/**
 * Review state for the results currently on screen.
 *
 * Wiring only: every state transition lives in `lib/reviewState.ts`, where it is a pure function and
 * covered by tests that need no DOM. What is left here is the network — load on query change, write
 * optimistically, roll back on failure, refresh the counts.
 *
 * The optimistic write is not a nicety. A verdict is one click in a run of many, and waiting for a
 * round trip before the button responds makes rapid review feel broken. Rolling back on failure is
 * what keeps that honest: the alternative — trusting the optimistic value — would let a reviewer
 * believe work was saved that was not, and only find out at export.
 */
import { useCallback, useEffect, useState } from 'react';

import { clearReview, fetchReviewSummary, listReviews, putReview } from '../api/client';
import {
  applyDecision,
  decisionsFor,
  EMPTY_ENTRY,
  mergeLoaded,
  NO_DECISIONS,
  revertDecision,
  type DecisionMap,
  type ReviewEntry,
} from '../lib/reviewState';
import type { Decision, ReviewSummary } from '../types/api';

const EMPTY_SUMMARY: ReviewSummary = {
  approved: 0,
  rejected: 0,
  bookmarked: 0,
  queries_reviewed: 0,
  total: 0,
  reviewers: 0,
};

export interface UseReviews {
  /** frame_id → verdict, for the query passed in. Absent means not yet judged. */
  decisions: DecisionMap;
  summary: ReviewSummary;
  /** Choosing the verdict a frame already has clears it — the same button is set and undo. */
  decide: (frameId: string, decision: Decision) => Promise<void>;
  error: string | null;
}

export function useReviews(
  query: string | null,
  onError?: (message: string) => void,
  initialMap?: DecisionMap,
): UseReviews {
  const [entry, setEntry] = useState<ReviewEntry>(() =>
    query && initialMap ? { query, map: initialMap } : EMPTY_ENTRY,
  );
  const [summary, setSummary] = useState<ReviewSummary>(EMPTY_SUMMARY);
  const [error, setError] = useState<string | null>(null);

  // Derived, so a stale map from the previous query can never be rendered and no effect has to
  // reset state on every query change.
  const decisions = decisionsFor(entry, query);

  const refreshSummary = useCallback(() => {
    fetchReviewSummary()
      .then(setSummary)
      .catch(() => {
        /* The counts are informational; failing to refresh them must not interrupt reviewing. */
      });
  }, []);

  useEffect(() => {
    if (!query) return;
    let cancelled = false;
    listReviews(query)
      .then((records) => {
        if (cancelled) return;
        const stored = Object.fromEntries(records.map((r) => [r.frame_id, r.decision]));
        setEntry((prev) => mergeLoaded(prev, query, stored));
      })
      .catch(() => {
        // Showing nothing as judged is the safe failure: a reviewer re-judges rather than trusting
        // a verdict we could not confirm was stored.
        if (!cancelled) setEntry((prev) => (prev.query === query ? prev : { query, map: NO_DECISIONS }));
      });
    return () => {
      cancelled = true;
    };
  }, [query]);

  useEffect(refreshSummary, [refreshSummary]);

  const decide = useCallback(
    async (frameId: string, decision: Decision) => {
      if (!query) return;
      const previous = decisions[frameId];
      const clearing = previous === decision;

      setEntry((prev) => applyDecision(prev, query, frameId, decision));
      setError(null);

      try {
        if (clearing) await clearReview(query, frameId);
        else await putReview({ query, frame_id: frameId, decision });
        refreshSummary();
      } catch (cause) {
        setEntry((prev) => revertDecision(prev, query, frameId, previous));
        const message = cause instanceof Error ? cause.message : 'Không lưu được đánh giá.';
        setError(message);
        onError?.(message);
      }
    },
    [query, decisions, refreshSummary, onError],
  );

  return { decisions, summary, decide, error };
}
