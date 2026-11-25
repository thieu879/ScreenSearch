/**
 * The last completed search, remembered for the lifetime of one browser tab.
 *
 * Why this exists: opening a frame navigates to `/scene/:id`, and "Quay lại kết quả tìm kiếm" pops
 * back to `/`. That remounts the search page, whose state starts empty — so a reviewer who opened a
 * single frame lost the ten results they were working through and had to retype the query. During a
 * feedback session that is the difference between judging a result set and fighting the tool.
 *
 * Why the whole response is stored rather than the query alone: re-running the search would spend a
 * second LLM parse on every back-click, and could return a different set. The reviewer has to come
 * back to *the frames they were judging*, not to a fresh answer to the same question.
 *
 * `sessionStorage`, not `localStorage`: this is the state of one reviewing session. A new tab should
 * open on the honest empty state, not on someone else's last query.
 *
 * The parse/serialise pair is pure and exported separately from the two storage wrappers, because
 * the test environment is `node` with no DOM (see `vitest.config.ts`) — the same split `reviewState`
 * uses. The wrappers are three lines of `try`; the shape guard is what can actually be wrong.
 */
import type { SearchResponse } from '../types/api';

const LAST_SEARCH_KEY = 'ssp_last_search_v1';

export interface LastSearch {
  query: string;
  response: SearchResponse;
}

export function serialiseLastSearch(query: string, response: SearchResponse): string {
  return JSON.stringify({ query, response });
}

/**
 * Turn a stored string back into a search, or null if it cannot be trusted.
 *
 * Guarded rather than cast: a stale entry from an older build, a half-written value, or anything
 * hand-edited in devtools must render as "no previous search" and not as a results grid. Showing
 * fabricated results is the exact failure the empty state was fixed to avoid.
 */
export function parseLastSearch(raw: string | null): LastSearch | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return null;
    const { query, response } = parsed as { query?: unknown; response?: unknown };
    if (typeof query !== 'string' || query.length === 0) return null;
    if (typeof response !== 'object' || response === null) return null;
    if (!Array.isArray((response as { results?: unknown }).results)) return null;
    return { query, response: response as SearchResponse };
  } catch {
    return null;
  }
}

export function saveLastSearch(query: string, response: SearchResponse): void {
  try {
    sessionStorage.setItem(LAST_SEARCH_KEY, serialiseLastSearch(query, response));
  } catch {
    // Quota, or a privacy mode that blocks storage. Losing the restore must never fail the search
    // that just succeeded.
  }
}

export function loadLastSearch(): LastSearch | null {
  try {
    return parseLastSearch(sessionStorage.getItem(LAST_SEARCH_KEY));
  } catch {
    return null;
  }
}
