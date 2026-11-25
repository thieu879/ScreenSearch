import { describe, expect, it } from 'vitest';

import {
  applyDecision,
  decisionsFor,
  EMPTY_ENTRY,
  mergeLoaded,
  NO_DECISIONS,
  revertDecision,
  type ReviewEntry,
} from './reviewState';

const AT_NIGHT = 'a bus at night';
const judged: ReviewEntry = { query: AT_NIGHT, map: { f1: 'approved', f2: 'rejected' } };

describe('decisionsFor', () => {
  it('returns the verdicts when they belong to the query being shown', () => {
    expect(decisionsFor(judged, AT_NIGHT)).toEqual({ f1: 'approved', f2: 'rejected' });
  });

  /**
   * The failure this prevents is showing a frame's verdict from a *different* question beside these
   * results — exactly what keying on the pair exists to stop.
   */
  it('shows nothing when what we hold belongs to another query', () => {
    expect(decisionsFor(judged, 'a cyclist at night')).toBe(NO_DECISIONS);
    expect(decisionsFor(judged, null)).toBe(NO_DECISIONS);
  });
});

describe('applyDecision', () => {
  it('records a verdict on an unjudged frame', () => {
    expect(applyDecision(EMPTY_ENTRY, AT_NIGHT, 'f1', 'approved').map).toEqual({ f1: 'approved' });
  });

  it('replaces a verdict when a different one is chosen', () => {
    expect(applyDecision(judged, AT_NIGHT, 'f1', 'rejected').map.f1).toBe('rejected');
  });

  it('clears the verdict when the one already set is chosen again', () => {
    const next = applyDecision(judged, AT_NIGHT, 'f1', 'approved');
    expect('f1' in next.map).toBe(false);
    expect(next.map.f2).toBe('rejected');
  });

  it('starts fresh rather than inheriting another query’s verdicts', () => {
    const next = applyDecision(judged, 'a cyclist at night', 'f9', 'approved');
    expect(next).toEqual({ query: 'a cyclist at night', map: { f9: 'approved' } });
  });

  it('does not mutate the entry it was given', () => {
    applyDecision(judged, AT_NIGHT, 'f1', 'rejected');
    expect(judged.map.f1).toBe('approved');
  });
});

describe('revertDecision', () => {
  it('restores the previous verdict after a failed write', () => {
    const optimistic = applyDecision(judged, AT_NIGHT, 'f1', 'rejected');
    expect(revertDecision(optimistic, AT_NIGHT, 'f1', 'approved').map.f1).toBe('approved');
  });

  /**
   * The case a naive `map[frameId] = previous` gets wrong: it writes `undefined`, and `'f1' in map`
   * then reports the frame as judged, so the card shows a verdict the server rejected.
   */
  it('deletes rather than restoring when the frame was previously unjudged', () => {
    const optimistic = applyDecision(EMPTY_ENTRY, AT_NIGHT, 'f1', 'approved');
    const reverted = revertDecision(optimistic, AT_NIGHT, 'f1', undefined);
    expect('f1' in reverted.map).toBe(false);
  });

  it('leaves a newer query’s state alone if the search moved on before the failure', () => {
    const moved: ReviewEntry = { query: 'something else', map: { f5: 'approved' } };
    expect(revertDecision(moved, AT_NIGHT, 'f1', 'approved')).toBe(moved);
  });
});

describe('mergeLoaded', () => {
  it('adopts the stored verdicts for a query it holds nothing for', () => {
    expect(mergeLoaded(EMPTY_ENTRY, AT_NIGHT, { f1: 'approved' }).map).toEqual({ f1: 'approved' });
  });

  /**
   * A reviewer who clicks before the load resolves has said something newer than the response in
   * flight. Letting the response win would silently revert their click.
   */
  it('lets a verdict clicked during the load win over the stored one', () => {
    const clickedEarly = applyDecision(EMPTY_ENTRY, AT_NIGHT, 'f1', 'rejected');
    const merged = mergeLoaded(clickedEarly, AT_NIGHT, { f1: 'approved', f2: 'approved' });
    expect(merged.map).toEqual({ f1: 'rejected', f2: 'approved' });
  });

  it('discards what it holds when the load is for a different query', () => {
    expect(mergeLoaded(judged, 'a cyclist at night', { f9: 'approved' }).map).toEqual({ f9: 'approved' });
  });
});
