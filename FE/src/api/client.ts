/**
 * The only place this app talks to the backend. Contract: `docs/api-contract.md` (frozen).
 *
 * In development `vite.config.ts` proxies `/api` to localhost:8000, so `API_BASE` is empty and
 * relative paths — including the `thumb_url` the server returns — work untouched. In production it
 * is set only if the frontend is served from a different origin than the API; when both are served
 * by the same Hugging Face Space, it stays empty and there is no CORS surface at all.
 */
import type {
  CorpusStatus,
  Decision,
  MomentDetail,
  ReviewExportResponse,
  ReviewRecord,
  ReviewRequestBody,
  HistoryEntry,
  ReviewSummary,
  SearchRequestBody,
  SearchResponse,
} from '../types/api';
import { getReviewerId } from '../lib/reviewer';

export const API_BASE: string = import.meta.env.VITE_API_BASE ?? '';

/** `top_k` is sent, and it is the number the user picked in the results dropdown.
 *
 *  This used to be omitted on the reasoning that the count is a measured retrieval parameter rather
 *  than a display preference. That reasoning is still true — `top_k` doubles as the diversity window
 *  (`services/search/diversity.py`), and at cap 2 relational lift measures +0.113 at window 10
 *  against +0.077 at window 50 while distinct-scenes@10 stays 5.50 either way, so a longer page is
 *  worse-ranked and no more varied. What was wrong was pairing it with a 10/20/50 dropdown that only
 *  re-paginated an array the server capped at 10: the control was inert, and its default of 20
 *  described a page that could never hold 20.
 *
 *  So the honest arrangement is the one here — the default is 10, which is `DEFAULT_TOP_K` and what
 *  every published `eval/results/` figure was measured at, and asking for more is a deliberate act
 *  by someone who wants a longer list and is choosing to pay for it in ranking quality. */

/** Longest query the API accepts (`schemas.py:65`). Enforced here so we fail before the round trip. */
export const MAX_QUERY_LENGTH = 500;

export class SearchError extends Error {
  // Declared and assigned separately rather than as a constructor parameter property: the app's
  // tsconfig sets `erasableSyntaxOnly`, which rules that syntax out.
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'SearchError';
    this.status = status;
  }
}

/**
 * Messages shown to the user. The API's `detail` is deliberately generic on 500 and must never be
 * rendered verbatim — `api-contract.md` asks for a friendly fallback rather than echoing it.
 */
function messageFor(status: number): string {
  if (status === 422) return 'Truy vấn không hợp lệ. Hãy thử mô tả ngắn gọn hơn.';
  if (status === 503) return 'Kho dữ liệu đang được nạp. Vui lòng thử lại sau ít giây.';
  if (status === 404) return 'Không tìm thấy tài nguyên.';
  return 'Tìm kiếm thất bại. Vui lòng thử lại.';
}

/**
 * Search the archive.
 *
 * `signal` is not optional in practice: each call is one gpt-4o-mini parse, and without it a slow
 * first request can resolve after a faster second one and overwrite newer results with older.
 */
export async function searchScenes(
  query: string,
  topK?: number,
  signal?: AbortSignal
): Promise<SearchResponse> {
  const body: SearchRequestBody = { query: query.slice(0, MAX_QUERY_LENGTH) };
  // Omitted rather than sent as a guess when the caller has no opinion: the server then applies
  // DEFAULT_TOP_K, which stays the single owner of the number. The API rejects anything outside
  // 1-50 (`schemas.py`), so clamp here and fail before the round trip.
  if (topK !== undefined) body.top_k = Math.min(50, Math.max(1, Math.trunc(topK)));

  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/v1/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    });
  } catch (cause) {
    // An aborted fetch rejects here too. Re-throw it unchanged so the caller can ignore it rather
    // than showing "server unreachable" for a search the user themselves superseded.
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    throw new SearchError('Không kết nối được tới máy chủ tìm kiếm.', 0);
  }

  if (!response.ok) throw new SearchError(messageFor(response.status), response.status);
  return (await response.json()) as SearchResponse;
}

/** Absolute URL for a relative API path the server handed back. Never rebuild such a path yourself. */
export function apiSrc(path: string): string {
  return `${API_BASE}${path}`;
}

/** Absolute URL for a hit's thumbnail. Use the server's `thumb_url`; never rebuild the path. */
export function thumbSrc(thumbUrl: string): string {
  return apiSrc(thumbUrl);
}

