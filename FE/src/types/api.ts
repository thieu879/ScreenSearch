/**
 * Mirrors `src/models/schemas.py`. The contract is frozen — see `docs/api-contract.md`.
 *
 * The enums below are closed on the backend and deliberately closed here too. A category the
 * parser cannot emit is one the metadata filter silently never satisfies, so a typo should be a
 * compile error rather than a search that quietly returns nothing.
 */

/** nuScenes categories the COCO detector was mapped onto. `schemas.py:17-27`. */
export type Category =
  | 'pedestrian'
  | 'car'
  | 'truck'
  | 'bus'
  | 'bicycle'
  | 'motorcycle'
  | 'construction_vehicle'
  | 'traffic_cone'
  | 'barrier';

/** CAM_FRONT only, so there is no "back" — anything outside ±90° is not in frame. `schemas.py:30`. */
export type Relation = 'front' | 'front_left' | 'front_right';

export type Attribute = 'moving' | 'stopped' | 'parked' | 'standing' | 'with_rider' | 'without_rider';

export type Confidence = 'high' | 'low';

/**
 * What the parser understood the user to be asking for.
 *
 * Returned so the interpretation is visible and correctable: the parser is an LLM and will
 * sometimes be wrong. Showing a wrong constraint is recoverable; silently searching for the wrong
 * thing is not.
 */
export interface QueryConstraint {
  objects: Category[];
  relations: Partial<Record<Category, Relation[]>>;
  attributes: Partial<Record<Category, Attribute[]>>;
  scene: { weather?: string; time?: string };
  /**
   * Set when the query needs motion across frames.
   *
   * **This does NOT imply `matched` is false, and it used to.** Since Tier 1 the field carries two
   * opposite verdicts depending on the corpus: on one with no source footage the query is refused,
   * as before; on one with footage it is *answered* — deep links, sometimes a clip — and this
   * becomes a caveat saying a single frame cannot show movement. **Read `matched` to decide whether
   * there are results.** Branching on this field instead is what put an "Out of Search Scope"
   * banner over ten linked results. See `lib/searchNotice.ts` and `api-contract.md`.
   */
  out_of_scope: string | null;
  /**
   * The object-relative phrase the parser had to drop — "to the right of a bus". This vocabulary
   * places an object in the frame, never against another object, so such a clause is discarded and
   * the search runs on the bare categories.
   *
   * Present means **part of the query was not searched for**. It is already spelled out in
   * `reason`, so a UI that renders `reason` needs no extra work; do not silently ignore both.
   */
  unsupported_relation: string | null;
  /**
   * The query in English — verbatim when it already was, a translation when it was not (issue #70).
   * The rejection gate scores this rather than the raw query, because its caption encoder is
   * English-only and refused every Vietnamese query outright.
   *
   * Retrieval still runs on what the user typed: SigLIP2 reads Vietnamese directly, measured. So a
   * query and its translation legitimately return different frames — that is not a bug to report.
   *
   * Not a chip. It restates the user's own sentence, so rendering it beside the constraint would
   * add a row that tells them nothing they did not just type. Null when the parse failed.
   */
  query_en: string | null;
}

/**
 * Where a frame came from, as a link into the footage at the moment it was taken.
 *
 * A result is one still, and a still cannot show motion. When the corpus kept its source clips,
 * the honest answer to "was that motorbike cutting in?" is not a better still — it is the video,
 * seeked to that second, at its own frame rate.
 *
 * **Null on the served nuScenes corpus and always will be**: its source blobs were pruned after
 * extraction, so there is nothing to link to. Render the card without it; never synthesise a URL.
 *
 * `uploader` and `license` are not decoration. The Hanoi clips are CC BY, which requires crediting
 * the author, so a renderer that shows the link and drops the credit breaks the licence.
 */
export interface SourceClip {
  /** The clip's public page with a start time, e.g. `https://www.youtube.com/watch?v=…&t=257`. */
  url: string;
  title: string | null;
  uploader: string | null;
  license: string | null;
}

