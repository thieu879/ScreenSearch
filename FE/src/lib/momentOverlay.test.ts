import { describe, expect, it } from 'vitest';
import type { MomentTrack } from '../types/api';
import { boxAt, boxStyle, distanceAt, formatDistance, frameAt } from './momentOverlay';

const track: MomentTrack = {
  label: 'motorcycle',
  closest_m: 2.0,
  lateral_m: 0.08,
  closest_at: 1,
  distances: [4.8, 3.1, 2.0],
  frames: [3, 6],
  // Frame 5 is missing on purpose: the detector lost it for one frame, which is what MAX_GAP allows.
  at: [3, 4, 6],
  boxes: [
    [0.3, 0.5, 0.4, 0.7],
    [0.32, 0.5, 0.42, 0.72],
    [0.36, 0.5, 0.46, 0.76],
  ],
};

describe('frameAt', () => {
  it('rounds a continuous playback position onto a discrete frame', () => {
    expect(frameAt(0, 10)).toBe(0);
    expect(frameAt(0.44, 10)).toBe(4);
    expect(frameAt(0.46, 10)).toBe(5);
  });
});

describe('boxAt', () => {
  it('finds the box the track carries for that frame', () => {
    expect(boxAt(track, 4)).toEqual([0.32, 0.5, 0.42, 0.72]);
  });

  it('draws NOTHING on a frame the track has no box for', () => {
    // The whole rule: a gap is a frame where nothing was measured, and interpolating one would put
    // a confident rectangle on footage that never supported it.
    expect(boxAt(track, 5)).toBeNull();
  });

  it('draws nothing outside the track entirely', () => {
    expect(boxAt(track, 0)).toBeNull();
    expect(boxAt(track, 99)).toBeNull();
  });
});

describe('distanceAt', () => {
  it('is the distance on THAT frame, not the track minimum', () => {
    // The bug this exists to prevent: the tag read 2.0 on every frame, so an overtaking vehicle
    // kept its closest value while it was already far away.
    expect(distanceAt(track, 3)).toBe(4.8);
    expect(distanceAt(track, 4)).toBe(3.1);
    expect(distanceAt(track, 6)).toBe(2.0);
  });

  it('has nothing to say on a frame the track skipped', () => {
    expect(distanceAt(track, 5)).toBeNull();
  });
});

describe('boxStyle', () => {
  it('is percentages, so the overlay scales with the player rather than the encode', () => {
    expect(boxStyle([0.25, 0.5, 0.75, 1])).toEqual({
      left: '25%',
      top: '50%',
      width: '50%',
      height: '50%',
    });
  });
});

describe('formatDistance', () => {
  it('keeps the ~ and one decimal, because the number is an estimate rounded to 0.5 m', () => {
    expect(formatDistance(2)).toBe('~2.0 m');
    expect(formatDistance(6.5)).toBe('~6.5 m');
  });
});
