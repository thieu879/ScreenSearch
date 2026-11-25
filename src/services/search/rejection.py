"""Saying "nothing matches" — M2_DESIGN §6.1, option B.

An engineer searching for footage the archive does not contain must be told so. Ten confident wrong
frames cost more than an empty result, because they have to be watched to find out they are wrong.

**Why captions and not the retrieval score.** Option A — threshold SigLIP2's own top-1 — was
eliminated on its operating point rather than its AUROC. At *every* cutoff it either discards two in
five legitimate searches or refuses almost no empty ones: 23 of 24 negatives outscore its weakest
real query. A global image embedding is a scene-appearance representation, so it can tell a scene is
not snowy but not that an ambulance is absent, because a street without an ambulance still looks
like a street. A caption is an enumeration, so a missing mention is evidence of absence.

Measured on query set v3 (18 positives, 24 negatives, 432 pairwise comparisons):

    option                          Neg-AUROC   answers   refuses   captioning
    A  threshold SigLIP2 top-1          0.755       61%       92%   none
    B  caption-verify top-5             0.898       78%       88%   5 frames/query
    C  full caption index               0.907       89%       83%   all N, 23x ingest

**More verification is worse.** k=5 beats k=10 (0.887) and k=20 (0.884): the score is a max over k
captions, so a larger k gives an *empty* query more chances to hit one spuriously agreeable caption.

**On cost, precisely.** Option B's argument is that rejection only needs to judge the frames being
returned, so captioning costs O(k) per query instead of O(N) across the archive — at §5's 7.2M-frame
projection, ~20 s of deferred work against ~8,000 CPU-hours of ingest. On *this* corpus all 404
frames are already captioned, so the runtime path below is a lookup either way. The saving is the
scale story, not the demo's latency; the decision rule is identical in both.
"""

from __future__ import annotations

import numpy as np

from src.services.search.artifacts import Corpus, get_corpus
from src.services.search.filters import TAGGED_AXES, declared_vocabulary, tagged_values


def contradicted(corpus: Corpus, constraint: dict | None) -> list[str]:
    """Conditions the query names that this archive **provably** cannot satisfy.

    The one refusal in the system that is not a threshold — M2_DESIGN §10.8. Option B decides by
    caption similarity, and a caption enumerates what is *there*; it never contradicts. So `a street
    at night` scored 0.559 on a corpus whose every frame is tagged `day`, because the captions
    describe a street and simply never mention time. No cut point fixes that, because the score is
    not wrong about anything it measured.

    Two fields can contradict, and the corpus already knows both. Returns labels in the same
    `scene:time=night` / `object:traffic_cone` form `satisfied_conditions` emits, so a refusal reads
    like the evidence.

    **Scene tags** (§10.8): `tag_scenes.py` writes `time` at ingest, `schemas.py` parses
    `scene: {time: night}` out of the query, and `filters.py` lists the axis in `TAGGED_AXES`.

    **Object categories** — and this half is now **unreachable on a corpus whose detector declares
    the parser's own vocabulary**, which is the invariant `schemas.py` holds as of 2026-08-18.

    It was written 2026-08-14 for the case where the parser could name nine categories and
    `COCO_TO_VOCAB` mapped six, treating that gap as proof of absence. **The premise was wrong**
    (issue #112): an unemittable class means *we cannot check*, not *it is not there*. All three
    orphans turned out to be plainly present in the served corpus — 241 of 6,858 captions name
    traffic cones, thumbnails confirm cones, barriers and a forklift, and retrieval already ranked a
    cone first at a verified 0.753. The refusal was overriding a correct answer with a statement of
    certainty. Closing the vocabulary gap removed the input rather than patching the rule.

    What remains here is still correct and still worth keeping: a corpus really can be ingested by a
    detector that declares *fewer* categories than the parser knows, and then a query naming one of
    the missing ones genuinely cannot be checked. It just cannot arise from the shipped pairing.

    Silent by construction where it should be: an axis no frame carries is absent from the census, a
    condition the query does not name is not checked, `weather` is outside `TAGGED_AXES`, and a
    corpus whose provenance declares no vocabulary refuses no category at all — so each of those
    falls through to the embedding rather than being refused from a field we chose not to write.
    """
    return _contradicted_scene(corpus, constraint) + _contradicted_objects(corpus, constraint)


