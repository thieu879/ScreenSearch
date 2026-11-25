import { describe, expect, it } from 'vitest';

import { composeQuery, isEmptyQuery } from './composeQuery';
import { MAX_QUERY_LENGTH } from '../api/client';
import type { FilterItem } from '../types/sceneSearch';

/** Only the fields `composeQuery` reads; `label` matters solely for ids it does not know. */
function filters(sections: Record<string, [string, boolean][]>): Record<string, FilterItem[]> {
  return Object.fromEntries(
    Object.entries(sections).map(([key, items]) => [
      key,
      items.map(([id, checked]) => ({ id, label: id, checked })),
    ]),
  );
}

describe('composeQuery', () => {
  it('returns the typed text alone when nothing is ticked', () => {
    expect(composeQuery('  a wet road at night  ', filters({}))).toBe('a wet road at night');
  });

  it('omits the "with" joiner when there is no typed text to join to', () => {
    const q = composeQuery('', filters({ objects: [['pedestrian', true], ['car', true]] }));
    expect(q).toBe('a pedestrian and a car');
  });

  it('joins filters onto typed text', () => {
    const q = composeQuery('a wet road', filters({ objects: [['pedestrian', true]] }));
    expect(q).toBe('a wet road with a pedestrian');
  });

  it('renders scene conditions as a trailing clause, not a noun', () => {
    const q = composeQuery('a road', filters({ weather: [['night', true]] }));
    expect(q).toBe('a road at night');
  });

  it('ignores unchecked items', () => {
    const q = composeQuery('a road', filters({ objects: [['car', false], ['pedestrian', true]] }));
    expect(q).toBe('a road with a pedestrian');
  });

  /**
   * The guard that matters most. Every option in `actions` describes motion across frames, which
   * single-frame retrieval classifies out of scope by design. If these ever reached the query, the
   * user would get a refusal for a checkbox the UI offered them.
   */
  it('never contributes the actions section', () => {
    const q = composeQuery('a car', filters({ actions: [['brake', true], ['leftturn', true]] }));
    expect(q).toBe('a car');
  });

  it('falls back to the label for ids it does not know, so custom filters still do something', () => {
    const custom: Record<string, FilterItem[]> = {
      objects: [{ id: 'objects-1712345678', label: 'a fire truck', checked: true }],
    };
    expect(composeQuery('', custom)).toBe('a fire truck');
  });

  /** The API rejects anything longer with a 422, so the cap has to hold before the round trip. */
  it('caps at the length the API accepts', () => {
    const q = composeQuery('x'.repeat(MAX_QUERY_LENGTH + 250), filters({ objects: [['car', true]] }));
    expect(q).toHaveLength(MAX_QUERY_LENGTH);
  });

  it('is empty when nothing is typed and nothing is ticked', () => {
    expect(composeQuery('   ', filters({ objects: [['car', false]] }))).toBe('');
  });

  it('tolerates a section the filters object does not have', () => {
    expect(composeQuery('a road', {})).toBe('a road');
  });
});

describe('isEmptyQuery', () => {
  it('is true only when the composed query would be empty', () => {
    expect(isEmptyQuery('', filters({ objects: [['car', false]] }))).toBe(true);
    expect(isEmptyQuery('  ', {})).toBe(true);
    expect(isEmptyQuery('', filters({ objects: [['car', true]] }))).toBe(false);
    expect(isEmptyQuery('a road', {})).toBe(false);
  });

  it('stays true when only the actions section is ticked, since it contributes nothing', () => {
    expect(isEmptyQuery('', filters({ actions: [['brake', true]] }))).toBe(true);
  });
});
