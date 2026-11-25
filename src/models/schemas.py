"""Request/response models for the SceneSearch API.

`QueryConstraint` deliberately mirrors the `gold` shape in
`experiments/m1/scenesearch/groundtruth/queries.yaml`. That is not incidental reuse — the whole
metadata-filter result (M2_DESIGN §9, relational mAP-lift +0.129 → +0.323) was measured against
constraints in exactly this shape, and `metadata/filter.py:satisfies` consumes it directly. A
different shape here would mean the product runs a filter that was never the one evaluated.
"""

from typing import Literal

from pydantic import BaseModel, Field

from src.config import get_settings

# Vocabulary is closed, and closed on purpose. **It is exactly `COCO_TO_VOCAB`'s six** — what the
# detector can actually emit — and that equality is the invariant, not a coincidence:
# `tests/test_models/test_category_vocabulary.py` fails if the two drift apart.
#
# It listed nine until 2026-08-18. The extra three — `construction_vehicle`, `traffic_cone`,
# `barrier` — are nuScenes annotation classes that COCO has no equivalent for, so the detector could
# never emit them, and a parser able to *name* what the corpus cannot *represent* is what issue #112
# is. `contradicted` read that gap as proof of absence and refused `traffic cones on the road` as
# certainly impossible on a corpus whose thumbnails plainly show traffic cones — 241 of 6,858
# captions name them, and retrieval already ranked a cone first. The same gap made a single spurious
# parse of one of those three an unrecoverable refusal (2026-08-17).
#
# Removing them does not lose a capability: nothing downstream could act on the three, and the
# embedding answers such queries correctly on its own (`traffic cones on the road` verifies at
# 0.753). Adding a category here is only safe once the detector can emit it.
Category = Literal[
    "pedestrian",
    "car",
    "truck",
    "bus",
    "bicycle",
    "motorcycle",
]
# CAM_FRONT only, so there is no "back". `annotations.py:_relation` returns exactly these three or
# None — anything outside ±90° is not in the frame at all.
Relation = Literal["front", "front_left", "front_right"]
Attribute = Literal["moving", "stopped", "parked", "standing", "with_rider", "without_rider"]


class QueryConstraint(BaseModel):
    """What the parser understood the user to be asking for.

    Returned to the client so the interpretation is visible and correctable. The parser is an LLM
    and will sometimes be wrong; showing a wrong constraint is recoverable, silently searching for
    the wrong thing is not.
    """

    objects: list[Category] = Field(default_factory=list)
    relations: dict[Category, list[Relation]] = Field(default_factory=dict)
    attributes: dict[Category, list[Attribute]] = Field(default_factory=dict)
    scene: dict[Literal["weather", "time"], str] = Field(default_factory=dict)
    out_of_scope: str | None = Field(
        default=None,
        max_length=200,
        description="Set when the query asks for something single frames cannot answer — motion "
        "over time ('a vehicle cutting into our lane'). Explained, never guessed at.",
    )
    # `max_length` above is the one place model output reaches the user as free text; every other
    # field is a closed enum. The structured-output schema already bounds what a crafted query can
    # achieve — it cannot invent a category or escape the shape — but it does not stop the model
    # being talked into emitting something long here, and that text is echoed into the response.
    # Capping it is not a vulnerability fix (the reflection is to the same user's own session, and
    # React escapes it); it removes the degenerate case where a prompt-injection attempt turns the
    # explanation field into a payload dump.

    unsupported_relation: str | None = Field(
        default=None,
        max_length=200,
        description="The object-relative phrase the parser had to drop, e.g. 'to the right of a "
        "bus'. Present means part of the query was NOT searched for — surface it, do not swallow it.",
    )
    # This vocabulary can only place an object in the frame, never against another object, and the
    # parser is instructed to drop such a phrase and emit both categories bare. That drop used to be
    # silent: "a motorbike to the right of a bus" quietly became "a frame containing a motorbike and
    # a bus, in any arrangement", and nothing in the response said so. `relax_node` reports the
    # widenings it performs mid-search; this one happens at parse time and reached no one.
    #
    # It is not a filterable condition and never becomes one — `metadata_constraint` ignores it —
    # which is exactly why it must be *said*. A product whose main claim is honest refusal cannot
    # answer a narrower question than the one asked without mentioning it.

    query_en: str | None = Field(
        default=None,
        max_length=500,
        description="The query in English, for the caption gate only (issue #70). Identical to the "
        "query when it was already English; a translation when it was not. Never used for "
        "retrieval — SigLIP2 reads Vietnamese directly, measured.",
    )
    # Not a constraint, in the same way `out_of_scope` is not one: this model is the parse result,
    # and both fields are things the parser understood rather than conditions the filter checks.
    # It lives here so it rides the existing `constraint` plumbing — one LLM call, one state field,
    # no new signature for `parse_constraint` and its two measurement-script callers.
    #
    # Why it exists: the caption gate embeds the query with `all-MiniLM-L6-v2`, which is English-only,
    # against Florence-2 captions, which are English. A Vietnamese query scored 0.057-0.123 where its
    # English twin scored 0.145-0.707, so every Vietnamese query fell under `tau_reject` and was
    # refused — not strictly, but blindly: the Vietnamese scores carried no relevance signal at all.


class SearchRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Natural-language scenario, e.g. 'a pedestrian to the front-left'",
    )
    top_k: int = Field(
        default_factory=lambda: get_settings().default_top_k,
        ge=1,
        le=50,
        description="Results to return. Also the diversity window — M2_DESIGN §7 "
        "measured that capping beyond the displayed head costs mAP and "
        "buys no additional diversity. Omit it to take the server's "
        "configured default (`DEFAULT_TOP_K`, 10 unless a box overrides it).",
    )


class SourceClip(BaseModel):
    """Where this frame came from, as a link into the footage at the moment it was taken.

    A result is one still, and a still cannot show motion. When the corpus knows which clip a frame
    came from, the honest answer to "was that motorbike cutting in?" is not a better still — it is
    the source video, seeked to that second, at its own frame rate. Costs no processing, no storage
    and no privacy exposure, because nothing is re-hosted.

    Null on the served nuScenes corpus and always will be: its source blobs were pruned after
    extraction, so there is nothing to link to. Render the card without it rather than inventing a
    link.
    """

    url: str = Field(
        description="The clip's public page with a start time, e.g. "
        "`https://www.youtube.com/watch?v=…&t=257`. Leaves this product — treat it as 'see the "
        "source', not as a result.",
    )
    title: str | None = Field(default=None, description="The clip's own title, as published.")
    uploader: str | None = Field(
        default=None,
        description="Who published it. Not optional in spirit: the Hanoi clips are CC BY, which "
        "requires crediting the author, so a renderer that drops this breaks the licence.",
    )
    license: str | None = Field(default=None, description="The licence the clip was published under.")


class MomentRef(BaseModel):
    """A redacted clip this service holds, cut around this very frame.

    The other half of `source`, and the two are offered together on purpose: this is footage the
    project owns and redacted, the deep link is the unmodified original and is the evidence. Present
    only where `scripts/moments/build_moment_clips.py` has cut a clip for this frame — which is a handful of
    frames, not the corpus, so **null is the normal answer** and the card renders without it.
    """

    id: str
    video_url: str = Field(description="Byte-range mp4 on this service, e.g. `/api/v1/moments/m05/video`.")
    closest_m: float | None = Field(
        default=None,
        description="How close the nearest tracked vehicle came to the ego car in this moment, in "
        "metres. A measurement — rounded to 0.5 and to be rendered with a `~`, because the scale is "
        "estimated off the road plane — and never a manoeuvre label. `null` where the clip was not "
        "annotated. The boxes behind it are on `GET /moments/{id}`: a search response carries the "
        "headline number, not a few hundred rectangles.",
    )
    events: list[list] = Field(
        default_factory=list,
        description="Hand-labelled manoeuvres inside the clip, `[start_s, end_s, label]`, in "
        "seconds FROM THE START OF THE CLIP. Empty where nobody labelled one. These are a human's "
        "reading of the footage, not a detection — do not render them as something the system found.",
    )