def _contradicted_scene(corpus: Corpus, constraint: dict | None) -> list[str]:
    """Tagged scene values no frame in the corpus carries."""
    asked = {k: v for k, v in ((constraint or {}).get("scene") or {}).items() if k in TAGGED_AXES}
    if not asked:
        return []
    census = tagged_values(corpus.metadata_of)
    return [f"scene:{axis}={value}" for axis, value in asked.items() if axis in census and value not in census[axis]]


def _contradicted_objects(corpus: Corpus, constraint: dict | None) -> list[str]:
    """Requested categories outside the vocabulary this corpus's detector can emit.

    Deliberately *not* "categories with zero frames" — see `filters.declared_vocabulary` for why a
    count cannot carry this claim.
    """
    asked = (constraint or {}).get("objects") or []
    vocabulary = declared_vocabulary(corpus.provenance)
    if not asked or not vocabulary:
        return []
    return [f"object:{category}" for category in asked if category not in vocabulary]


def contradiction_reason(corpus: Corpus, conditions: list[str]) -> str:
    """Why a contradicted query is refused, in the archive's own terms rather than a score.

    Deliberately different from `rejection_reason`, which ends with "best match 0.42 against a 0.50
    threshold" and invites a rephrase. That advice is right when a score was marginal and wrong here:
    no wording finds night footage in a daytime archive, and offering the suggestion anyway sends the
    user round a loop that cannot terminate. This is the one refusal the product can state as fact.
    """
    clauses = [c for c in (_scene_clause(corpus, conditions), _object_clause(corpus, conditions)) if c]
    return (
        f"Nothing in this archive matches, and this one is certain rather than a close call: "
        f"{'; and '.join(clauses)}. "
        f"That is the archive's own record of what it holds, written from the pixels at ingest, not a "
        f"similarity score — so rephrasing will not surface this footage, because there is none to find."
    )


def _scene_clause(corpus: Corpus, conditions: list[str]) -> str:
    """ "no frame is tagged time=night — all 6,858 are tagged time=day"."""
    asked = dict(c.removeprefix("scene:").split("=", 1) for c in conditions if c.startswith("scene:"))
    if not asked:
        return ""
    census = tagged_values(corpus.metadata_of)
    held = "; ".join(
        f"all {corpus.n_frames:,} are tagged {axis}={'/'.join(sorted(census[axis]))}"
        for axis in asked
        if axis in census
    )
    return f"no frame is tagged {', '.join(f'{k}={v}' for k, v in asked.items())} — {held}"


def _object_clause(corpus: Corpus, conditions: list[str]) -> str:
    """Names the vocabulary rather than a frame count, because that is what the claim rests on.

    "we found none" would be the wrong sentence: it invites the reader to assume the detector looked
    and missed, when in fact the category was never expressible. Saying what the archive *can*
    record also tells the user where to go next, which a bare refusal does not.
    """
    asked = [c.removeprefix("object:") for c in conditions if c.startswith("object:")]
    if not asked:
        return ""
    vocabulary = "/".join(sorted(declared_vocabulary(corpus.provenance)))
    return (
        f"this archive records no {', '.join(asked)} at all — the detector that read its "
        f"{corpus.n_frames:,} frames can only label {vocabulary}, so none was ever recorded"
    )


def verify_match(
    corpus: Corpus, query_caption_vec: np.ndarray, ranked: list[str], top_k: int = 5
) -> tuple[bool, float]:
    """Does the archive plausibly contain what was asked? Returns (matched, score).

    Scores the query against the captions of the top-`top_k` retrieved frames and keeps the best.
    Compared against `settings.rejection_tau` by the caller, so the threshold stays configuration
    rather than a literal buried here.
    """
    head = ranked[:top_k]
    if not head:
        return False, 0.0
    if corpus.caption_vectors.shape[0] == 0:
        import psycopg2
        from src.config import get_settings

        valid = [f for f in head if f in corpus.scene_of]
        if not valid:
            return False, 0.0
        q = query_caption_vec.reshape(-1).astype("float32")
        q_str = "[" + ",".join(f"{x:.8g}" for x in q.tolist()) + "]"
        url = get_settings().database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        with psycopg2.connect(url, connect_timeout=15) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT MAX(1 - (caption_vector <=> %s::vector)) FROM public.frames WHERE frame_id = ANY(%s)",
                    (q_str, valid),
                )
                row = cur.fetchone()
                if not row or row[0] is None:
                    return False, 0.0
                return True, float(row[0])
    pos = {fid: n for n, fid in enumerate(corpus.frame_ids)}
    rows = [pos[f] for f in head if f in pos]
    if not rows:
        return False, 0.0
    sims = corpus.caption_vectors[rows] @ query_caption_vec.reshape(-1).astype("float32")
    return True, float(sims.max())