/**
 * Public dataset repository on Hugging Face holding the certified loose 640px thumbnails.
 * Used as a high-availability fallback when a local environment or deployed container lacks thumbs.
 */
export const HF_DATASET_ASSETS_BASE =
  'https://huggingface.co/datasets/P-057-RisingStar/scenesearch-assets/resolve/main';

export function hfThumbSrc(frameId: string): string {
  return `${HF_DATASET_ASSETS_BASE}/${frameId}.jpg`;
}

/* ── Human review ───────────────────────────────────────────────────────────────────────────────
 *
 * These deliberately do NOT reuse `messageFor`: a failed verdict is not a failed search, and
 * telling someone "Tìm kiếm thất bại" after they clicked approve would send them looking in the
 * wrong place. They throw `SearchError` for the type, with their own text.
 */

/**
 * Reading the export is not writing a verdict, so it does not borrow `reviewError`'s text — for the
 * same reason `reviewError` does not borrow `messageFor`'s. "Không lưu được đánh giá" after a failed
 * *load* sends someone to check whether their review was saved, which is not what went wrong.
 */
function exportError(status: number): SearchError {
  if (status === 401 || status === 403) return new SearchError('Cần đăng nhập để xem danh sách này.', status);
  return new SearchError('Không tải được danh sách kết quả đã duyệt.', status);
}

function reviewError(status: number): SearchError {
  if (status === 404) return new SearchError('Khung hình này không có trong kho hiện tại.', status);
  if (status === 422) return new SearchError('Đánh giá không hợp lệ.', status);
  return new SearchError('Không lưu được đánh giá. Vui lòng thử lại.', status);
}

/**
 * Every review call carries the reviewer id, and it is attached **here** rather than by callers.
 *
 * One deployment serves every tester from one table, so a call that omits the id writes a verdict
 * nobody can attribute afterwards. Injecting it centrally means a new call site cannot forget it —
 * the alternative, threading it through `useReviews` and every component, is one refactor away from
 * a silently unattributed row. `lib/reviewer.ts` has the argument.
 */

/** Record or replace a verdict. Re-deciding the same frame overwrites — the server upserts. */
export async function putReview(body: ReviewRequestBody): Promise<ReviewRecord> {
  const response = await fetch(`${API_BASE}/api/v1/reviews`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...body, reviewer: getReviewerId() }),
  }).catch(() => {
    throw new SearchError('Không kết nối được tới máy chủ.', 0);
  });
  if (!response.ok) throw reviewError(response.status);
  return (await response.json()) as ReviewRecord;
}

/** Undo a verdict. Idempotent server-side, so undoing nothing is not an error. */
export async function clearReview(query: string, frameId: string): Promise<void> {
  const params = new URLSearchParams({ query, frame_id: frameId, reviewer: getReviewerId() });
  const response = await fetch(`${API_BASE}/api/v1/reviews?${params}`, { method: 'DELETE' }).catch(() => {
    throw new SearchError('Không kết nối được tới máy chủ.', 0);
  });
  if (!response.ok) throw reviewError(response.status);
}

/** Undo/delete a specific verdict from the export page (supports explicit reviewer id). */
export async function deleteReviewVerdict(query: string, frameId: string, reviewer?: string): Promise<void> {
  const params = new URLSearchParams({
    query,
    frame_id: frameId,
    reviewer: reviewer || getReviewerId(),
  });
  const response = await fetch(`${API_BASE}/api/v1/reviews?${params}`, {
    method: 'DELETE',
    credentials: 'include',
  }).catch(() => {
    throw new SearchError('Không kết nối được tới máy chủ.', 0);
  });
  if (!response.ok) throw reviewError(response.status);
}

/**
 * This reviewer's verdicts for one query.
 *
 * This is what stops the review loop losing work: search the same thing twice and the previous
 * decisions come back with it, rather than the reviewer silently re-judging frames they already
 * judged and having no way to tell.
 *
 * Scoped to this browser's id. Unscoped, a tester saw the previous tester's ticks and crosses
 * already on the cards, which is contamination rather than restored work.
 */
export async function listReviews(query: string): Promise<ReviewRecord[]> {
  const params = new URLSearchParams({ query, reviewer: getReviewerId() });
  const response = await fetch(`${API_BASE}/api/v1/reviews?${params}`);
  if (!response.ok) throw reviewError(response.status);
  return (await response.json()) as ReviewRecord[];
}

