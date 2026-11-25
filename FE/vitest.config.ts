import { defineConfig } from 'vitest/config';

/**
 * Kept separate from `vite.config.ts`, and deliberately minimal.
 *
 * The units under test — `composeQuery`, `satisfiedLabel`, `attributeLabel`, `formatTimestamp`, and
 * the `reviewState` transitions — are pure functions over plain data. They need no DOM, no React
 * renderer and no jsdom, so none is installed. Adding a browser environment "for later" would
 * triple the dependency surface and slow every run to test nothing that exists today.
 *
 * `reviewState.ts` exists *because* of this line. The review hook's optimistic update, rollback and
 * load-merge are the logic most likely to be wrong, so they were extracted from the hook into pure
 * functions rather than left untested behind a renderer this project does not have.
 *
 * Component tests, if they arrive, will need jsdom and @testing-library/react; that is the point to
 * add them, not before.
 */
export default defineConfig({
  test: {
    include: ['src/**/*.test.ts'],
    environment: 'node',
  },
});
