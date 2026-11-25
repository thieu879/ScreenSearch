/**
 * Every `t('key')` a component asks for must exist in both locales.
 *
 * **This is a real bug class, not a tidiness rule.** i18next falls back to rendering the key itself
 * when it has no translation, so a missing entry does not throw, does not warn in production, and
 * does not fail any other test — it puts `REG_FAIL_TITLE` on screen where an error message should
 * be, styled as a heading by whatever CSS uppercases it. Twenty keys were in that state when this
 * was written, sixteen of them in the registration and OTP flow, which is the first thing a new
 * user touches; `TH_COUNT` was a visible column header on the search-history page.
 *
 * A missing key in *one* locale is the same defect wearing a disguise — the app looks correct until
 * someone switches language — so the two are checked separately rather than as a union.
 *
 * Sources are read with `import.meta.glob(..., '?raw')` rather than `node:fs`, which keeps this
 * inside the types the app already has: `tsconfig.app.json` declares only `vite/client`, and
 * reaching for the filesystem would mean adding `@types/node` to the app's build so that one test
 * can list a directory.
 *
 * Scanning text rather than rendering components is a deliberate trade: it reaches every call site
 * cheaply, including ones no test renders, and in exchange it only sees *literal* keys. `t(someVar)`
 * and template literals are invisible here. Those are rare, and the alternative — a render pass over
 * every route — is a much larger thing that would still miss any branch it did not exercise.
 */

import { describe, expect, it } from 'vitest';

import i18n from './index';

/** Every source file in `src`, as text. Tests and the locale tables themselves are filtered below. */
const SOURCES = import.meta.glob('../**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

/** Literal `t('some_key')` calls. Deliberately not matching `t(variable)` — see the module note. */
const T_CALL = /\bt\(\s*'([a-zA-Z0-9_]+)'/g;

/** A second argument to `t()` is an inline default, so that key cannot leak even when undefined. */
const T_CALL_WITH_DEFAULT = /\bt\(\s*'([a-zA-Z0-9_]+)'\s*,\s*'/g;

/**
 * `<Trans i18nKey="...">`, which is the other way a key reaches i18next.
 *
 * Added when `MomentPlayer` started using `Trans` to keep the emphasis inside a caveat. Without it
 * this file would have gone on passing while the newest keys were exactly the unchecked ones — a
 * guard that quietly stops covering the thing it was written for is worse than no guard at all.
 */
const TRANS_KEY = /\bi18nKey=["']([a-zA-Z0-9_]+)["']/g;

function keysUsed(): Map<string, string> {
  const used = new Map<string, string>();
  for (const [path, text] of Object.entries(SOURCES)) {
    if (/\.test\.tsx?$/.test(path) || path.includes('/i18n/')) continue;
    const withDefault = new Set(Array.from(text.matchAll(T_CALL_WITH_DEFAULT), (m) => m[1]));
    for (const match of [...text.matchAll(T_CALL), ...text.matchAll(TRANS_KEY)]) {
      const key = match[1];
      if (withDefault.has(key) || used.has(key)) continue;
      used.set(key, path);
    }
  }
  return used;
}

describe('translation keys', () => {
  const used = keysUsed();

  it('finds the call sites at all, so a silent zero cannot pass this file', () => {
    // Without this, a glob or regex that quietly stopped matching would make both assertions below
    // vacuously true, and the check would go on reporting success while covering nothing.
    expect(used.size).toBeGreaterThan(100);
  });

  for (const locale of ['vi', 'en']) {
    it(`has a ${locale} string for every key a component asks for`, () => {
      const missing = [...used.entries()]
        .filter(([key]) => !i18n.getResource(locale, 'translation', key))
        .map(([key, path]) => `${key} (${path})`);

      expect(missing).toEqual([]);
    });
  }
});