class FrameHit(BaseModel):
    frame_id: str
    scene_id: str
    timestamp_s: float
    score: float = Field(..., description="Similarity from the retrieval encoder, not a probability")
    match_probability: float | None = Field(
        default=None,
        description="`score` put through SigLIP2's own trained sigmoid calibration, 0–1. This is "
        "the number to render as a percentage — `score * 100` is not one, since the cosine scale "
        "tops out near 0.17. Null when the encoder is not loaded. It measures the EMBEDDING only: "
        "a relational query the metadata filter satisfies can sit low here, so `satisfied` is the "
        "evidence for those, not this.",
    )
    thumb_url: str
    corpus: str | None = Field(
        default=None,
        description="Which corpus this frame came from, on a corpus merged out of several — e.g. "
        "`hanoi`. **Null whenever it cannot be established**, including on every unmerged corpus "
        "and for the parts of a merge that recorded no name. Null means 'not known', never 'the "
        "default one': the frame card printed a hardcoded `nuScenes (Production)` on every result "
        "until 2026-08-30, which was false for all 2,211 Hanoi frames, and the fix was to show "
        "nothing rather than a better guess. `Corpus.source_names` decides.",
    )
    satisfied: list[str] = Field(
        default_factory=list,
        description="Constraint conditions this frame's DETECTED metadata satisfies, e.g. "
        "'rel:pedestrian:front_left' or 'scene:time=night'. From pixels, never from annotations.",
    )
    caption: str | None = Field(
        default=None,
        description="What the captioner saw in THIS frame (Florence-2, English). The same text the "
        "rejection check scores the query against, so showing it lets a user see the evidence the "
        "verdict was formed from. Null on a caption-deferred corpus where this frame has not been "
        "captioned yet — render the frame without it rather than inventing a description.",
    )
    source: SourceClip | None = Field(
        default=None,
        description="The footage this frame was extracted from, seeked to its timestamp. Present "
        "only on a corpus whose `videos.json` names its clips — null on nuScenes, which kept no "
        "source video. With `moment`, the two affordances that can show motion over time.",
    )
    moment: MomentRef | None = Field(
        default=None,
        description="A redacted clip this service holds, cut around this frame. Null unless one was "
        "built — which is a handful of frames, not the corpus. Where both this and `source` are "
        "present, offer both: the clip is ours and redacted, the link is the original and is the "
        "evidence.",
    )


class ContextFrame(BaseModel):
    """One frame of a keyframe strip, already published and already redacted."""

    frame_id: str
    timestamp_s: float
    offset_s: float = Field(
        ...,
        description="Seconds relative to the frame that was asked about: negative for earlier, "
        "0.0 for the anchor itself. Render from this rather than differencing `timestamp_s`, "
        "which is an offset into the clip and not comparable across scenes.",
    )
    thumb_url: str


class FrameContextResponse(BaseModel):
    """The moment a hit belongs to: the frames leading up to it, within one scene.

    A single keyframe cannot show motion — whether a pedestrian was stepping into the road or
    standing still looks identical. This is what lets a user judge that, and it is a PREVIEW and
    not a search: the agent still refuses motion-over-time queries, because the corpus cannot
    answer them. Do not present these frames as evidence that a temporal query was satisfied.
    """

    frame_id: str
    scene_id: str
    timestamp_s: float
    requested_before_s: float
    frames: list[ContextFrame] = Field(
        default_factory=list,
        description="Ascending by timestamp, ending with the anchor. Always at least the anchor.",
    )
    complete: bool = Field(
        ...,
        description="Whether the full requested window was available. False at the start of a "
        "scene, where less footage precedes the hit than was asked for — 2.5% of the corpus has "
        "no predecessor at all. Label it in the UI rather than silently showing a shorter strip.",
    )
    mode: Literal["strip", "sparse"] = Field(
        default="strip",
        description="Whether this request actually produced a strip. `sparse` means the window "
        "returned the anchor and nothing useful before it, because this corpus's frames are too "
        "far apart — render `source` instead, and do NOT present one still as a moment. Decided "
        "per request from what came back, not from a corpus-wide label, so it stays right on a "
        "corpus whose spacing is not uniform.",
    )
    median_gap_s: float | None = Field(
        default=None,
        description="The corpus's median within-scene interval, so a client can say WHY a request "
        "came back sparse — 0.50 s on nuScenes, 5.00 s on the staged Hanoi corpus. Derived from "
        "the loaded frames, never stamped, so it cannot disagree with the artifact.",
    )
    source: SourceClip | None = Field(
        default=None,
        description="The footage this frame came from, seeked to its timestamp — the temporal "
        "affordance that works when the strip does not. Null where the corpus kept no source "
        "video, which on nuScenes is always. When `mode` is `sparse` and this is null too, the "
        "honest answer is that this corpus cannot show the moment at all: say so.",
    )


