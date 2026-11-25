import { describe, expect, it } from 'vitest';

import { attributeLabel, formatTimestamp, satisfiedLabel, shortSceneId } from './satisfied';

describe('satisfiedLabel', () => {
  it('reads the three token shapes the backend actually emits', () => {
    // src/services/search/filters.py:satisfied_conditions builds exactly these and nothing else.
    expect(satisfiedLabel('object:car')).toBe('Xe con');
    expect(satisfiedLabel('rel:pedestrian:front_left')).toBe('Người đi bộ · trước trái');
    expect(satisfiedLabel('scene:time=night')).toBe('ban đêm');
  });

  it('covers both values of the one tagged scene axis', () => {
    // `time` is the only axis ingest writes — weather measured 76.3% and is never tagged, so
    // `scene:weather=rain` cannot reach here. If that changes, this test should change with it.
    for (const value of ['night', 'day']) {
      expect(satisfiedLabel(`scene:time=${value}`)).not.toContain(value);
    }
  });

  it('covers every category and relation in the closed vocabulary', () => {
    // A category the parser can emit but this map lacks would render as a raw enum name in the UI.
    for (const category of [
      'pedestrian',
      'car',
      'truck',
      'bus',
      'bicycle',
      'motorcycle',
      'construction_vehicle',
      'traffic_cone',
      'barrier',
    ]) {
      expect(satisfiedLabel(`object:${category}`)).not.toBe(category);
    }
    for (const relation of ['front', 'front_left', 'front_right']) {
      expect(satisfiedLabel(`rel:car:${relation}`)).not.toContain(relation);
    }
  });

  /**
   * Passing unknown input through is the documented behaviour, and it is the safer failure: a
   * backend that adds a third token shape shows an odd label rather than silently dropping a
   * condition the user is relying on.
   */
  it('passes unrecognised input through rather than dropping it', () => {
    expect(satisfiedLabel('attr:car:parked')).toBe('attr:car:parked');
    expect(satisfiedLabel('object:spaceship')).toBe('spaceship');
    expect(satisfiedLabel('nonsense')).toBe('nonsense');
    expect(satisfiedLabel('')).toBe('');
  });

  it('supports English labels when lang is en', () => {
    expect(satisfiedLabel('object:car', 'en')).toBe('Car');
    expect(satisfiedLabel('rel:pedestrian:front_left', 'en')).toBe('Pedestrian · front-left');
    expect(satisfiedLabel('scene:time=night', 'en')).toBe('night');
    expect(satisfiedLabel('scene:weather=rain', 'en')).toBe('rainy');
    expect(attributeLabel('car', 'parked', 'en')).toBe('Car · parked');
  });
});

describe('attributeLabel', () => {
  it('covers every attribute in the closed vocabulary', () => {
    for (const attribute of ['moving', 'stopped', 'parked', 'standing', 'with_rider', 'without_rider']) {
      expect(attributeLabel('car', attribute)).not.toContain(attribute);
    }
  });

  it('renders category and attribute together', () => {
    expect(attributeLabel('car', 'parked')).toBe('Xe con · đang đỗ');
  });

  it('falls back to the raw value for anything outside the vocabulary', () => {
    expect(attributeLabel('car', 'levitating')).toBe('Xe con · levitating');
  });
});

describe('formatTimestamp', () => {
  it('pads the seconds so timestamps line up in a column', () => {
    expect(formatTimestamp(0)).toBe('0:00.0');
    expect(formatTimestamp(1.5)).toBe('0:01.5');
    expect(formatTimestamp(13.5)).toBe('0:13.5');
  });

  it('rolls over into minutes', () => {
    expect(formatTimestamp(60)).toBe('1:00.0');
    expect(formatTimestamp(65.4)).toBe('1:05.4');
    expect(formatTimestamp(600)).toBe('10:00.0');
  });
});

describe('shortSceneId', () => {
  it('truncates the 32-hex id to something readable', () => {
    expect(shortSceneId('cc8c0bf57f984915a77078b10eb33198')).toBe('cc8c0bf5');
  });
});
