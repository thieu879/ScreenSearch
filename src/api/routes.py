"""SceneSearch HTTP endpoints. Contract and rationale: `docs/api-contract.md`."""

from __future__ import annotations

import logging
import os
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response

from src.agents.graph import agent
from src.api.auth_middleware import get_current_user
from src.api.ratelimit import limit_llm, limit_writes
from src.api.security import current_operator, require_operator
from src.config import get_settings
from src.db.models import User
from src.models.schemas import (
    ChatRequest,
    ChatResponse,
    ContextFrame,
    Decision,
    FrameContextResponse,
    MomentClip,
    MomentDetail,
    MomentTrack,
    ReviewRecord,
    ReviewRequest,
    ReviewSummary,
    ReviewUndo,
    SearchRequest,
    SearchResponse,
)
from src.services import export
from src.services.reviews import ReviewKey, get_store, reviewer_identity
from src.services.search.artifacts import get_corpus
from src.services.search.band import band_status
from src.services.search.context import MAX_WINDOW_S, preceding_frames
from src.services.search.density import MIN_STRIP_FRAMES, corpus_density
from src.services.search.moments import get_moments
from src.services.search.service import source_clip
from src.services.search.videos import get_manifest

logger = logging.getLogger(__name__)
router = APIRouter()

# Thumbnails are immutable: frame_id is content-derived and the image behind it never changes, so a
# browser may keep them indefinitely. Without this, a results grid refetches every thumbnail on
# every search.
_THUMB_CACHE = "public, max-age=31536000, immutable"


@router.post("/search", response_model=SearchResponse, dependencies=[Depends(limit_llm)])
async def search(request: SearchRequest) -> SearchResponse:
    """Search the archive, or report honestly that it holds nothing matching.

    Rate-limited because it is the one endpoint that spends money — one gpt-4o-mini call per
    request, on a public URL with no credential. `api/ratelimit.py` has the two limits and why.
    """
    try:
        state = await agent.ainvoke({"query": request.query, "top_k": request.top_k})
    except Exception as exc:  # noqa: BLE001 - outermost boundary; nothing above this can recover
        # The detail is deliberately generic. The template returned str(e), which hands the caller
        # an OpenAI stack trace or a filesystem path; the rubric asks for errors that never leak
        # raw exceptions, and the real message belongs in the log where an operator can see it.
        logger.exception("search failed for query %r", request.query)
        raise HTTPException(status_code=500, detail="Search failed. Please try again.") from exc

    return SearchResponse(
        matched=bool(state.get("matched")),
        confidence=state.get("confidence") if state.get("matched") else None,
        # An empty reason alongside a match means "nothing worth saying"; None is cleaner on the wire.
        reason=state.get("reason") or None,
        constraint=state.get("constraint") or {},
        results=state.get("results", []),
        distinct_scenes=state.get("distinct_scenes", 0),
    )


# frame_id is a nuScenes sample token plus a camera suffix: 32 hex characters, an underscore, then
# the camera name. Validating the shape is a whitelist rather than a blacklist — it admits only ids
# the corpus could actually contain, so no traversal sequence, absolute path or drive letter is
# expressible in the first place.
_FRAME_ID = re.compile(r"^[0-9a-f]{32}_[A-Z_]+$")


@router.get("/frames/{frame_id}/thumb")
async def frame_thumb(frame_id: str) -> Response:
    """Downscaled JPEG for one frame. Derived from nuScenes (CC BY-NC-SA 4.0)."""
    settings = get_settings()
    if not _FRAME_ID.match(frame_id):
        raise HTTPException(status_code=404, detail="No thumbnail for that frame id.")

    # Belt and braces: still resolve and require containment. The pattern above already makes this
    # unreachable, but the two checks fail independently, and a later change to the id format
    # would otherwise silently remove the only protection.
    root = os.path.abspath(settings.thumbs_dir)
    path = os.path.abspath(os.path.join(root, f"{frame_id}.jpg"))
    try:
        contained = os.path.commonpath([root, path]) == root
    except ValueError:
        # Raised when the two paths are on different Windows drives. Left unhandled this returned a
        # 500 for what is simply an unknown id — an error the client cannot act on, and one that
        # leaks the fact that something unusual happened.
        contained = False
    if contained and os.path.exists(path):
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": _THUMB_CACHE})

    try:
        img_url = get_corpus().image_url_of.get(frame_id)
    except Exception:
        img_url = None
    if img_url:
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url=img_url, status_code=307, headers={"Cache-Control": _THUMB_CACHE})

    raise HTTPException(status_code=404, detail="No thumbnail for that frame id.")