class MomentTrack(BaseModel):
    """One vehicle tracked through a moment, and how close it came.

    **A measurement, not a manoeuvre.** Eight trajectory rules failed to tell a cut-in from an
    overtake on this corpus (best AUC 0.827, a ranking rather than a decision), so nothing here
    names the manoeuvre. What the geometry does support is the distance, and `closest_m` is that:
    the nearest this vehicle came to the ego car over the window.

    **Render it with a `~`.** It is an estimate off the road plane — the scale comes from typical
    vehicle widths and the forward half needs the declared `hfov_deg` — so it is rounded to 0.5 m at
    the source and a caption claiming more precision than that is claiming more than was measured.
    """

    label: str = Field(description="Detector class: motorcycle, car, bus, truck, bicycle.")
    closest_m: float = Field(description="Nearest this vehicle came to the camera over the clip, in metres.")
    distances: list[float] = Field(
        default_factory=list,
        description="Distance on each frame, one per entry in `at`. **Render this, not `closest_m`, "
        "on a moving box**: the minimum was on the tag first and read as a live figure, so an "
        "overtaking car showed its closest value while it was already far away and two vehicles at "
        "obviously different depths displayed the same number.",
    )
    closest_at: int = Field(description="Index into `at` where the closest approach happens.")
    lateral_m: float = Field(
        description="Sideways distance from the ego path, from the ground plane. Kept for reference "
        "and used by the Tier 3 ranking; not the displayed figure."
    )
    ground_plane_m: float | None = Field(
        default=None,
        description="The distance the road-plane estimator gives, kept so the two can be compared. "
        "It is NOT what to show: on this footage it compresses everything into one band — a car, a "
        "bus and two trucks at plainly different depths all read ~2.6 m — because the horizon "
        "regression can fail and every box bottom sits near the frame edge in dense traffic.",
    )
    frames: list[int] = Field(description="[first, last] frame index of the track within the clip.")
    at: list[int] = Field(description="Frame index of each box, at the clip's fps. Gaps mean a missed detection.")
    boxes: list[list[float]] = Field(
        description="One `[x0, y0, x1, y1]` per entry in `at`, as fractions of the frame so an "
        "overlay scales to whatever size the video is rendered at."
    )


class MomentClip(BaseModel):
    """One redacted six-second cut, held locally — the affordance a still cannot provide.

    This is the private-storage case: the pixels are ours, so the product can show the motion
    instead of pointing at someone else's video. Every clip here was redacted at source resolution
    and then **verified against the encoded output** — the mp4 decoded back to frames with the face
    and plate detectors re-run on it. A manifest that failed that check does not load at all, so a
    clip appearing in this list has passed it.
    """

    id: str
    video_id: str = Field(description="The source clip this was cut from, as `videos.json` names it.")
    query: str = Field(
        description="The motion query this moment was shortlisted for. Not a label: "
        "nothing has verified that the manoeuvre occurs, and the corpus has no "
        "annotations that could. Render it as what was searched for, not as a finding."
    )
    keyframe_timestamp_s: float = Field(description="The keyframe this window was built around.")
    window_s: list[float] = Field(description="[start, end] in the source clip, seconds.")
    fps: int
    video_url: str = Field(
        description="Byte-range mp4 on this service, e.g. "
        "`/api/v1/moments/m01/video`. Local disk, never a redirect off-site."
    )
    deep_link: str | None = Field(
        default=None,
        description="The public source at the same second. Both are offered on purpose: the local "
        "clip is redacted and ours, the deep link is the unmodified original and is the evidence.",
    )


class MomentDetail(MomentClip):
    """One clip with the tracked vehicles drawn out — what the player needs, and only on request.

    Separate from `MomentClip` because the boxes are bulky: six tracks over sixty frames is a few
    hundred rectangles per clip, which nobody listing ten clips wants and every player opening one
    does. The list stays cheap; this is fetched when a moment is actually watched.
    """

    tracks: list[MomentTrack] = Field(
        default_factory=list,
        description="Vehicles tracked through the clip, nearest first. Empty where the manifest "
        "predates `scripts/moments/annotate_moment_tracks.py`, which is not the same as nothing coming near.",
    )
    camera_h_m: float | None = Field(
        default=None,
        description="Camera height above the road, in metres, recovered per clip from typical "
        "vehicle widths. Published because every distance here scales with it: on one clip it came "
        "back 0.92 m where a dashcam sits nearer 1.3, so a reader can see how much to trust the metres.",
    )


