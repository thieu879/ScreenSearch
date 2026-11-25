/**
 * The product routes must stay reachable without an account.
 *
 * This reads the router's own source rather than rendering it. `vitest.config.ts` deliberately
 * installs no jsdom and no React renderer, and that decision is worth more than this test is — so
 * the assertion is made the only way it can be made without reversing it.
 *
 * What it proves is narrow and worth stating: that none of these paths is written with a
 * `ProtectedRoute` wrapper. It does not prove the pages render, and it would not catch a gate
 * introduced somewhere other than this file. It catches the one regression that has actually
 * happened here — a route quietly re-wrapped while the auth work was landing — which turned every
 * entry point, including `*`, into a redirect to `/login`.
 *
 * If a route legitimately needs an account, delete its line here in the same commit. A failing
 * assertion is the conversation, not an obstacle to route around.
 */
import { describe, expect, it } from 'vitest';

// `?raw` rather than `node:fs`, so the test needs neither @types/node nor a path relative to a
// working directory. Vite resolves it the same way in a run and in the build.
import source from './index.tsx?raw';

/** Paths a visitor with no account must be able to open (Home landing page). */
const OPEN_PATHS = ['/'];

/** Paths that genuinely need a user (all application feature routes require login). */
const GATED_PATHS = ['/search', '/archive', '/history', '/export', '/scene/:id', '/detail', '/profile', '/admin', '/admin/users', '/admin/dataset', '/admin/monitoring'];

function routeLine(path: string): string {
  const line = source.split('\n').find((l) => l.includes(`<Route path="${path}"`));
  if (!line) throw new Error(`no <Route path="${path}"> in router/index.tsx`);
  return line;
}

describe('router', () => {
  it.each(OPEN_PATHS)('leaves %s reachable without an account', (path) => {
    expect(routeLine(path)).not.toContain('ProtectedRoute');
  });

  it.each(GATED_PATHS)('keeps %s behind a login', (path) => {
    expect(routeLine(path)).toContain('ProtectedRoute');
  });

  it('sends unknown paths to Home landing page rather than to the login page', () => {
    expect(routeLine('*')).toContain('/');
  });
});
