"""Stage functions for the query path, one per graph node.

Deliberately granular rather than a single `search()`: the LangGraph agent needs to run these as
separate steps so it can inspect what came back and decide whether to relax the constraint and try
again. A monolithic call would hide the state the router needs.

Ordering is not free-form — `retriever.py` explains why filter must precede diversity — so
`rerank_candidates` applies both as one step rather than exposing two the graph could reorder.
"""

from __future__ import annotations

import numpy as np

from src.config import get_settings
from src.models.schemas import FrameHit, MomentRef, SourceClip
from src.services.search.artifacts import Corpus, get_corpus
from src.services.search.diversity import SceneCapReranker
from src.services.search.encoder import calibrated_match_probability, get_caption_encoder, get_query_encoder
from src.services.search.filters import (
    MetadataFilterReranker,
    metadata_constraint,
    satisfied_conditions,
)
from src.services.search.index import FlatIndex
from src.services.search.moments import MomentStore, get_moments
from src.services.search.rejection import classify, contradicted, verify_match
from src.services.search.videos import VideoManifest, get_manifest

_index: FlatIndex | None = None


def get_index() -> FlatIndex:
    """Process-wide flat index over the corpus vectors."""
    global _index
    if _index is None:
        corpus = get_corpus()
        _index = FlatIndex(corpus.vectors, corpus.frame_ids)
    return _index