class SearchResponse(BaseModel):
    matched: bool = Field(
        ...,
        description="False means the archive genuinely holds nothing "
        "matching. Results will be empty; show the empty state.",
    )
    confidence: Literal["high", "low"] | None = Field(
        default=None,
        description="Present when matched. 'low' means the archive was searched and these are its "
        "closest frames, but a check against their descriptions could not confirm the "
        "match — show them WITH the caveat in `reason`, do not hide them. Hiding a "
        "real result is the one error the user cannot detect or recover from.",
    )
    reason: str | None = Field(
        default=None,
        description="Plain English. Why nothing matched, or — when confidence is 'low' — what to "
        "be careful of. Present in both cases; not an error string.",
    )
    constraint: QueryConstraint
    results: list[FrameHit] = Field(default_factory=list)
    distinct_scenes: int = Field(
        default=0,
        description="Distinct source clips in the results. At 2 Hz "
        "keyframes, consecutive frames are near-identical, so "
        "this is how a caller sees whether an answer has real "
        "variety (M2_DESIGN §7).",
    )
    trace_id: str | None = Field(default=None, description="LangSmith run id, when tracing is on")


class HealthResponse(BaseModel):
    status: str
    version: str
    corpus_frames: int
    release: str = Field(
        default="unknown",
        description="Which build is running — a git tag or describe string, e.g. `v1.1`. `unknown` "
        "means the image was built without one, which is a deploy that skipped a step rather than a "
        "normal state. Use it to attribute a bug report to a build.",
    )


class ChatRequest(BaseModel):
    """Retained from the template contract; `/chat` is a thin alias over the search agent."""

    message: str = Field(..., min_length=1, max_length=5000)


class ChatResponse(BaseModel):
    response: str
    analysis: str = Field(default="")


# --- Human review (Brief §Chức năng chính: "Human Review", "Dataset Export") ---

Decision = Literal["approved", "rejected", "bookmarked"]


class ReviewRequest(BaseModel):
    """One reviewer verdict on one frame, for one query.

    `query` is required and is not decoration: a frame is a positive *for a question*, so the pair
    is the key (`services/reviews.py` has the argument). It carries the **composed** query — the
    text actually searched, filters folded in — because that is what the decision was made about.
    """

    query: str = Field(..., min_length=1, max_length=500)
    frame_id: str = Field(..., min_length=1, max_length=128)
    reviewer: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Pseudonymous browser id, for a caller with no session. **Ignored when you are "
        "signed in** — the account decides, so this cannot be used to file a verdict as somebody "
        "else. Required only when anonymous: one deployment serves every tester from one table, so "
        "an unattributed verdict cannot be separated from anyone else's afterwards "
        "(`services/reviews.py:reviewer_identity` has the argument)",
    )
    decision: Decision
    note: str = Field(
        default="",
        max_length=500,
        description="Optional reviewer note — why this frame was rejected, or what to check later",
    )


class ReviewUndo(BaseModel):
    """The query string of `DELETE /reviews` — the triple that names one verdict.

    A model rather than three loose parameters because the route also needs the caller's session to
    resolve `reviewer`, and four positional dependencies is where a handler stops being readable.
    Grouping the *data* keeps the injected dependency visibly separate from what the client sent.
    """

    query: str = Field(..., min_length=1)
    frame_id: str = Field(..., min_length=1)
    reviewer: str | None = Field(
        default=None,
        min_length=1,
        description="As `ReviewRequest.reviewer`: ignored when signed in, required when anonymous. "
        "Without one an undo would delete whichever verdict matched, including another tester's",
    )


class ReviewRecord(BaseModel):
    query: str
    frame_id: str
    reviewer: str
    decision: Decision
    note: str = ""
    reviewed_at: str = Field(..., description="UTC ISO-8601, second precision")


class ReviewSummary(BaseModel):
    """Counts for the review bar, and the numbers `report.md` §9 reports after a feedback session."""

    approved: int = 0
    rejected: int = 0
    bookmarked: int = 0
    queries_reviewed: int = 0
    total: int = 0
    reviewers: int = Field(
        default=0,
        description="Distinct reviewers in scope. The rubric asks for 3-5 people, and a total count "
        "cannot evidence that; this can",
    )


# --- Search history (per account, not per browser — `services/history.py` has the argument) ---


class HistoryWrite(BaseModel):
    """One search to remember. The body of `POST /history`.

    No `reviewer`-shaped field and no user id: whose history this is comes from the session, never
    from the request, for the same reason a verdict's attribution does.
    """

    keyword: str = Field(..., min_length=1, max_length=500, description="The text that was searched")
    results_count: int = Field(
        default=0,
        ge=0,
        description="How many hits it returned — what makes a repeat worth or not worth running",
    )
    filters: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Filter labels shown alongside the query",
    )


class HistoryEntry(BaseModel):
    """One remembered search, as the history page renders it."""

    entry_id: str
    keyword: str
    results_count: int
    filters: list[str] = Field(default_factory=list)
    created_at: str = Field(..., description="UTC ISO-8601")
