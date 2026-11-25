"""The SceneSearch pipeline as graph nodes.

One node per stage of M2_DESIGN §3's query path, so the router can inspect what each produced and
decide whether to widen the constraint and try again. Every node is `async def node(state) -> dict`,
returns only the fields it changed, and catches its own failures into `error` rather than raising —
a half-built state that reaches `respond` is still answerable.
"""

from __future__ import annotations

import logging

from src.agents.state import AgentState
from src.config import get_settings
from src.services.llm import parse_constraint
from src.services.search import service
from src.services.search.artifacts import get_corpus
from src.services.search.rejection import contradiction_reason, low_confidence_note, rejection_reason
from src.services.search.videos import get_manifest

logger = logging.getLogger(__name__)


def _top_k(state: AgentState) -> int:
    """How many results this invocation asks for, falling back to the configured default.

    The graph is reachable without going through `SearchRequest` — `/chat`, the scene tools and the
    measurement scripts all invoke it directly — so the fallback here is a second entry point for
    the same decision, not dead defensiveness. It reads the same setting the request schema does,
    because the previous arrangement wrote `10` in both places and nothing would have failed if one
    of them had moved.
    """
    requested = state.get("top_k")
    return requested if requested is not None else get_settings().default_top_k


MAX_ITERATIONS = 3
OUT_OF_SCOPE_REASON = (
    "This search works on single frames, so it cannot find events that only exist across time. "
    "{why} Try describing what would be visible in one moment instead — for example "
    "'a car to the front-left' rather than 'a car cutting in'."
)

# What the same refusal becomes on a corpus that kept its source footage. The first sentence is the
# refusal's own claim, unweakened — one frame still cannot show a manoeuvre, and nothing below
# asserts that it did. What changes is that there is now somewhere to send the user to find out, so
# ending at "try a different query" would be withholding an answer the system has.
TEMPORAL_CAVEAT = "This search reads single frames, so it cannot confirm the movement itself. {why}"
TEMPORAL_SOURCE_NOTE = (
    TEMPORAL_CAVEAT + " These are the moments that look closest — each one links to the source "
    "video at that second, where the motion plays at full speed."
)

# Said, not swallowed. The parser drops an object-relative phrase because the vocabulary places
# things in the frame and never against each other; until now that drop was invisible, so "a
# motorbike to the right of a bus" was answered as "a motorbike and a bus, anywhere" with nothing
# to distinguish the two. Naming the dropped words lets the user re-aim; hiding them teaches them
# the search understood more than it did.
OBJECT_RELATIVE_NOTE = (
    "One part of that query was not searched for: '{phrase}' places one object relative to another, "
    "and this archive only records where something sits in the frame. These are frames containing "
    "the objects you named, in any arrangement."
)
UNSUPPORTED_MODIFIER_NOTE = (
    "The condition '{phrase}' could not be verified automatically — worth checking the results to confirm."
)


def object_relative_note(constraint: dict) -> str:
    """The caveat for a dropped phrase (spatial or modifier), or "" when nothing was dropped."""
    phrase = (constraint.get("unsupported_relation") or "").strip()
    if not phrase:
        return ""
    lower = f" {phrase.lower()} "
    if any(prep in lower for prep in (" of ", " behind ", " next to ", " between ", " beside ", " in front of ")):
        return OBJECT_RELATIVE_NOTE.format(phrase=phrase)
    return UNSUPPORTED_MODIFIER_NOTE.format(phrase=phrase)


def as_sentence(text: str) -> str:
    """Capitalise and terminate a model-supplied fragment so it can sit between two written ones.

    `out_of_scope` is free text from the parser and comes back as a clause, not a sentence — "cutting
    in is motion over time, not one frame". Substituted raw it produced "…across time. cutting in is
    motion over time, not one frame Try describing…", which reads as a rendering bug rather than an
    explanation. The fix belongs here and not in the prompt: the model will phrase this differently
    every time, and a template that only works for well-punctuated output is a template that breaks
    in front of a user eventually.
    """
    text = text.strip()
    if not text:
        return ""
    return text[0].upper() + text[1:] + ("" if text[-1] in ".!?" else ".")


async def parse_query_node(state: AgentState) -> dict:
    """Natural language → structured constraint. The only LLM call in the graph."""
    try:
        parsed = await parse_constraint(state.get("query", ""))
        return {"constraint": parsed.model_dump(), "iteration": 0, "relaxations": []}
    except Exception as exc:  # noqa: BLE001 - boundary with an external API; logged and surfaced
        logger.exception("query parsing failed")
        return {"error": f"could not interpret the query: {exc}", "iteration": 0}