def classify(score: float, tau_reject: float, tau_confident: float) -> str:
    """Score → one of `high`, `low`, `no_match`.

    Three outcomes rather than two because a single cutoff forces the system to choose between two
    unequal errors. Showing something wrong is recoverable — the user sees it and rephrases. Hiding
    something real is not: they are told the archive lacks footage it holds, and there is nothing in
    the interface to suggest otherwise. The band lets the marginal cases be *labelled* instead of
    silently decided, and keeps an outright refusal for the queries that genuinely have no answer.
    """
    if score >= tau_confident:
        return "high"
    return "low" if score >= tau_reject else "no_match"


def low_confidence_note(score: float, tau: float) -> str:
    """Caveat shown alongside results the caption check could not confirm."""
    return (
        f"These results may not be what you asked for. The archive was searched and these are its "
        f"closest frames, but a check against their descriptions could not confirm the match "
        f"({score:.2f} against a {tau:.2f} confidence threshold) — worth scanning before relying "
        f"on them."
    )


def _archive_size() -> str:
    """ "6,858 keyframes from 170 driving clips", read from provenance at call time.

    Falls back to a phrasing with no numbers rather than raising: this is one clause of an
    explanation, and a corpus that cannot be described is not a reason to fail a response the user
    is already owed.
    """
    try:
        p = get_corpus().provenance
        return f"{p['n_frames']:,} keyframes from {p['n_scenes']} driving clips"
    except (OSError, KeyError, ValueError):
        return "keyframes from driving clips"


def _archive_description() -> str:
    """ " recorded in Boston and Singapore ...", read from provenance at call time.

    The leading space is part of the return: this is an optional clause spliced into a sentence
    that has to read correctly without it.

    **Why this is not a literal.** It was one until 2026-08-25, and `_archive_size()` above already
    carries half the lesson — the counts were moved here after the message spent weeks promising
    "404 keyframes from 10 clips". The place and date stayed behind, so a local run against
    `data/staging/hanoi` told the user its 2,211 Hanoi keyframes were "recorded in Boston and
    Singapore between July and November 2018". A number that goes stale is bad; a provenance claim
    that is simply false about the footage on disk is worse, because this sentence's whole purpose
    is to be trusted about the archive.

    Returns "" for a corpus that does not describe itself, which shortens the sentence to a claim
    that is true of any corpus. Silence is the only safe default here — inheriting another corpus's
    description is exactly the failure this exists to prevent.
    """
    try:
        desc = get_corpus().provenance.get("corpus_description", "")
    except (OSError, KeyError, ValueError):
        return ""
    return f" {desc.strip()}" if isinstance(desc, str) and desc.strip() else ""


def rejection_reason(constraint: dict | None, score: float, tau: float) -> str:
    """Plain-English why, for a query the archive appears not to answer.

    Deliberately says nothing about which *objects* were asked for. An earlier version opened with
    "No frames with pedestrian in this archive", which is false and badly so — pedestrians are the
    second most common category in the corpus. The rejection is about the query as a whole, not
    about any noun in it, and a message that blames one noun teaches the user something untrue.

    The corpus description is concrete for the same reason: an engineer told "nothing matches"
    should be able to see *why* without guessing, and to judge whether to look elsewhere. Every
    part of it — the counts and the description of the footage alike — comes from
    `provenance.json` rather than from this file — they were written here as
    literals once, and went on telling users the archive held 404 keyframes from 10 clips for as
    long as it actually held 6,858 from 170. A sentence whose whole purpose is to be trusted about
    the archive is the worst place to keep a number that has to be updated by hand.
    """
    return (
        f"Nothing in this archive appears to match that. It holds {_archive_size()}"
        f"{_archive_description()}. "
        f"If you expected a match, try describing the scene more simply: the check scores the "
        f"whole phrase, so extra detail can push a real result below the line. "
        f"(Best match {score:.2f} against a {tau:.2f} threshold.)"
    )
