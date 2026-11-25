/**
 * The state transitions behind `useReviews`, as pure functions over plain data.
 *
 * They live here rather than inside the hook for one reason: this is where the logic that can
 * actually be *wrong* is. Optimistic update, rollback on failure, and merging a server load under
 * verdicts clicked while it was in flight are three rules with real edge cases, and `vitest.config.ts`
 * deliberately has no jsdom or React renderer. Extracting them keeps the tricky part covered by the
 * tests that already run, and leaves the hook as wiring.
 *
 * Verdicts always travel with the query they belong to. A frame is a positive *for a question* —
 * `src/services/reviews.py` has the full argument — so a map with no query attached is a map that
 * can be shown against the wrong results.
 */
import type { Decision } from '../types/api';

export type DecisionMap = Record<string, Decision>;

/** Stable identity: a fresh `{}` per render would be a new prop every time and defeat memoisation. */
export const NO_DECISIONS: DecisionMap = Object.freeze({}) as DecisionMap;

export interface ReviewEntry {
  query: string;
  map: DecisionMap;
}

export const EMPTY_ENTRY: ReviewEntry = { query: '', map: NO_DECISIONS };

/** Verdicts to show for `query` — nothing at all if what we hold belongs to a different one. */
export function decisionsFor(entry: ReviewEntry, query: string | null): DecisionMap {
  return query && entry.query === query ? entry.map : NO_DECISIONS;
}

/**
 * Apply a verdict optimistically. Choosing the verdict a frame already has clears it, so the same
 * button is both "set" and "undo" — see `ReviewActions` for why that beats a fourth control.
 */
export function applyDecision(
  entry: ReviewEntry,
  query: string,
  frameId: string,
  decision: Decision,
): ReviewEntry {
  const map = { ...(entry.query === query ? entry.map : {}) };
  if (map[frameId] === decision) delete map[frameId];
  else map[frameId] = decision;
  return { query, map };
}

/**
 * Put back what was there before a request failed.
 *
 * `previous === undefined` means the frame was unjudged, so rollback deletes rather than restores —
 * the case a naive `map[frameId] = previous` turns into an `undefined` value that reads as judged.
 */
export function revertDecision(
  entry: ReviewEntry,
  query: string,
  frameId: string,
  previous: Decision | undefined,
): ReviewEntry {
  if (entry.query !== query) return entry;
  const map = { ...entry.map };
  if (previous) map[frameId] = previous;
  else delete map[frameId];
  return { query, map };
}

/**
 * Merge verdicts loaded from the server, letting local ones win.
 *
 * A reviewer who clicks before the load resolves has expressed something newer than the response in
 * flight. Overwriting it would silently revert their click, and they would have no way to notice.
 */
export function mergeLoaded(entry: ReviewEntry, query: string, stored: DecisionMap): ReviewEntry {
  return { query, map: entry.query === query ? { ...stored, ...entry.map } : stored };
}
