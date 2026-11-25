import type { MomentTrack } from '../types/api';

/**
 * The arithmetic behind the moment overlay, kept out of the component so it can be tested.
 *
 * Same reason `downloadFrame.ts` exists: these are the parts that can be *wrong* rather than merely
 * ugly — a box drawn on the wrong frame, or a distance rendered with a precision nothing measured —
 * and the FE test suite runs in plain node with no DOM. A component test would need jsdom; this
 * needs nothing.
 */

/** Which clip frame a playback position lands on. Rounded, because the video seeks continuously and the boxes do not. */
export function frameAt(currentTime: number, fps: number): number {
  return Math.round(currentTime * fps);
}

/**
 * The track's box on this frame, or `null` when it has none.
 *
 * **`null` is the important case.** `at` carries gaps — frames where the detector missed the
 * vehicle — and the honest rendering is nothing at all. Interpolating between the neighbours would
 * draw a box on a frame where nothing was measured, which is the same class of error as a caption
 * that states an absence: confident, invisible, and wrong.
 */
export function boxAt(track: MomentTrack, frame: number): [number, number, number, number] | null {
  const index = track.at.indexOf(frame);
  return index === -1 ? null : track.boxes[index];
}

/**
 * How far away the vehicle is on THIS frame, or `null` when it was not seen.
 *
 * The tag showed `closest_m` — the minimum over the whole clip — until someone watched it: an
 * overtaking car kept reading 2.5 m while it was already well ahead, and two vehicles at obviously
 * different depths showed the same figure, because each had reached that minimum at a different
 * moment and the values had been rounded into the same string. A number on a moving box has to be
 * the number for that moment.
 */
export function distanceAt(track: MomentTrack, frame: number): number | null {
  const index = track.at.indexOf(frame);
  return index === -1 ? null : (track.distances[index] ?? null);
}

/** A box as CSS percentages, so the overlay scales with however large the player is drawn. */
export function boxStyle(box: [number, number, number, number]): {
  left: string;
  top: string;
  width: string;
  height: string;
} {
  const [x0, y0, x1, y1] = box;
  return {
    left: `${x0 * 100}%`,
    top: `${y0 * 100}%`,
    width: `${(x1 - x0) * 100}%`,
    height: `${(y1 - y0) * 100}%`,
  };
}

/**
 * A distance, written the way it was measured.
 *
 * One decimal and a leading `~`, always. The value is rounded to 0.5 m at the source because the
 * scale is recovered from typical vehicle widths — on one clip it came back 0.92 m where a dashcam
 * sits nearer 1.3 — so `2.0 m` would read as a measurement to the centimetre that nobody made.
 */
export function formatDistance(metres: number): string {
  return `~${metres.toFixed(1)} m`;
}
