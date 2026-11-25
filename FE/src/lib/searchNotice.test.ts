import { describe, expect, it } from 'vitest';
import { noticeFor } from './searchNotice';
import type { SearchResponse } from '../types/api';

// Spreading a Partial widens every field with `| undefined`, which the strict config rejects, so the
// fixture asserts its own shape. It is a test double, not a value crossing a boundary.
const constraint = (over: Partial<SearchResponse['constraint']> = {}): SearchResponse['constraint'] =>
  ({
    objects: [],
    relations: {},
    attributes: {},
    scene: {},
    out_of_scope: null,
    ...over,
  }) as SearchResponse['constraint'];

const response = (over: Partial<SearchResponse> = {}): SearchResponse =>
  ({
    matched: true,
    confidence: 'high',
    reason: null,
    constraint: constraint(),
    results: [],
    distinct_scenes: 0,
    ...over,
  }) as SearchResponse;

describe('noticeFor', () => {
  it('does not refuse a motion query that was answered — the v1.7.1 defect', () => {
    // Exactly what production returns for `a motorcycle cutting into our lane`: ten results, deep
    // links, a moment clip — and out_of_scope set as a caveat.
    const d = noticeFor(
      response({
        matched: true,
        confidence: 'low',
        reason: 'This search reads single frames, so it cannot confirm the movement.',
        constraint: constraint({ out_of_scope: 'cutting into our lane is motion across time, not one frame' }),
      })
    );
    expect(d.variant).toBe('caveat');
    expect(d).toHaveProperty('lowConfidence', true);
  });

  it('emits exactly one notice, never a refusal stacked on a caveat', () => {
    const d = noticeFor(
      response({ matched: true, reason: 'caveat text', constraint: constraint({ out_of_scope: 'motion' }) })
    );
    // A single decision by construction: the old JSX could and did render two at once.
    expect(['caveat']).toContain(d.variant);
  });

  it('still refuses a motion query on a corpus with no footage', () => {
    const d = noticeFor(
      response({ matched: false, confidence: null, reason: 'r', constraint: constraint({ out_of_scope: 'motion' }) })
    );
    expect(d.variant).toBe('outOfScope');
  });

  it('distinguishes "nothing matched" from "cannot be asked"', () => {
    const d = noticeFor(response({ matched: false, confidence: null, reason: 'nothing here' }));
    expect(d.variant).toBe('empty');
  });

  it('shows nothing when a confident answer needs no caveat', () => {
    expect(noticeFor(response({ matched: true, reason: null })).variant).toBe('none');
  });
});
