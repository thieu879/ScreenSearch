/**
 * Mapping from the API's `FrameHit` to the shape the cards render.
 *
 * Lives beside `ResultCard.tsx` rather than inside it because a module exporting both a component
 * and a plain function breaks React Fast Refresh — the module is re-evaluated on every edit and
 * component state is lost, which is what `react-refresh/only-export-components` reports.
 * `SceneItemData` stays in `ResultCard.tsx`: every consumer imports it with `import type`, which is
 * erased before the bundler sees it and so never trips the rule.
 */
import { thumbSrc } from '../../../api/client';
import { formatTimestamp, satisfiedLabel, type SupportedLang } from '../../../lib/satisfied';
import type { FrameHit } from '../../../types/api';
import type { SceneItemData } from './ResultCard';

export function frameHitToSceneData(hit: FrameHit, lang: SupportedLang = 'vi'): SceneItemData {
  // `score` is a raw cosine and is NOT a percentage: on this corpus the best frame of 6,858 scores
  // about 0.17 and meaningless input still scores 0.09, so `score * 100` labelled "%" showed a
  // perfect match as 16% and had no reachable top end. `match_probability` is the same number
  // through SigLIP2's own trained sigmoid, which is the scale the model was fitted to emit.
  // Null when the backend has no encoder loaded — then show the raw score and no bar, rather than
  // inventing a percentage.
  const pct = hit.match_probability === null ? null : hit.match_probability * 100;
  const similarityVal = pct === null ? 0 : Math.min(100, Math.round(pct * 10) / 10);
  const labels = hit.satisfied.length > 0
    ? hit.satisfied.map((token) => satisfiedLabel(token, lang))
    : ['Frame', 'CAM_FRONT'];
  const formattedTime = formatTimestamp(hit.timestamp_s);
  // Read off the id (`<token>_CAM_FRONT`) rather than asserted. This was the constant
  // 'CAM_FRONT_CENTER' — a camera the archive does not have, on a corpus that is CAM_FRONT only,
  // printed on every result and in the metadata table of the detail page.
  const cameraId = hit.frame_id.split('_').slice(1).join('_') || 'CAM_FRONT';

  return {
    id: hit.frame_id,
    // The frame's own id, not a fabricated name. This read `nuScenes_frame_<id>.jpg` and the
    // dataset row below it read `nuScenes (Production)` — both hardcoded, and both plainly wrong
    // the moment the service was pointed at the Hanoi corpus: every result claimed a dataset the
    // backend never named. Same defect as the `CAM_FRONT_CENTER` constant fixed above it, which
    // asserted a camera the archive does not have.
    //
    // The dataset row stayed blank after that, because the API sent no corpus name and showing
    // nothing beat guessing. It sends one as of 2026-08-30 (`FrameHit.corpus`), so the row is
    // filled from the merge record — and is still blank wherever that record cannot place a frame.
    filename: `${hit.frame_id}.jpg`,
    similarity: pct === null ? hit.score.toFixed(3) : `${similarityVal.toFixed(1)}%`,
    similarityVal,
    labels,
    timestamp: formattedTime,
    imgSrc: thumbSrc(hit.thumb_url),
    // The corpus the backend attributed this frame to, and `undefined` when it attributed none.
    // This was hardcoded and then deliberately blanked (see above); the API sends it as of
    // 2026-08-30, so the row can be filled from what the service knows instead of a constant.
    // Still absent for frames the merge record cannot place — which is the honest outcome, and the
    // detail page already renders an em dash for it.
    dataset: hit.corpus ?? undefined,
    cameraId,
    // The frame's own caption, which is what the rejection check scored the query against — so the
    // user sees the evidence behind the confidence verdict rather than a restatement of the number
    // already shown above it. This was a fixed sentence plus `score`, identical on every result of
    // every search, while the backend held something specific about each frame and never sent it.
    //
    // English because Florence-2 is, and labelled as such rather than machine-translated: a wrong
    // translation of the evidence is worse than evidence in the wrong language. Undefined when the
    // corpus has not captioned this frame yet — the detail panel omits the block entirely.
    description: hit.caption ?? undefined,
    rawHit: hit,
  };
}