async def retrieve_node(state: AgentState) -> dict:
    """Embed the query and rank the corpus. Independent of the constraint by design.

    Retrieval uses the raw query text, not the parsed constraint: the embedding carries meaning the
    9-category vocabulary cannot ("busy intersection", "difficult lighting"). The constraint is a
    filter applied after, not a replacement for the query.

    **The raw query, deliberately, and not `constraint["query_en"]` — measured, not assumed.**
    Issue #70 proposed feeding the English canonicalisation here too if Vietnamese retrieval turned
    out to be weak. It is not: over 8 en/vn pairs, the fraction of the top-10 whose *detected*
    metadata contains the queried object was 0.750 English against 0.787 Vietnamese, and the night
    tag was 1.00 in both. SigLIP2's text tower is trained on multilingual WebLI and reads Vietnamese
    directly. The two rankings agree only 0.275 at k=10 — different frames, equal quality — so
    translating here would not sharpen retrieval, it would discard a working multilingual encoder
    and add a translation's worth of drift. `verify_node` is the only stage that needs English.
    """
    try:
        ranked, scores = service.retrieve(state.get("query", ""))
        return {"ranked": ranked, "scores": scores}
    except (OSError, ValueError, RuntimeError) as exc:
        logger.exception("retrieval failed")
        return {"error": f"retrieval unavailable: {exc}"}


async def verify_node(state: AgentState) -> dict:
    """Does the archive contain this at all? M2_DESIGN §6.1, option B.

    **Runs on the retrieval ranking, before any reranking, and that ordering is load-bearing.**
    `rejection_tau` was calibrated in `rejection_ablation.py` against the caption similarity of
    SigLIP2's *unreranked* top-5. Filtering and diversity deliberately reorder that head — promoting
    frames for constraint satisfaction and spreading them across clips — so verifying afterwards
    scores a different set of frames than the threshold was measured on. Observed directly: "a
    pedestrian to the front-left" scores 0.431 before reranking and 0.395 after.

    It is also the better separation. Whether the archive holds something is a question about the
    archive; how results are arranged is a question about presentation. Only the first should decide
    whether the user is told "nothing matches".

    **Two refusals, not one, and they are told apart here.** A contradicted query (§10.8) is refused
    from the corpus's own scene tags rather than from a score, so it gets `contradiction_reason` —
    which states a fact instead of quoting a threshold and, unlike `rejection_reason`, does not
    suggest a rephrase that cannot work.

    **Scored in English, always** (issue #70). The caption encoder is `all-MiniLM-L6-v2` and the
    captions are Florence-2's, both English-only, so a Vietnamese query scored 0.057-0.123 against
    the same captions its English twin scored 0.145-0.707 on — under `tau_reject` every time, and
    with no relevance signal left to separate a real query from an empty one. Every Vietnamese query
    was therefore refused regardless of what the archive held. `query_en` is the same sentence in
    English, produced by the parse call that already runs, so this costs no extra latency or model.

    It falls back to the raw query when the parser returned nothing, which keeps a parse failure
    behaving exactly as it did before rather than verifying against an empty string — that would
    score every query near zero and refuse the entire archive.

    An English query's `query_en` is the query verbatim, which matters more than it looks: the band
    was calibrated on `all-MiniLM-L6-v2`'s score distribution over English queries, so a rephrase
    here would shift the scores the thresholds were fitted to and quietly invalidate them.
    """
    constraint = state.get("constraint")
    verify_text = (constraint or {}).get("query_en") or state.get("query", "")
    try:
        verdict, score, tau = service.verify(verify_text, state.get("ranked", []), constraint)
        if verdict == "no_match":
            impossible = service.contradicts_corpus(constraint)
            return {
                "matched": False,
                "verify_score": score,
                "confidence": None,
                "reason": (
                    contradiction_reason(get_corpus(), impossible)
                    if impossible
                    else rejection_reason(constraint, score, tau)
                ),
            }
        return {
            "matched": True,
            "verify_score": score,
            "confidence": verdict,
            "reason": low_confidence_note(score, tau) if verdict == "low" else "",
        }
    except (KeyError, ValueError, RuntimeError) as exc:
        logger.exception("verification failed")
        return {"error": f"verification failed: {exc}"}


