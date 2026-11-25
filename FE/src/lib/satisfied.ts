/**
 * Turn a hit's `satisfied` tokens into labels a person can read.
 *
 * The backend emits exactly three shapes (`src/services/search/filters.py:satisfied_conditions`):
 *
 *     object:<category>
 *     rel:<category>:<relation>
 *     scene:<axis>=<value>          // added 2026-08-02, M2_DESIGN §11.2
 *
 * `scene:` carries only axes the ingest tagger actually writes — today that is `time`, measured at
 * 99.9%. `weather` measured 76.3% and is deliberately never tagged, so no `scene:weather=` token
 * exists to render; a rain query is answered by the embedding alone.
 *
 * There is no `attr:` token. `attributeLabel` below exists for the constraint chips, which are built
 * client-side from `QueryConstraint` rather than from these tokens — same vocabulary, different
 * source. Deliberately not folded into `satisfiedLabel`, because that would imply a wire format the
 * server never produces.
 *
 * Anything unrecognised is passed through verbatim rather than dropped, so a future backend
 * addition shows up as an odd label instead of silently disappearing.
 *
 * These conditions come from detected pixels, never from the dataset's own annotations, which is
 * what makes them evidence rather than a restatement of the ground truth.
 */
import type { Attribute, Category, Relation } from '../types/api';

export type SupportedLang = 'vi' | 'en';

const CATEGORY_LABEL_VI: Record<Category, string> = {
  pedestrian: 'Người đi bộ',
  car: 'Xe con',
  truck: 'Xe tải',
  bus: 'Xe buýt',
  bicycle: 'Xe đạp',
  motorcycle: 'Mô tô',
  construction_vehicle: 'Xe công trình',
  traffic_cone: 'Cọc tiêu',
  barrier: 'Rào chắn',
};

const CATEGORY_LABEL_EN: Record<Category, string> = {
  pedestrian: 'Pedestrian',
  car: 'Car',
  truck: 'Truck',
  bus: 'Bus',
  bicycle: 'Bicycle',
  motorcycle: 'Motorcycle',
  construction_vehicle: 'Construction vehicle',
  traffic_cone: 'Traffic cone',
  barrier: 'Barrier',
};

const RELATION_LABEL_VI: Record<Relation, string> = {
  front: 'phía trước',
  front_left: 'trước trái',
  front_right: 'trước phải',
};

const RELATION_LABEL_EN: Record<Relation, string> = {
  front: 'front',
  front_left: 'front-left',
  front_right: 'front-right',
};

const ATTRIBUTE_LABEL_VI: Record<Attribute, string> = {
  moving: 'đang di chuyển',
  stopped: 'đang dừng',
  parked: 'đang đỗ',
  standing: 'đang đứng',
  with_rider: 'có người lái',
  without_rider: 'không có người lái',
};

const ATTRIBUTE_LABEL_EN: Record<Attribute, string> = {
  moving: 'moving',
  stopped: 'stopped',
  parked: 'parked',
  standing: 'standing',
  with_rider: 'with rider',
  without_rider: 'without rider',
};

/**
 * Scene tag values, keyed `<axis>=<value>` because a label reads off the pair, not the axis.
 * "ban đêm" already says it is about time of day; prefixing it with "Thời gian ·" would only add
 * noise to a chip that has to be scannable at a glance beside the object ones.
 */
const SCENE_LABEL_VI: Record<string, string> = {
  'time=night': 'ban đêm',
  'time=day': 'ban ngày',
  'weather=rain': 'trời mưa',
  'weather=clear': 'trời quang',
};

const SCENE_LABEL_EN: Record<string, string> = {
  'time=night': 'night',
  'time=day': 'day',
  'weather=rain': 'rainy',
  'weather=clear': 'clear',
};

export function categoryLabel(raw: string, lang: SupportedLang = 'vi'): string {
  const dict = lang === 'en' ? CATEGORY_LABEL_EN : CATEGORY_LABEL_VI;
  return dict[raw as Category] ?? raw;
}

/**
 * `car` + `parked` → "Xe con · đang đỗ" (vi) / "Car · parked" (en).
 *
 * Only reachable from the constraint chips. Without it, a query like "a parked car to the
 * front-right" showed the object and the position but silently dropped the attribute — leaving a
 * third of the parse invisible in the one place built to make a wrong parse visible.
 */
export function attributeLabel(category: string, attribute: string, lang: SupportedLang = 'vi'): string {
  const attrDict = lang === 'en' ? ATTRIBUTE_LABEL_EN : ATTRIBUTE_LABEL_VI;
  return `${categoryLabel(category, lang)} · ${attrDict[attribute as Attribute] ?? attribute}`;
}

/**
 * `object:car` → "Xe con" (vi) / "Car" (en);
 * `rel:pedestrian:front_left` → "Người đi bộ · trước trái" (vi) / "Pedestrian · front-left" (en);
 * `scene:time=night` → "ban đêm" (vi) / "night" (en).
 */
export function satisfiedLabel(token: string, lang: SupportedLang = 'vi'): string {
  const parts = token.split(':');
  if (parts[0] === 'object' && parts.length === 2) {
    return categoryLabel(parts[1], lang);
  }
  if (parts[0] === 'rel' && parts.length === 3) {
    const relDict = lang === 'en' ? RELATION_LABEL_EN : RELATION_LABEL_VI;
    const relation = relDict[parts[2] as Relation] ?? parts[2];
    return `${categoryLabel(parts[1], lang)} · ${relation}`;
  }
  if (parts[0] === 'scene' && parts.length === 2) {
    const sceneDict = lang === 'en' ? SCENE_LABEL_EN : SCENE_LABEL_VI;
    return sceneDict[parts[1]] ?? parts[1];
  }
  return token;
}

/** Seconds into the clip as `m:ss.s`. `timestamp_s` is a float offset, not a wall-clock time. */
export function formatTimestamp(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds - minutes * 60;
  return `${minutes}:${rest.toFixed(1).padStart(4, '0')}`;
}

/** Short, stable label for a clip. Scene ids are 32 hex chars, which is unreadable in full. */
export function shortSceneId(sceneId: string): string {
  return sceneId.slice(0, 8);
}
