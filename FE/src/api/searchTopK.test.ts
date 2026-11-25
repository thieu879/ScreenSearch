import { describe, expect, it, vi, afterEach } from 'vitest';
import { searchScenes } from './client';

/**
 * `top_k` is the number of results the server returns AND the diversity window it reranks over
 * (`services/search/diversity.py`). Both halves of that matter here:
 *
 * - Omitted when the caller has no opinion, so `DEFAULT_TOP_K` stays the single owner of the number.
 *   A frontend constant that guessed 10 would agree with the server today and drift silently.
 * - Clamped to 1-50, which is what `schemas.py` accepts. Out of range is a 422, and a round trip to
 *   discover that is a round trip wasted.
 *
 * These are asserted against the request body rather than the UI because the defect they replace was
 * exactly this: a 10/20/50 dropdown that changed a local variable and never reached the server.
 */

function mockFetch(): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ matched: true, results: [], constraint: {}, distinct_scenes: 0 }),
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

const bodyOf = (fetchMock: ReturnType<typeof vi.fn>) =>
  JSON.parse(fetchMock.mock.calls[0][1].body as string);

afterEach(() => vi.unstubAllGlobals());

describe('searchScenes top_k', () => {
  it('omits top_k entirely when the caller does not ask for one', async () => {
    const f = mockFetch();
    await searchScenes('a pedestrian on the right');
    expect(bodyOf(f)).not.toHaveProperty('top_k');
  });

  it('sends the requested count', async () => {
    const f = mockFetch();
    await searchScenes('a pedestrian on the right', 50);
    expect(bodyOf(f).top_k).toBe(50);
  });

  it('clamps to the range schemas.py accepts, rather than paying a 422 to find out', async () => {
    for (const [asked, sent] of [[0, 1], [-5, 1], [51, 50], [9999, 50]] as const) {
      const f = mockFetch();
      await searchScenes('q', asked);
      expect(bodyOf(f).top_k).toBe(sent);
      vi.unstubAllGlobals();
    }
  });

  it('truncates a fractional count instead of sending a float the API will reject', async () => {
    const f = mockFetch();
    await searchScenes('q', 12.7);
    expect(bodyOf(f).top_k).toBe(12);
  });
});