/** This reviewer's own progress. A count including everyone else's work anchors the next verdict. */
export async function fetchReviewSummary(): Promise<ReviewSummary> {
  const params = new URLSearchParams({ reviewer: getReviewerId() });
  const response = await fetch(`${API_BASE}/api/v1/reviews/summary?${params}`);
  if (!response.ok) throw reviewError(response.status);
  return (await response.json()) as ReviewSummary;
}

/**
 * Everyone's verdicts — the whole reviewed set, which is what the export actually contains.
 *
 * **This exists because the export page was counting one thing and downloading another.** It read
 * `fetchReviewSummary` above, which is scoped to this browser's pseudonymous id, while
 * `fetchReviewExport` and `exportUrl` send no reviewer at all and return every reviewer's rows. So
 * the badge and the button showed *your* count over *everybody's* items, and a tester saw verdicts
 * from an earlier session they could not find in the review bar — the bar is scoped, the preview
 * was not.
 *
 * Which side was wrong is settled by `export_reviews` in `src/api/routes.py`: *"Defaults to
 * `approved` because that is the dataset."* The export is the deliverable, not a personal history,
 * so the count moves to match it rather than the export being narrowed.
 *
 * That also fixes a harder failure than the mislabelling: the button is disabled on `rowCount === 0`,
 * so a signed-in user with no verdicts of their own could not download a dataset that exists.
 *
 * Signed-in only, like the export itself — omitting `reviewer` is what makes it the global view, and
 * `api/security.py` gates exactly that. The page sits behind `ProtectedRoute`, so a 401 here means
 * the session expired and the existing error state is the honest thing to show.
 */
export async function fetchReviewSummaryAll(): Promise<ReviewSummary> {
  const response = await fetch(`${API_BASE}/api/v1/reviews/summary`, { credentials: 'include' });
  if (!response.ok) throw reviewError(response.status);
  return (await response.json()) as ReviewSummary;
}

/**
 * URL for the export download.
 *
 * Returned as a URL rather than fetched: the response carries `Content-Disposition: attachment`, so
 * letting the browser navigate to it saves the file with the server's filename. Fetching it into
 * memory and re-triggering a download would throw that name away and buffer the whole set for no
 * reason.
 *
 * Nothing authenticating is appended. This used to carry `?token=…`, because a link cannot set a
 * header and the gate was a shared secret; since 2026-08-27 the gate is simply *being signed in*,
 * and the session rides the `access_token` cookie, which a top-level navigation sends on its own
 * (`Path=/; SameSite=lax`). So the URL is now the same for everyone, and a refused export is a
 * question about who is signed in rather than about what is in the address bar.
 */
/**
 * Whose verdicts an export covers.
 *
 * `all` is the dataset the team built, and stays the default; `mine` is one person's own work. Both
 * are real answers to "export the reviewed set", and offering only the first is what made a newly
 * registered account open this page on 61 rows from fourteen strangers with no way to find its own.
 *
 * **Whichever is chosen must drive the count and the download together.** They disagreed once —
 * `fetchReviewSummaryAll` below carries the record of that — and one control feeding both is what
 * stops it recurring.
 */
export type ExportScope = 'all' | 'mine';

export function exportUrl(
  format: 'csv' | 'json' | 'zip',
  decision: Decision | 'all' = 'approved',
  scope: ExportScope = 'all',
): string {
  const params = new URLSearchParams({ format, decision, scope });
  return `${API_BASE}/api/v1/reviews/export?${params}`;
}

/**
 * The same export, read into memory instead of downloaded — what the preview above the button
 * renders, so the page can show *what* is about to leave rather than only how many rows.
 *
 * `credentials: 'include'` is not optional here, and it is the one thing that differs from
 * `exportUrl`. The gate is the `access_token` cookie; a top-level navigation carries it on its own,
 * but `fetch` only does so by default when the request is same-origin. That is true of the vite
 * proxy and of the deployed box, and false the moment `VITE_API_BASE` names another origin — the
 * deployment this file's header describes. Without it the preview 401s in exactly the setup nobody
 * runs locally. Every call in `api/auth.ts` says the same thing for the same reason.
 */
