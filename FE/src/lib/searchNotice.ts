import type { SearchResponse } from '../types/api';

/**
 * Which notice, if any, sits above the results.
 *
 * **The rule: `matched` decides whether there are results. `out_of_scope` never does.**
 *
 * This exists as a function rather than inline JSX because getting it wrong is invisible — the page
 * still renders, the results are still there, and only the banner above them lies. It did lie:
 * `a motorcycle cutting into our lane` returned ten linked results with a moment clip attached,
 * under a heading announcing the query was out of scope, and under a second notice repeating the
 * same text, because the refusal branch and the caveat branch both fired.
 *
 * `out_of_scope` changed meaning when Tier 1 landed. On a corpus with no footage a motion query is
 * refused, as before. On one with footage it is *answered* — deep links, sometimes a clip — and the
 * field downgrades to a caveat saying a single frame cannot show movement. Same field, opposite
 * verdicts, and only `matched` separates them. `api-contract.md` states this.
 */
export type NoticeDecision =
  | { variant: 'none' }
  | { variant: 'outOfScope'; message: string | null }
  | { variant: 'empty'; message: string | null }
  | { variant: 'caveat'; message: string; lowConfidence: boolean };

export function noticeFor(response: SearchResponse): NoticeDecision {
  const outOfScope = response.constraint?.out_of_scope ?? null;

  if (!response.matched) {
    // A refusal. `out_of_scope` distinguishes "this question cannot be asked of stills" from
    // "nothing here matches", which are different answers and deserve different wording.
    const message = response.reason ?? outOfScope;
    return outOfScope ? { variant: 'outOfScope', message } : { variant: 'empty', message };
  }

  // Answered. Any `reason` is a caveat about results the user can see, never a verdict against them.
  if (response.reason) {
    return { variant: 'caveat', message: response.reason, lowConfidence: response.confidence === 'low' };
  }
  return { variant: 'none' };
}
