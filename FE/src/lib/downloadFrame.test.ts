import { describe, expect, it } from 'vitest';

import { outcomeFor } from './downloadFrame';

/**
 * The middle case is the one worth pinning. `fetch` resolves on a 404, `blob()` wraps the error body
 * without complaint, and the version of this code that shipped on 2026-08-27 saved that as
 * `frame.jpg` and told the user the download had succeeded. The whole defect is one status check.
 */
describe('outcomeFor', () => {
  it('saves when the server serves the bytes', () => {
    expect(outcomeFor(new Response('x', { status: 200 }))).toBe('saved');
  });

  it('refuses rather than saving an error body under a .jpg name', () => {
    expect(outcomeFor(new Response(JSON.stringify({ detail: 'Not found' }), { status: 404 }))).toBe('failed');
    expect(outcomeFor(new Response('', { status: 500 }))).toBe('failed');
  });

  it('hands a request that never completed to the browser, and does not call it saved', () => {
    expect(outcomeFor(null)).toBe('opened');
  });
});
