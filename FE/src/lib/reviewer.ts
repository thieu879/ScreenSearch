/**
 * The reviewer's pseudonymous id — who made a verdict, without asking anyone who they are.
 *
 * One deployment serves every tester from one SQLite table. Before this existed, two people judging
 * the same frame for the same query collided on the primary key and the second silently destroyed
 * the first, and every tester was shown every other tester's ticks and crosses before judging
 * anything. `src/services/reviews.py` carries the full argument.
 *
 * **A browser id, not a login.** No name, no email, no prompt. Enough to separate and attribute
 * verdicts and deliberately not enough to identify a person — a feedback session should not start
 * by collecting personal data it has no use for.
 *
 * **It is now the fallback, not the identity.** Being per-browser was the point when the service had
 * no accounts; once every product route sat behind a login it became the defect, because three
 * accounts signing in on one laptop share one `localStorage`, therefore one id, therefore one set of
 * verdicts — each seeing the other two's. Since then the server decides:
 * `src/services/reviews.py:reviewer_identity` files a verdict under the signed-in account and
 * **ignores** whatever this returns, so what is sent alongside a session is inert. This id still
 * governs a caller with no session, which is what the open review routes exist for, and it is still
 * sent on every call because the client cannot know which case it is in cheaply — the cookie does.
 *
 * `localStorage`, not `sessionStorage`: a tester who reloads, or comes back after lunch, is the
 * same reviewer. That is the opposite of `lastSearch.ts`, which is per-tab *because* a new tab
 * should be a clean session — the two are different questions and get different storage.
 */

const REVIEWER_KEY = 'scenesearch.reviewer.id';

/** `crypto.randomUUID` needs a secure context; a tunnel is https, but `http://localhost` in dev is
 * also secure by definition. The fallback exists for neither of those — it is for an unexpectedly
 * insecure origin, where returning `undefined` would make every verdict fail validation server-side
 * and the reviewer would see saving break for no visible reason. */
function newId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `r-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * The id for this browser, created on first use and stable thereafter.
 *
 * Storage failures (private browsing, a full quota, a blocked origin) fall back to a per-load id
 * rather than throwing. A reviewer whose verdicts are attributed to two ids across two reloads has
 * lost some grouping; a reviewer who cannot record a verdict at all has lost the session.
 */
export function getReviewerId(): string {
  try {
    const existing = localStorage.getItem(REVIEWER_KEY);
    if (existing) return existing;
    const created = newId();
    localStorage.setItem(REVIEWER_KEY, created);
    return created;
  } catch {
    return newId();
  }
}

/** Start a fresh reviewer on this browser — what an operator runs between two testers sharing one
 * machine, so the second person's verdicts are not filed under the first person's id. */
export function resetReviewerId(): string {
  const created = newId();
  try {
    localStorage.setItem(REVIEWER_KEY, created);
  } catch {
    /* Same reasoning as `getReviewerId`: an unstorable id is still better than a failed session. */
  }
  return created;
}