export async function fetchReviewExport(
  decision: Decision | 'all' = 'approved',
  scope: ExportScope = 'all',
): Promise<ReviewExportResponse> {
  const params = new URLSearchParams({ format: 'json', decision, scope });
  const response = await fetch(`${API_BASE}/api/v1/reviews/export?${params}`, { credentials: 'include' });
  if (!response.ok) throw exportError(response.status);
  return (await response.json()) as ReviewExportResponse;
}

/**
 * What the archive currently holds.
 *
 * Read rather than hardcoded, so a page cannot go on advertising a corpus size after a re-ingest.
 * The login hero used to claim `> 1.2M` keyframes against an archive of 6,858.
 */
export async function fetchCorpusStatus(): Promise<CorpusStatus> {
  const response = await fetch(`${API_BASE}/api/v1/status`);
  if (!response.ok) throw new Error(`status ${response.status}`);
  return (await response.json()) as CorpusStatus;
}

/**
 * One moment clip with the vehicles tracked through it.
 *
 * Fetched when a player opens rather than ridden along with the search response: six tracks over
 * sixty frames is a few hundred rectangles, and a page of ten results does not need them. The
 * headline number (`moment.closest_m`) is already on the hit, so a card can say how close the
 * nearest vehicle came without this request at all.
 */
export async function fetchMoment(momentId: string): Promise<MomentDetail> {
  const response = await fetch(`${API_BASE}/api/v1/moments/${encodeURIComponent(momentId)}`);
  if (!response.ok) throw new Error(`moment ${response.status}`);
  return (await response.json()) as MomentDetail;
}

export interface Health {
  status: string;
  version: string;
  corpus_frames: number;
  /** The build that is running, e.g. `v1.1`. `unknown` means the image was built without one. */
  release: string;
}

/**
 * Which build is answering. Shown in the sidebar so a screenshot or a bug report dates itself.
 *
 * Feedback arrives continuously via Discord against a link that keeps being redeployed, and the
 * review table has no column naming the build a verdict came from — so "it said nothing matches"
 * is otherwise unattributable between a retired threshold, a fixed bug, and a real gap.
 */
export async function fetchHealth(): Promise<Health> {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) throw new Error(`health ${response.status}`);
  return (await response.json()) as Health;
}

/* ── Authentication ──────────────────────────────────────────────────────────────────────────────
 *
 * Real authentication is in `auth.ts`. The mock auth that used to live here (loginUser,
 * registerUser, googleLogin, forgotPassword, resetPassword — all localStorage-based) has been
 * removed. Tokens now travel in HttpOnly cookies set by the backend.
 */


/* ── Search history ──────────────────────────────────────────────────────────────────────────────
 *
 * Per account and server-side. It used to be five rows in `localStorage`, which is a browser
 * profile rather than a person: invisible on a second machine, and shared by every account that
 * signed in on one laptop. `src/services/history.py` carries the full argument.
 *
 * Every call here needs the session cookie, hence `credentials: 'include'` — and none of them takes
 * a user id, because whose history this is is never the client's to say.
 */

/** This account's recent searches, newest first. */
export async function fetchSearchHistory(): Promise<HistoryEntry[]> {
  const response = await fetch(`${API_BASE}/api/v1/history`, { credentials: 'include' });
  if (!response.ok) throw new Error(`history ${response.status}`);
  return (await response.json()) as HistoryEntry[];
}

/**
 * Remember one search. **Deliberately fire-and-forget** — callers do not await it and it never
 * throws.
 *
 * A history row is a convenience and the search it describes has already succeeded, so a failed
 * write must cost the row and nothing else. Surfacing this as a toast would interrupt a reviewer
 * mid-flow to report that a list they were not looking at is one entry short.
 */
export function rememberSearch(keyword: string, resultsCount: number): void {
  void fetch(`${API_BASE}/api/v1/history`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keyword, results_count: resultsCount }),
  }).catch(() => {
    /* See above: the search already succeeded. */
  });
}

/** Forget one search. */
export async function deleteSearchHistoryEntry(entryId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v1/history/${encodeURIComponent(entryId)}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  // 404 means it is already gone, which is the outcome the caller wanted.
  if (!response.ok && response.status !== 404) throw new Error(`history ${response.status}`);
}

/** Empty this account's history. */
export async function clearSearchHistoryAll(): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v1/history`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!response.ok) throw new Error(`history ${response.status}`);
}
