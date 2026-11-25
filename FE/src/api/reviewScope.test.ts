import { afterEach, describe, expect, it, vi } from 'vitest';
import { exportUrl, fetchReviewExport, fetchReviewSummary, fetchReviewSummaryAll } from './client';

/**
 * **The count and the export must agree about whose verdicts they describe.**
 *
 * They did not. `fetchReviewSummary` sends `reviewer=<browser id>`; `fetchReviewExport` and
 * `exportUrl` send none and return every reviewer's rows. The export page used the first to label
 * and gate the second, so the badge showed your count over everyone's items, and a tester saw
 * verdicts from an earlier session that the review bar — correctly scoped — could not show.
 *
 * It also disabled the button on the wrong number: `rowCount === 0` gates the download, so a
 * signed-in user with no verdicts of their own could not export a dataset that exists.
 *
 * Asserted on the request URL because that is where the scope actually lives. A test of the rendered
 * count would have passed against the broken version — the number was real, it just described the
 * wrong set.
 */
function mockFetch(payload: unknown = { approved: 0, rejected: 0, bookmarked: 0, queries_reviewed: 0, total: 0, decisions: [] }) {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => payload });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
const urlOf = (f: ReturnType<typeof vi.fn>) => new URL(f.mock.calls[0][0] as string, 'http://x');

afterEach(() => vi.unstubAllGlobals());

describe('review scope', () => {
  it('the per-reviewer summary is scoped — the review bar depends on this', async () => {
    const f = mockFetch();
    await fetchReviewSummary();
    expect(urlOf(f).searchParams.get('reviewer')).toBeTruthy();
  });

  it('the export-page summary is NOT scoped, so it counts what the export contains', async () => {
    const f = mockFetch();
    await fetchReviewSummaryAll();
    expect(urlOf(f).searchParams.has('reviewer')).toBe(false);
  });

  it('neither export call is scoped, which is what the unscoped count now matches', async () => {
    const f = mockFetch();
    await fetchReviewExport('approved');
    expect(urlOf(f).searchParams.has('reviewer')).toBe(false);
    expect(new URL(exportUrl('json', 'approved'), 'http://x').searchParams.has('reviewer')).toBe(false);
  });

  it('sends the session cookie, or the signed-in-only routes 401 cross-origin', async () => {
    const f = mockFetch();
    await fetchReviewSummaryAll();
    expect(f.mock.calls[0][1]).toMatchObject({ credentials: 'include' });
  });
});