@router.get("/frames/{frame_id}/context", response_model=FrameContextResponse)
async def frame_context(
    frame_id: str,
    before: float = Query(3.0, ge=0.5, le=MAX_WINDOW_S, description="Seconds of lead-in to return"),
) -> FrameContextResponse:
    """The frames leading up to one hit, so a still can be judged as a moment.

    Reads only what the corpus already holds — these frames are published and redacted like any
    other. It is a preview, not temporal retrieval: motion-over-time queries are still refused.

    **It says when it could not do that, rather than returning one frame and calling it a strip.**
    Whether a window yields a moment is a property of the corpus's sampling density, and nothing
    used to report it: at nuScenes' 0.50 s spacing a ±3 s window is 7 stills, at the staged Hanoi
    corpus's 5.00 s it is the anchor alone **83% of the time** — the frame already on screen,
    relabelled. Promote a sparse corpus and this route starts asserting that while `/health` and
    `/status` stay green, which is the shape of the spatial-band and rejection-band failures before
    PR #117. `mode` is decided from what the window actually returned, so it is right per frame even
    where spacing is not uniform, and `source` carries the affordance that still works.
    """
    corpus = get_corpus()
    if not _FRAME_ID.match(frame_id) or frame_id not in corpus.scene_of:
        raise HTTPException(status_code=404, detail="No such frame id.")
    anchor_t = corpus.timestamp_of[frame_id]
    found = preceding_frames(corpus, frame_id, before)
    return FrameContextResponse(
        frame_id=frame_id,
        scene_id=corpus.scene_of[frame_id],
        timestamp_s=anchor_t,
        requested_before_s=before,
        frames=[
            ContextFrame(
                frame_id=fid,
                timestamp_s=t,
                offset_s=round(t - anchor_t, 3),
                thumb_url=f"/api/v1/frames/{fid}/thumb",
            )
            for t, fid in found
        ],
        # The scene simply may not reach back that far; say so rather than returning a short strip
        # that looks like the full window.
        complete=bool(found) and found[0][0] <= anchor_t - before + 0.05,
        # `complete` and `mode` are different claims and neither implies the other. `complete: false`
        # says this scene ran out of history; `sparse` says the corpus never had the resolution to
        # answer. On Hanoi the old response was `complete: false` with one frame, which reads as a
        # boundary case rather than as "this corpus cannot do strips".
        mode="strip" if len(found) >= MIN_STRIP_FRAMES else "sparse",
        median_gap_s=round(corpus_density(corpus).median_gap_s, 3),
        source=source_clip(corpus, get_manifest(), frame_id),
    )


@router.get("/status")
async def agent_status() -> dict:
    """Readiness, which is not liveness — the process serves /health before artifacts finish loading."""
    try:
        corpus = get_corpus()
    except (FileNotFoundError, ValueError) as exc:
        logger.error("artifacts unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Corpus artifacts are not loaded.") from exc
    settings = get_settings()
    return {
        "status": "ready",
        "artifacts_loaded": True,
        "corpus_frames": corpus.n_frames,
        "encoder": corpus.provenance.get("encoder", "unknown"),
        # The one thing here that can be wrong while everything else looks right: the band is a
        # property of the corpus and lives in config. See `band.py` for what each state means.
        "rejection_band": band_status(corpus, (settings.tau_reject, settings.tau_confident)),
        # Derived from the loaded frames rather than read from provenance, so unlike the band it
        # cannot disagree with the corpus underneath it. What it answers: does `/frames/{id}/context`
        # return a moment on this corpus, or the frame you already had?
        "temporal_density": corpus_density(corpus).as_dict(),
        "source_clips": len(get_manifest().clips),
        "provenance": corpus.provenance,
    }


# --- Moment clips: the private-storage half of the temporal answer ---
#
# Empty unless something mounted them: they arrive through `MOMENTS_DIR`, never in the image. That
# was "absent on every deployed box" until the merged corpus was mounted on 2026-08-31, and
# production now serves ten. `get_moments()` is empty when nothing has been built, so both routes
# answer honestly rather than erroring, and a manifest whose own output scan failed does not load at
# all — see `moments.py`.


@router.get("/moments", response_model=list[MomentClip])
async def list_moments() -> list[MomentClip]:
    """The redacted cuts this service holds. Empty where none were built, which is not an error."""
    store = get_moments()
    return [
        MomentClip(
            id=c["id"],
            video_id=c["video_id"],
            query=c["query"],
            keyframe_timestamp_s=c["keyframe_timestamp_s"],
            window_s=c["window_s"],
            fps=c["fps"],
            video_url=f"/api/v1/moments/{c['id']}/video",
            deep_link=c.get("deep_link"),
        )
        for c in store.clips.values()
    ]