async def rerank_node(state: AgentState) -> dict:
    """Metadata filter then scene-diversity cap, in that order — see retriever.py.

    Also counts how many displayed results actually satisfy the constraint, which is what tells the
    router whether the constraint was too narrow to be useful.
    """
    try:
        top_k = _top_k(state)
        constraint = state.get("constraint")
        ranked = service.rerank_candidates(state.get("ranked", []), state.get("scores", {}), constraint, top_k)
        return {"ranked": ranked, "satisfied_count": service.count_satisfying(ranked, constraint, top_k)}
    except (KeyError, ValueError) as exc:
        logger.exception("reranking failed")
        return {"error": f"reranking failed: {exc}"}


async def relax_node(state: AgentState) -> dict:
    """Widen a constraint that matched nothing, and record that it was widened.

    Relaxation order follows how much each condition can be trusted, worst first. Positions go
    before objects because a position is the weaker evidence: detector recall on positions is
    0.32–0.72 against object presence at car 0.97, pedestrian 0.67, so presence is given up last.
    The order has not changed, but half its reasoning has: until 2026-08-20 `front_left` and
    `front_right` were also *rare*, being edge-of-frame conditions at CAM_FRONT's 32.8° half-FOV
    (M2_DESIGN §9.2). The re-band cuts them at the outer thirds of the picture instead, so they are
    now ordinary rather than nearly-out-of-view — `pedestrian front_right` alone went from 167
    frames to 1,034. Weak, still; scarce, no longer.
    """
    constraint = dict(state.get("constraint") or {})
    relaxations = list(state.get("relaxations", []))
    if constraint.get("relations"):
        constraint["relations"] = {}
        relaxations.append("ignored the position, which the detector reads least reliably")
    elif len(constraint.get("objects") or []) > 1:
        dropped = constraint["objects"][1:]
        constraint["objects"] = constraint["objects"][:1]
        relaxations.append(f"searched without {', '.join(dropped)}")
    return {"constraint": constraint, "relaxations": relaxations, "iteration": state.get("iteration", 0) + 1}


async def respond_node(state: AgentState) -> dict:
    """Assemble the answer — results and their variety, or an honest reason there are none."""
    if state.get("error"):
        return {"results": [], "distinct_scenes": 0, "reason": "Search is temporarily unavailable. Please try again."}

    constraint = state.get("constraint") or {}
    # Free text from the parser, e.g. "cutting in is motion over time, not one frame". Set means the
    # query asked for something no single frame can settle; whether that is the end of the answer
    # depends on whether this corpus can point at the footage — see `route_after_parse`.
    unconfirmable = constraint.get("out_of_scope")
    if unconfirmable and not get_manifest():
        return {
            "results": [],
            "distinct_scenes": 0,
            "matched": False,
            "reason": OUT_OF_SCOPE_REASON.format(why=as_sentence(unconfirmable)),
        }
    ignored = object_relative_note(constraint)
    if not state.get("matched"):
        # The caveat belongs on a refusal *more* than on a hit, not less. The user is being told the
        # archive holds nothing like this, while part of what they asked was never searched for —
        # without the note they would rephrase the half that was already working.
        #
        # The temporal caveat leads for the same reason, and without the "here are the moments" half
        # it normally carries: there are none. Measured on Hanoi, no motion query fell this far —
        # they score 0.35-0.51 against `tau_reject` 0.30 — but a query that does must not be refused
        # as if the archive lacked motorbikes when what it lacks is a way to see them move.
        leading = TEMPORAL_CAVEAT.format(why=as_sentence(unconfirmable)) if unconfirmable else ""
        return {
            "results": [],
            "distinct_scenes": 0,
            "reason": " ".join(n for n in (leading, state.get("reason", ""), ignored) if n),
        }

    top_k = _top_k(state)
    ranked, scores = state.get("ranked", []), state.get("scores", {})
    hits = service.build_hits(ranked, scores, constraint, top_k)

    # These caveats can apply at once and none may overwrite another: the results can be
    # low-confidence, *and* the product of a widened constraint, *and* missing a clause the
    # vocabulary could not express. Each is something the user needs to judge what they see.
    # Four caveats can now apply at once. The temporal one leads because it qualifies what the
    # results *are* — closest moments, not confirmed manoeuvres — where the other three qualify how
    # well they match.
    leading = TEMPORAL_SOURCE_NOTE.format(why=as_sentence(unconfirmable)) if unconfirmable else ""
    notes = [n for n in (leading, state.get("reason", ""), ignored) if n]
    if relaxed := state.get("relaxations", []):
        notes.append(f"Nothing matched exactly, so the search was widened: {'; '.join(relaxed)}.")
    return {
        "results": hits,
        "distinct_scenes": service.count_distinct_scenes(get_corpus(), ranked, top_k),
        "reason": " ".join(notes),
    }
