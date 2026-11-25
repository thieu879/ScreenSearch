/**
 * Save a keyframe to disk.
 *
 * Both callers used to build an `<a download href={imgSrc}>` and click it. That is the simplest
 * thing that works, and it stops working the moment the image is served from another origin: the
 * `download` attribute is ignored cross-origin, so the browser navigates to the JPEG instead of
 * saving it and the chosen filename is thrown away. Fetching the bytes and handing over a blob URL
 * keeps the name, because a blob URL is same-origin by construction.
 *
 * What that trade costs, and why this file exists rather than the two inline copies it replaces:
 * a `fetch` **succeeds** on a 404. `response.blob()` will happily wrap `{"detail":"Not found"}`,
 * and the version that shipped on 2026-08-27 saved that as `frame.jpg` and reported success. So the
 * status has to be checked, and the two failure shapes have to be told apart.
 */

/**
 * - `saved` — the bytes are on their way to disk under the right name.
 * - `opened` — `fetch` never completed (offline, or a cross-origin block). The link is handed to
 *   the browser instead, which can still succeed where `fetch` cannot, but nothing here can observe
 *   whether it did. Do not report this as a completed download.
 * - `failed` — the server answered, and answered no.
 */
export type FrameDownloadOutcome = 'saved' | 'opened' | 'failed';

/**
 * Which of the three happened, given the response — or `null` if `fetch` itself threw.
 *
 * Split out from the work below so it can be tested at all: this project's vitest runs in `node`
 * with no jsdom, on purpose (`vitest.config.ts`), and the same reasoning that pulled the review
 * transitions into `reviewState.ts` applies here. The bug this module exists to fix lives entirely
 * in this function — everything after it is DOM plumbing.
 */
export function outcomeFor(response: Response | null): FrameDownloadOutcome {
  if (response === null) return 'opened';
  return response.ok ? 'saved' : 'failed';
}

/** Click a synthetic anchor. `target` only for the fallback, where the href is not a blob URL. */
function clickLink(href: string, filename: string, newTab: boolean): void {
  const link = document.createElement('a');
  link.href = href;
  link.download = filename || 'frame.jpg';
  if (newTab) link.target = '_blank';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

export async function downloadFrame(imgSrc: string, filename: string): Promise<FrameDownloadOutcome> {
  const response = await fetch(imgSrc).catch(() => null);
  const outcome = outcomeFor(response);

  if (outcome === 'opened') {
    clickLink(imgSrc, filename, true);
    return outcome;
  }
  // No link fallback on `failed`: it would request the same URL, get the same refusal, and save the
  // error body under a `.jpg` name. A silent bad file is worse than a stated failure.
  if (outcome === 'failed') return outcome;

  const url = URL.createObjectURL(await (response as Response).blob());
  clickLink(url, filename, false);
  // Revoked on a timer rather than on the next line. The click only *starts* the save; revoking in
  // the same tick can cancel it, a race that resolves differently per browser and per file size —
  // the worst kind to leave in. Ten seconds is long after any local blob has been read.
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
  return outcome;
}