@router.get("/moments/{moment_id}", response_model=MomentDetail)
async def moment_detail(moment_id: str) -> MomentDetail:
    """One clip, with the vehicles tracked through it and how close each came.

    Separate from the list because the boxes are bulky — six tracks over sixty frames — and only a
    player that is actually open needs them. `tracks` is empty on a manifest built before
    `scripts/moments/annotate_moment_tracks.py`, which a renderer must not read as "nothing came near".

    `closest_m` is a measurement and never a manoeuvre label: eight trajectory rules could not tell a
    cut-in from an overtake on this corpus, so the product reports the distance it can support and
    stays quiet about the one it cannot.
    """
    store = get_moments()
    clip = store.clips.get(moment_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="No such moment clip.")
    return MomentDetail(
        id=clip["id"],
        video_id=clip["video_id"],
        query=clip["query"],
        keyframe_timestamp_s=clip["keyframe_timestamp_s"],
        window_s=clip["window_s"],
        fps=clip["fps"],
        video_url=f"/api/v1/moments/{clip['id']}/video",
        deep_link=clip.get("deep_link"),
        camera_h_m=clip.get("camera_h_m"),
        tracks=[MomentTrack(**t) for t in clip.get("tracks") or []],
    )


@router.get("/moments/{moment_id}/video")
async def moment_video(moment_id: str) -> FileResponse:
    """Stream one redacted clip from local disk.

    `FileResponse` handles `Range` itself, so seeking in a `<video>` element works without this
    route parsing a byte range — which is the right place for that code to live, since a
    hand-rolled range parser is a way to read past the end of a file.

    The id is looked up in the manifest rather than joined onto a path, so only ids the build
    already produced can resolve; `path_of` re-checks the resolved path against the store's
    directory. Same posture as `/thumb`, for the same reason.
    """
    path = get_moments().path_of(moment_id)
    if path is None:
        raise HTTPException(status_code=404, detail="No such moment clip.")
    return FileResponse(path, media_type="video/mp4")


# --- Human review, and the export it exists to produce ---
#
# These are sync `def`, not `async def`, on purpose: sqlite3 blocks, and a blocking call inside an
# async handler stalls the whole event loop — including `/health`, which the deploy's uptime check
# calls. FastAPI runs a sync handler in its threadpool instead, which is why `ReviewStore` keeps a
# connection per thread.


