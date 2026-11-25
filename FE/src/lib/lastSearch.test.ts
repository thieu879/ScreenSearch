import { describe, expect, it } from 'vitest';

import { parseLastSearch, serialiseLastSearch, type LastSearch } from './lastSearch';
import type { SearchResponse } from '../types/api';

const response: SearchResponse = {
  matched: true,
  confidence: 'high',
  reason: null,
  constraint: {
    objects: ['pedestrian'],
    relations: {},
    attributes: {},
    scene: {},
    out_of_scope: null,
    unsupported_relation: null,
    query_en: 'a pedestrian to the front-left',
  },
  results: [
    {
      frame_id: 'ae81961b714544968078764ec81112f9_CAM_FRONT',
      scene_id: '223096a415cc45bf8ecd4c3a42251fd7',
      timestamp_s: 7.9,
      score: 0.1477,
      match_probability: 0.467,
      thumb_url: '/api/v1/frames/ae81961b714544968078764ec81112f9_CAM_FRONT/thumb',
      satisfied: ['object:pedestrian'],
      caption: 'a person walking on the side of a city street at night',
      source: null,
      moment: null,
    },
  ],
  distinct_scenes: 1,
  trace_id: null,
};

describe('serialise/parse round trip', () => {
  it('returns the query and every result it was given', () => {
    const parsed = parseLastSearch(serialiseLastSearch('a pedestrian to the front-left', response));

    expect(parsed?.query).toBe('a pedestrian to the front-left');
    expect(parsed?.response.results).toHaveLength(1);
    expect(parsed?.response.results[0].frame_id).toBe('ae81961b714544968078764ec81112f9_CAM_FRONT');
  });

  it('keeps an empty result set as a search, not as nothing', () => {
    // `matched: false` is a real answer the archive gave. Coming back to it must show the "no
    // matches" state, not the untouched landing page, or the reviewer thinks their search vanished.
    const empty = { ...response, matched: false, results: [], distinct_scenes: 0 };
    const parsed = parseLastSearch(serialiseLastSearch('a bus on fire', empty));

    expect(parsed).not.toBeNull();
    expect(parsed?.response.results).toHaveLength(0);
  });
});

describe('parseLastSearch rejects anything it cannot trust', () => {
  // Each of these would otherwise reach the results grid and render as frames nobody searched for.
  it.each([
    ['nothing stored', null],
    ['empty string', ''],
    ['not JSON', '{oh no'],
    ['a JSON primitive', '"a string"'],
    ['null', 'null'],
    ['no query', JSON.stringify({ response })],
    ['an empty query', JSON.stringify({ query: '', response })],
    ['a non-string query', JSON.stringify({ query: 42, response })],
    ['no response', JSON.stringify({ query: 'cars at night' })],
    ['a response with no results array', JSON.stringify({ query: 'cars at night', response: {} })],
    ['results that are not an array', JSON.stringify({ query: 'cars at night', response: { results: 'many' } })],
  ])('returns null for %s', (_label, raw) => {
    expect(parseLastSearch(raw as string | null)).toBeNull();
  });
});

describe('the restored value is usable as state', () => {
  it('carries the fields the page reads on first paint', () => {
    const parsed = parseLastSearch(serialiseLastSearch('cars at night', response)) as LastSearch;

    expect(parsed.response.confidence).toBe('high');
    expect(parsed.response.distinct_scenes).toBe(1);
    expect(parsed.response.constraint.objects).toEqual(['pedestrian']);
  });
});