/**
 * A redacted clip this service holds, cut around this very frame.
 *
 * The other half of `source`, and both are offered together on purpose: this is footage the
 * project owns and redacted, the deep link is the unmodified original and is the evidence.
 *
 * **Null is the normal answer.** Clips are built for a handful of frames, not the corpus, and no
 * deployed box has any — render the card without it rather than leaving a gap where it would go.
 */
export interface MomentRef {
  id: string;
  /** Byte-range mp4 on this service, e.g. `/api/v1/moments/m05/video`. Prefix with the API base. */
  video_url: string;
  /**
   * How close the nearest tracked vehicle came to the camera, in metres — **a measurement, never a
   * manoeuvre label**. Estimated from the vehicle's apparent size against a typical height for its
   * class, so render it with a `~`. `null` where the clip was not annotated, which is not the same
   * as nothing having come near.
   */
  closest_m: number | null;
  /**
   * Hand-labelled manoeuvres inside the clip: `[start_s, end_s, label]`, seconds from the START OF
   * THE CLIP. **A human's reading of the footage, not a detection** — never present these as
   * something the system found.
   */
  events: [number, number, string][];
}

/**
 * One vehicle tracked through a moment clip.
 *
 * `boxes` are fractions of the frame, one per entry in `at`, so an overlay scales to whatever size
 * the player is rendered at. `at` can have gaps — a frame where the detector missed it — and a
 * renderer must simply draw nothing for those rather than interpolating a box that was never there.
 */
export interface MomentTrack {
  label: string;
  /** Nearest this vehicle came over the whole clip. A summary — do NOT put it on a moving box. */
  closest_m: number;
  /** Distance on each frame, aligned with `at`. This is what a box tag shows. */
  distances: number[];
  lateral_m: number;
  closest_at: number;
  frames: [number, number];
  at: number[];
  boxes: [number, number, number, number][];
}

/** One clip with its tracks — `GET /api/v1/moments/{id}`, fetched only when a player opens. */
export interface MomentDetail {
  id: string;
  video_id: string;
  query: string;
  window_s: [number, number];
  fps: number;
  video_url: string;
  deep_link: string | null;
  /** Camera height in metres, recovered per clip. Every distance scales with it — shown so a viewer can judge. */
  camera_h_m: number | null;
  tracks: MomentTrack[];
}

export interface FrameHit {
  frame_id: string;
  scene_id: string;
  timestamp_s: number;
  /** Similarity from the retrieval encoder — NOT a probability. Never render as a percentage. */
  score: number;
  /**
   * `score` through SigLIP2's own trained sigmoid calibration, 0–1. **This** is the field to render
   * as a percentage; `score * 100` is not one, because the cosine scale tops out near 0.17 — a
   * perfect match displayed that way reads as "16%". Null when the backend encoder is not loaded.
   *
   * It measures the embedding alone. A relational query that the metadata filter satisfies can sit
   * low here (`a car to the front-right` calibrates to ~5% while being the strongest measured
   * result in the project), so `satisfied` is the evidence for those, not this number.
   */
  match_probability: number | null;
  /** Relative path, e.g. `/api/v1/frames/{id}/thumb`. Prefix with the API base; do not rebuild it. */
  thumb_url: string;
  /**
   * Which corpus this frame came from, on a merged one — e.g. `hanoi`.
   *
   * **Null means "not established", never "the default".** The card printed a hardcoded
   * `nuScenes (Production)` until 2026-08-30, which was false for every Hanoi frame; render
   * nothing when this is absent rather than substituting a name.
   */
  corpus?: string | null;
  /**
   * Conditions this frame's DETECTED metadata satisfies: `object:car`,
   * `rel:pedestrian:front_left`, `scene:time=night`. All read from pixels, never from annotations.
   */
  satisfied: string[];
  /**
   * What the captioner saw in THIS frame (Florence-2, English) — the same text the rejection check
   * scores the query against, so it is the evidence the confidence verdict was formed from.
   *
   * Null on a caption-deferred corpus where this frame has not been captioned yet. Render the card
   * without it in that case; do not substitute a generic sentence, which is what every card showed
   * before this field existed.
   */
  caption: string | null;
  /**
   * The footage this frame was extracted from, seeked to its timestamp — the only affordance in
   * the product that can show motion over time. Null on nuScenes, which kept no source video.
   */
  source: SourceClip | null;
  /**
   * A redacted clip cut around this frame, where one was built. Null unless so — which is almost
   * always. Where both this and `source` are present, offer both: the clip is ours and redacted,
   * the link is the original and is what makes the claim checkable.
   */
  moment: MomentRef | null;
}

