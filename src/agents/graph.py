"""SceneSearch agent graph.

    parse ──► retrieve ──► verify ──┬─ nothing matches ──────────────────► respond ──► END
                                    └─ matched ──► rerank ──┬─ usable ───► respond
                                                     ▲      │
                                                     └ relax ┘  constraint satisfied by nothing

    parse ──► respond                  error, or out-of-scope query

**Verify sits before rerank, and that is deliberate.** Two different questions are being asked, and
conflating them mis-calibrates the first. *Does the archive contain this?* is about the archive, and
`rejection_tau` was measured against SigLIP2's unreranked top-5. *How should results be arranged?*
is about presentation. Reranking reorders the head — that is its job — so verifying afterwards would
score frames the threshold was never fitted to (measured: 0.431 before, 0.395 after, across a 0.457
threshold).

The loop therefore keys on **constraint satisfaction, not rejection**. The metadata filter is a
rerank rather than a hard filter, so a ranking is never empty; the real signal that a constraint was
too narrow is that none of the displayed results satisfy it. Relaxing and re-ranking distinguishes
"the archive lacks this combination" from "the detector missed it".

The loop returns to **rerank**, not retrieve: retrieval embeds the raw query text and is unaffected
by the constraint, so re-running it would repeat the most expensive step of the request for a
byte-identical answer.

Bounded twice — by `MAX_ITERATIONS`, and by `can_relax`, which stops as soon as there is nothing
left to give up. The counter is a backstop; running out of constraint is the usual exit.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from src.agents.nodes.search_nodes import (
    MAX_ITERATIONS,
    parse_query_node,
    relax_node,
    rerank_node,
    respond_node,
    retrieve_node,
    verify_node,
)
from src.agents.state import AgentState
from src.services.search.videos import get_manifest


def can_relax(constraint: dict | None) -> bool:
    """Is any condition left to give up? Positions first, then surplus objects."""
    if not constraint:
        return False
    return bool(constraint.get("relations")) or len(constraint.get("objects") or []) > 1


def route_after_parse(state: AgentState) -> str:
    """Skip retrieval when there is nothing worth retrieving.

    An out-of-scope query is not a question answered badly — it is one that single-frame retrieval
    cannot answer at all (M2_DESIGN §7). Returning ten confident frames for "a vehicle cutting into
    our lane" is the exact failure this product exists to prevent.

    **That claim is about one frame, and it stops being the whole story once the corpus keeps its
    source footage.** `llm.py` sets `out_of_scope` because a still cannot show motion — true, and
    unchanged. But a corpus with a `videos.json` can hand the user the second of video the frame was
    taken from, where the motion is visible at 60 fps. So the branch retrieves, and `respond_node`
    answers with the moments plus links and the caveat that the manoeuvre itself is unconfirmed —
    which asserts strictly less than the refusal it replaces, not more.

    **Nothing changes on the served corpus.** nuScenes pruned its source blobs after extraction and
    can never carry a manifest, so `get_manifest()` is empty there and the refusal stands exactly as
    it did. The parser is untouched either way: this is what the branch *does*, not what it knows —
    `_SYSTEM` is at its measured size limit and growing it is what broke `v1.6`.
    """
    if state.get("error"):
        return "respond"
    if (state.get("constraint") or {}).get("out_of_scope") and not get_manifest():
        return "respond"
    return "retrieve"


def route_after_verify(state: AgentState) -> str:
    """Arrange an answer, or stop because there is nothing to arrange."""
    if state.get("error") or not state.get("matched"):
        return "respond"
    return "rerank"


def route_after_rerank(state: AgentState) -> str:
    """Answer, or give up the weakest condition and rerank once more.

    Relaxing is only worth doing when the constraint is satisfied by *nothing* on display. A partial
    match is still a useful answer, and widening it would trade real hits for weaker ones.
    """
    if state.get("error"):
        return "respond"
    if (
        state.get("satisfied_count", 0) == 0
        and state.get("iteration", 0) < MAX_ITERATIONS
        and can_relax(state.get("constraint"))
    ):
        return "relax"
    return "respond"


def build_graph():
    """Wire and compile the graph.

    Both conditional edges pass an explicit map covering every value their router can return,
    including the fallback. A router returning a name absent from the map fails at *runtime*, well
    after the graph looks fine, so the mapping is written out rather than left to inference.
    """
    graph = StateGraph(AgentState)
    graph.add_node("parse", parse_query_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("rerank", rerank_node)
    graph.add_node("verify", verify_node)
    graph.add_node("relax", relax_node)
    graph.add_node("respond", respond_node)

    graph.set_entry_point("parse")
    graph.add_conditional_edges("parse", route_after_parse, {"retrieve": "retrieve", "respond": "respond"})
    graph.add_edge("retrieve", "verify")
    graph.add_conditional_edges("verify", route_after_verify, {"rerank": "rerank", "respond": "respond"})
    graph.add_conditional_edges("rerank", route_after_rerank, {"relax": "relax", "respond": "respond"})
    graph.add_edge("relax", "rerank")
    graph.add_edge("respond", END)
    return graph.compile()


agent = build_graph()