def _retrieve_pgvector(query_vec: np.ndarray) -> tuple[list[str], dict[str, float]]:
    """Rank frames directly in PostgreSQL using pgvector cosine distance (`<=>`)."""
    import psycopg2

    q = query_vec.reshape(-1).astype("float32")
    q_str = "[" + ",".join(f"{x:.8g}" for x in q.tolist()) + "]"
    url = get_settings().database_url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    with psycopg2.connect(url, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL enable_indexscan = off;")
            cur.execute(
                """
                SELECT frame_id, 1 - (image_vector <=> %s::vector) AS score
                FROM public.frames
                ORDER BY image_vector <=> %s::vector
                """,
                (q_str, q_str),
            )
            rows = cur.fetchall()
    ranked = [r[0] for r in rows]
    scores = {r[0]: float(r[1]) for r in rows}
    return ranked, scores


def retrieve(query: str) -> tuple[list[str], dict[str, float]]:
    """Embed the query and rank the whole corpus by cosine similarity."""
    corpus = get_corpus()
    q_vec = get_query_encoder().encode(query)
    if corpus.vectors.shape[0] == 0:
        return _retrieve_pgvector(q_vec)
    return get_index().search(q_vec)


def rerank_candidates(ranked: list[str], scores: dict[str, float], constraint: dict | None, top_k: int) -> list[str]:
    """Apply the metadata filter, then the scene-diversity cap over the displayed head.

    `top_k` sets the diversity window: it must equal the number of results shown, because capping
    further down costs ranking quality and buys no additional diversity (M2_DESIGN §7).
    """
    settings = get_settings()
    corpus = get_corpus()
    chain = [
        MetadataFilterReranker(corpus.metadata_of, metadata_constraint(constraint)),
        SceneCapReranker(corpus.scene_of, settings.diversity_cap, window=top_k),
    ]
    for reranker in chain:
        ranked = reranker.rank(ranked, scores)
    return ranked


def contradicts_corpus(constraint: dict | None) -> list[str]:
    """Scene conditions this query names that no frame in the corpus carries. See `rejection.contradicted`."""
    return contradicted(get_corpus(), constraint)


def verify(query: str, ranked: list[str], constraint: dict | None = None) -> tuple[str, float, float]:
    """Caption-verify the head of the ranking. Returns (verdict, score, tau_confident).

    M2_DESIGN §6.1 option B, as a three-way band — see `rejection.classify`. `tau_confident` comes
    back with it so callers can explain the decision without reading settings themselves.

    On a caption-deferred corpus this is where option B stops being a lookup and becomes the O(k)
    captioning it was always argued as. It is the only step that can block for seconds, and only for
    frames nobody has verified before; `retrieve` and `rerank_candidates` above are unaffected, so
    the results are already on screen when it runs.

    The contradiction check runs *before* that captioning and not after (§10.8). It is free, it is
    the only refusal here that does not go through a threshold, and short-circuiting it first means a
    query the archive provably cannot answer never pays the ~5 s/frame a deferred corpus charges to
    find that out. `constraint` defaults to None so a caller with no parse degrades to the caption
    check alone rather than to a wrong refusal.
    """
    settings = get_settings()
    corpus = get_corpus()
    if contradicted(corpus, constraint):
        return "no_match", 0.0, settings.tau_confident
    if corpus.captions_deferred:
        from src.services.search.captions import embed_cached, ensure_captions

        embed_cached(corpus)
        ensure_captions(corpus, ranked[: settings.verify_top_k])
    ok, score = verify_match(corpus, get_caption_encoder().encode(query), ranked, top_k=settings.verify_top_k)
    if not ok:
        return "no_match", score, settings.tau_confident
    verdict = classify(score, settings.tau_reject, settings.tau_confident)
    return verdict, score, settings.tau_confident


def source_clip(corpus: Corpus, manifest: VideoManifest, frame_id: str) -> SourceClip | None:
    """The footage this frame came from, seeked to its own timestamp — or None when there is none.

    Three ways to get None and they are all ordinary: the corpus records no `video_id` for the
    frame, the manifest does not name that clip, or there is no manifest at all because the corpus
    kept no source video. None of them is an error and none of them may cost a result.
    """
    url = manifest.deep_link(corpus.video_of.get(frame_id, ""), corpus.timestamp_of.get(frame_id, 0.0))
    return None if url is None else SourceClip(url=url, **manifest.credit(corpus.video_of[frame_id]))


def moment_ref(moments: MomentStore, frame_id: str) -> MomentRef | None:
    """The redacted clip cut around this frame, if one was built. Null for almost every frame."""
    clip = moments.for_frame(frame_id)
    if clip is None:
        return None
    return MomentRef(
        id=clip["id"],
        video_url=f"/api/v1/moments/{clip['id']}/video",
        closest_m=min((t["closest_m"] for t in clip.get("tracks") or []), default=None),
        events=clip.get("events") or [],
    )


def build_hits(ranked: list[str], scores: dict[str, float], constraint: dict | None, top_k: int) -> list[FrameHit]:
    """Top-k ids → API results, each carrying the conditions it actually satisfies."""
    corpus = get_corpus()
    manifest = get_manifest()
    moments = get_moments()
    checkable = metadata_constraint(constraint)
    # Resolved once for the page rather than per hit: it is a scan of the merge record, and it is
    # the same answer for every frame in the response.
    source_names = corpus.source_names
    return [
        FrameHit(
            frame_id=fid,
            scene_id=corpus.scene_of.get(fid, ""),
            timestamp_s=corpus.timestamp_of.get(fid, 0.0),
            score=round(scores.get(fid, 0.0), 4),
            match_probability=_calibrated(scores.get(fid, 0.0)),
            thumb_url=f"/api/v1/frames/{fid}/thumb",
            # Which corpus this frame came from, or None. `.get` twice on purpose: a frame with no
            # `video_id`, or one whose part of the merge recorded no name, is unattributable and
            # says so by being absent — the card renders nothing there rather than a default.
            corpus=source_names.get(corpus.video_of.get(fid, "")),
            satisfied=satisfied_conditions(corpus.metadata_of.get(fid), checkable),
            # The evidence the rejection verdict was actually formed from. `verify` already scores
            # the query against these captions and never showed them, so every card asserted the
            # same generic sentence while the system held something specific about each frame.
            # `.get` rather than `[...]`: a caption-deferred corpus captions at query time, so a
            # frame outside the verified head legitimately has none yet.
            caption=corpus.caption_of.get(fid),
            # The one thing on this card that can show motion. Computed per hit rather than once for
            # the response because a mixed corpus — the `--merge` tool that does not exist yet —
            # would hold frames from clips that are linkable and clips that are not.
            source=source_clip(corpus, manifest, fid),
            # The other half: a clip this service actually holds, where one was cut around this
            # frame. Both are offered rather than one replacing the other — the clip is ours and
            # redacted, the deep link is the untouched original and is what makes the claim checkable.
            moment=moment_ref(moments, fid),
        )
        for fid in ranked[:top_k]
    ]


def _calibrated(cosine: float) -> float | None:
    """Rounded match probability, or None when the encoder has not been loaded."""
    p = calibrated_match_probability(cosine)
    return None if p is None else round(p, 4)


def count_distinct_scenes(corpus: Corpus, ranked: list[str], top_k: int) -> int:
    """Distinct source clips in the head — how much variety the answer actually shows."""
    return len({corpus.scene_of.get(f, f) for f in ranked[:top_k]})


def count_satisfying(ranked: list[str], constraint: dict | None, top_k: int) -> int:
    """How many of the displayed results actually meet the structured constraint.

    This is what tells the graph a constraint was too narrow. The metadata filter is a *rerank*, not
    a hard filter, so it always returns a full ranking — "no results" never happens, and the real
    signal is that the promoted head satisfies nothing. Zero here means either the user asked for a
    combination the archive lacks, or the detector missed it; relaxing distinguishes the two by
    trying again without the weakest condition.
    """
    checkable = metadata_constraint(constraint)
    if not checkable:
        return top_k  # nothing structured was asked, so nothing can be unsatisfied
    corpus = get_corpus()
    from src.services.search.filters import satisfies

    return sum(1 for f in ranked[:top_k] if (m := corpus.metadata_of.get(f)) and satisfies(m, checkable))


def caption_similarity(query_vec: np.ndarray, frame_id: str) -> float:
    """Query-to-caption similarity for one frame. Used by the verify tool for explanations."""
    corpus = get_corpus()
    if corpus.caption_vectors.shape[0] == 0:
        import psycopg2

        q = query_vec.reshape(-1).astype("float32")
        q_str = "[" + ",".join(f"{x:.8g}" for x in q.tolist()) + "]"
        url = get_settings().database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        with psycopg2.connect(url, connect_timeout=15) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 - (caption_vector <=> %s::vector) FROM public.frames WHERE frame_id = %s",
                    (q_str, frame_id),
                )
                row = cur.fetchone()
                return float(row[0]) if row and row[0] is not None else 0.0
    pos = corpus.frame_ids.index(frame_id)
    return float(corpus.caption_vectors[pos] @ query_vec.reshape(-1).astype("float32"))