export interface SearchResponse {
  /** False means the archive genuinely holds nothing matching — a first-class answer, not an error. */
  matched: boolean;
  /** Present when matched. 'low' means show the results WITH the caveat, never hide them. */
  confidence: Confidence | null;
  /** Plain English. Why nothing matched, or what to be careful of. Not an error string. */
  reason: string | null;
  constraint: QueryConstraint;
  results: FrameHit[];
  /** Distinct source clips in the results — how a caller sees whether an answer has real variety. */
  distinct_scenes: number;
  /** Declared in the schema but not currently populated by the API. Do not depend on it. */
  trace_id: string | null;
}

export interface SearchRequestBody {
  query: string;
  /** 1–50. Also the diversity window: set it to what you actually display. Optional — omitted, the
   *  server applies its configured `DEFAULT_TOP_K`, which is the one place the number is set. */
  top_k?: number;
}

/* ── Human review (Brief §Chức năng chính: "Human Review", "Dataset Export") ────────────────────
 *
 * A verdict is keyed on the **pair** `(query, frame_id)`, not on the frame. A frame is a positive
 * *for a question someone asked* — the same frame can be right for `driving at night` and wrong for
 * `a cyclist at night`. `src/services/reviews.py` carries the full argument.
 */

export type Decision = 'approved' | 'rejected' | 'bookmarked';

export interface ReviewRecord {
  /** The **composed** query — filters folded in — because that is what the verdict was about. */
  query: string;
  frame_id: string;
  /** Pseudonymous browser id of whoever judged this. Not a login — `lib/reviewer.ts`. */
  reviewer: string;
  decision: Decision;
  note: string;
  /** UTC ISO-8601, second precision. */
  reviewed_at: string;
}

export interface ReviewSummary {
  approved: number;
  rejected: number;
  bookmarked: number;
  queries_reviewed: number;
  total: number;
  /** Distinct reviewers across the whole table — the evidence for "3-5 people", which no count of
   * verdicts can give. Always global, even when the counts beside it are scoped to one reviewer. */
  reviewers: number;
}

export interface ReviewRequestBody {
  query: string;
  frame_id: string;
  decision: Decision;
  note?: string;
}

export interface ReviewExportItem {
  query: string;
  frame_id: string;
  reviewer: string;
  decision: Decision;
  note: string;
  reviewed_at: string;
  scene_id?: string;
  timestamp_s?: number;
  caption?: string;
  satisfied?: string[];
}

export interface ReviewExportResponse {
  exported_at: string;
  count: number;
  reviewers: string[];
  decisions: ReviewExportItem[];
}

/**
 * What `/api/v1/status` reports about the loaded corpus.
 *
 * Only the fields the UI reads are declared. `provenance` carries a good deal more (encoder
 * prompts, ablation filenames, the anonymisation record); typing the whole of it here would make
 * this file a second copy of the server's provenance schema, to be kept in sync by hand.
 */
export interface CorpusStatus {
  status: string;
  corpus_frames: number;
  encoder: string;
  provenance?: {
    n_scenes?: number;
    version?: string;
  };
}

/**
 * One remembered search. Server-side and per account since 2026-08-30 — see
 * `src/services/history.py` for why it left `localStorage`.
 */
export interface HistoryEntry {
  entry_id: string;
  keyword: string;
  results_count: number;
  filters: string[];
  /** UTC ISO-8601. Formatted for display at the point of render, not stored formatted. */
  created_at: string;
}
