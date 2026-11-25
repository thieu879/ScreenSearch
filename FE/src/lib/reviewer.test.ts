/**
 * The reviewer id has exactly two jobs and both are testable: be the same across reloads, and be
 * different from anyone else's. Everything else about it is deliberately absent — no name, no
 * prompt, no server round-trip.
 *
 * `vitest.config.ts` sets `environment: 'node'` and explains why jsdom is not installed, so these
 * supply their own storage rather than assuming a browser. The fake is an in-memory Map with the
 * three methods this module touches; a full `Storage` polyfill would be more code testing less.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { getReviewerId, resetReviewerId } from './reviewer';

const KEY = 'scenesearch.reviewer.id';

function fakeStorage() {
  const map = new Map<string, string>();
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    clear: () => map.clear(),
  };
}

beforeEach(() => {
  vi.stubGlobal('localStorage', fakeStorage());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('getReviewerId', () => {
  it('returns the same id on every call, which is what makes a session one reviewer', () => {
    expect(getReviewerId()).toBe(getReviewerId());
  });

  it('persists it, so a reload is the same reviewer rather than a new one', () => {
    const first = getReviewerId();
    expect(localStorage.getItem(KEY)).toBe(first);
  });

  it('reuses an id already stored rather than minting a second one', () => {
    localStorage.setItem(KEY, 'existing-id');
    expect(getReviewerId()).toBe('existing-id');
  });

  it('gives two browsers different ids — the whole point of attribution', () => {
    const ann = getReviewerId();
    vi.stubGlobal('localStorage', fakeStorage()); // a second browser, empty storage
    expect(getReviewerId()).not.toBe(ann);
  });

  it('still returns an id when storage throws, because a failed verdict is worse than a regrouped one', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('private browsing');
      },
      setItem: () => {
        throw new Error('private browsing');
      },
    });
    expect(getReviewerId()).toMatch(/.+/);
  });

  it('falls back to a generated id where crypto.randomUUID is unavailable', () => {
    vi.stubGlobal('crypto', {});
    expect(getReviewerId()).toMatch(/^r-/);
  });
});

describe('resetReviewerId', () => {
  it('issues a different id, so two testers on one machine are not filed as one person', () => {
    const first = getReviewerId();
    const second = resetReviewerId();
    expect(second).not.toBe(first);
    expect(getReviewerId()).toBe(second);
  });
});