def _reviewer_of(claimed: str | None, operator: User | None) -> str:
    """Resolve who a review call is filed under, or 400.

    Thin on purpose: the rule and the reasoning behind it are
    `services.reviews.reviewer_identity`, which knows nothing about HTTP, so the store's key
    semantics stay with the store and stay testable without a client. All four review routes go
    through here — an identity rule applied to three of them is one a caller steps around by
    picking the fourth.
    """
    try:
        return reviewer_identity(claimed, str(operator.user_id) if operator is not None else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/reviews", response_model=ReviewRecord, dependencies=[Depends(limit_writes)])
def put_review(
    request: ReviewRequest,
    operator: User | None = Depends(current_operator),
) -> ReviewRecord:
    """Record a reviewer's verdict on one frame. Re-deciding replaces the previous verdict.

    Filed under the signed-in account when there is one, and under the body's browser id only when
    there is not. A signed-in caller's `reviewer` is ignored rather than trusted, so the returned
    record — not the request — is what says where the verdict landed.
    """
    if request.frame_id not in get_corpus().scene_of:
        # Refuse ids the archive does not hold, rather than storing them. An export is meant to be a
        # dataset someone else can resolve; a row pointing at no frame is worse than a missing one.
        raise HTTPException(status_code=404, detail="No such frame in this corpus.")
    key = ReviewKey(request.query, request.frame_id, _reviewer_of(request.reviewer, operator))
    stored = get_store().put(key, request.decision, request.note)
    return ReviewRecord(**vars(stored))


@router.delete("/reviews", status_code=204, dependencies=[Depends(limit_writes)])
def clear_review(
    undo: Annotated[ReviewUndo, Query()],
    operator: User | None = Depends(current_operator),
) -> Response:
    """Undo one verdict. Idempotent — undoing nothing is a 204, not an error.

    A signed-in caller can only undo their own: the id comes from the cookie, never from the query
    string, which is what stops the published `(query, frame_id, reviewer)` triples in an export
    from being a delete list for other people's work.
    """
    get_store().clear(ReviewKey(undo.query, undo.frame_id, _reviewer_of(undo.reviewer, operator)))
    return Response(status_code=204)


@router.get("/reviews", response_model=list[ReviewRecord])
def list_reviews(
    query: str = Query(..., min_length=1),
    reviewer: str | None = Query(default=None),
    operator: User | None = Depends(current_operator),
) -> list[ReviewRecord]:
    """One reviewer's verdicts for one query, so a repeat search restores them rather than losing them.

    Scoped to the caller, and *which* caller is the session's answer when there is one. Returning
    every reviewer's verdicts is what let one tester see another's ticks and crosses before judging,
    which contaminates the only evidence the shipped corpus gets — and three accounts sharing one
    browser's `localStorage` reproduced that exactly, which is why the scope is no longer the
    browser's to name.
    """
    scope = _reviewer_of(reviewer, operator)
    return [ReviewRecord(**vars(r)) for r in get_store().for_query(query, scope)]


@router.get("/reviews/summary", response_model=ReviewSummary)
def review_summary(
    reviewer: str | None = Query(default=None),
    operator: User | None = Depends(current_operator),
) -> ReviewSummary:
    """How much has been judged. Drives the review bar, and answers §9 after a feedback session.

    **Sending `reviewer` asks for your own progress; omitting it asks for everyone's.** That
    distinction belongs to the export page (`fetchReviewSummaryAll`) and is unchanged here — what
    moved is only *whose* "own" means: a supplied id is replaced by the signed-in account, on the
    same rule as the other three routes, so the review bar counts the account rather than the
    laptop. Without it, the whole table, which is the operator's view and therefore needs a
    signed-in user: the same reason `/reviews/export` needs one.
    """
    if reviewer is None:
        require_operator(operator)
    scope = None if reviewer is None else _reviewer_of(reviewer, operator)
    store = get_store()
    return ReviewSummary(**store.summary(scope), reviewers=len(store.reviewers()))


@router.get("/reviews/export")
def export_reviews(
    format: Literal["csv", "json", "zip"] = "json",
    decision: Decision | Literal["all"] = "approved",
    scope: Literal["all", "mine"] = "all",
    user: User = Depends(get_current_user),
) -> Response:
    """Download the reviewed set. **Signed-in users only** — see `api/security.py`.

    Not merely because the verdicts are the deliverable. `decision=all` returns every
    `(query, frame_id, reviewer)` triple, which is exactly what `DELETE /reviews` needs, so an open
    export also hands out the means to empty the table.

    **Two scopes, because there are two products here and only one of them used to exist.**
    `scope=all` is the dataset the team built — every rater's verdicts, which is what makes
    disagreement between them visible and is what the Brief means by an engineer building a test set.
    `scope=mine` is one person's own work. Offering only the first is what made a newly registered
    account open this page on 61 rows from fourteen strangers with no way to find its own, and
    reasonably read that as a bug.

    `all` stays the default: it is what the page has meant since PR #173, and on a corpus whose
    verdicts predate account attribution `mine` is legitimately empty for everyone — a default that
    shows nothing would be a worse first impression than one that shows the team's set.

    **Whatever the scope, the count on the page and the bytes in the file must agree.** They
    disagreed once — the badge counted this browser's rows while the download carried everyone's —
    and that is the defect this parameter has to avoid re-creating, which is why the frontend drives
    both from one control.

    Defaults to `approved` because that is the dataset. `decision=all` returns every verdict, which
    is what you want in order to *inspect* a reviewer's rejections rather than to train on them —
    spelled as a value rather than an empty parameter, because an empty query string cannot express
    "no filter" without also being how a caller's bug looks. JSON is the complete export; CSV has
    nowhere to carry corpus provenance (`export.py`); ZIP packages both the image files and manifest.
    """
    mine = _reviewer_of(None, user) if scope == "mine" else None
    reviews = get_store().all(None if decision == "all" else decision, reviewer=mine)
    corpus = get_corpus()
    if format == "zip":
        body = export.to_zip(reviews, corpus, get_settings().thumbs_dir)
        media_type = "application/zip"
    elif format == "csv":
        body = export.to_csv(reviews, corpus)
        media_type = "text/csv; charset=utf-8"
    else:
        body = export.to_json(reviews, corpus)
        media_type = "application/json; charset=utf-8"

    return Response(
        content=body,
        media_type=media_type,
        # `attachment` so a browser saves it instead of rendering JSON in a tab — this endpoint is
        # reached from a download button, not from a fetch.
        headers={"Content-Disposition": f'attachment; filename="{export.filename(decision, format)}"'},  # noqa: E501
    )


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(limit_llm)])
async def chat(request: ChatRequest) -> ChatResponse:
    """Prose alias over the same agent, retained from the template contract.

    Prefer `/search`: this shape cannot express `matched`, `constraint` or `distinct_scenes`, which
    is most of what the product knows.
    """
    result = await search(SearchRequest(query=request.message[:500]))
    analysis = result.constraint.model_dump_json()
    if not result.matched:
        return ChatResponse(response=result.reason or "Nothing in the archive matches that.", analysis=analysis)
    clips = result.distinct_scenes
    return ChatResponse(
        response=f"Found {len(result.results)} frames across {clips} clip{'s' if clips != 1 else ''}.",
        analysis=analysis,
    )
