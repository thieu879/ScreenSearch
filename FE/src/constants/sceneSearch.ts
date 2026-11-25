import { CloudDrizzle, Shapes, PersonStanding } from 'lucide-react';
import type { FilterItem, FilterSectionDef } from '../types/sceneSearch';

/* ── Filter sections ─────────────────────────────────────────────────────────────────────────
 *
 * `actions` is disabled, not removed. Its options describe motion across time — an unprotected left
 * turn, an emergency stop, someone crossing — and retrieval works on single frames, so the backend
 * classifies every one of them as out of scope by design and explains rather than guessing.
 *
 * Leaving the checkboxes live would mean a third of the sidebar could only ever produce a refusal.
 * Showing them greyed out with the reason is more honest than hiding them: an engineer who wants
 * these queries learns why they are not available instead of assuming nobody thought of them.
 */
export const filterSections: FilterSectionDef[] = [
  { key: 'weather', title: 'THỜI TIẾT', icon: CloudDrizzle },
  { key: 'objects', title: 'LOẠI ĐỐI TƯỢNG', icon: Shapes },
  {
    key: 'actions',
    title: 'HÀNH ĐỘNG',
    icon: PersonStanding,
    disabled: true,
    disabledNote:
      'Tìm kiếm hoạt động trên từng khung hình riêng lẻ, nên không thể phát hiện chuyển động theo thời gian.',
  },
];

/* ── Initial filter values ───────────────────────────────────────────────────────────────────
 *
 * Ids are the contract with `lib/composeQuery.ts`, which maps them to the English noun phrases the
 * parser expects. Labels are display-only and safe to reword; ids are not.
 *
 * Nothing starts checked. The previous defaults (night + pedestrian + car) meant the first search
 * anyone ran was silently narrowed by filters they had not chosen.
 */
export const initialFilters: Record<string, FilterItem[]> = {
  weather: [
    { id: 'night', label: 'Hoạt động Đêm', checked: false },
    { id: 'rain', label: 'Trời mưa', checked: false },
    { id: 'sun', label: 'Nắng gắt', checked: false },
    { id: 'fog', label: 'Sương mù', checked: false },
    { id: 'snow', label: 'Băng tuyết', checked: false },
  ],
  objects: [
    { id: 'pedestrian', label: 'Người đi bộ', checked: false },
    { id: 'car', label: 'Xe con', checked: false },
    { id: 'bike', label: 'Xe đạp', checked: false },
    { id: 'truck', label: 'Xe tải/Xe buýt', checked: false },
    { id: 'moto', label: 'Mô tô', checked: false },
  ],
  actions: [
    { id: 'leftturn', label: 'Rẽ trái không ưu tiên', checked: false },
    { id: 'cross', label: 'Sang đường', checked: false },
    { id: 'brake', label: 'Phanh khẩn cấp', checked: false },
    { id: 'park', label: 'Đỗ xe trái phép', checked: false },
  ],
};

/* ── Example queries ─────────────────────────────────────────────────────────────────────────
 *
 * One per outcome the system can produce. They are offered as starting points because an empty
 * search box gives no hint that "nothing matches" and "out of scope" are answers this product
 * deliberately gives.
 *
 * **All four are corpus-dependent and must be re-verified when the corpus changes.** The hints
 * assert what the system will do, so a card whose hint has gone stale is the interface telling the
 * user something untrue — on the first click, before they have any reason to doubt it. Re-verified
 * against the served merged corpus 2026-08-29 (9,069 frames, v1.7.1):
 *
 *   a truck to the left                 high, 10 hits, 6 linked
 *   a pedestrian to the front-left      low, 10 hits — a real result the check cannot confirm
 *   a bus on fire                       matched false, 0 hits
 *   a motorcycle cutting into our lane  low, 10 hits, 5 linked, 1 with a moment clip
 *
 * **The fourth card used to be `a vehicle cutting into our lane`, hinted "ngoài phạm vi", and that
 * claim expired with Tier 1.** It was picked as the out-of-scope demo because the refusal was
 * parser-level and so the only corpus-independent card. On a corpus that has footage to point at,
 * the same query now returns ten answered results — the hint asserted a refusal the product no
 * longer gives. `a motorcycle` rather than `a vehicle` because `vehicle` is not one of the
 * detector's six categories, so it parses to `objects: []` and drops from 5 linked results to 1,
 * and from a moment clip to none — the card is there to show the clip.
 *
 * `a wet road at night` was the first card and is now removed. It scores 0.581 → *high* on this
 * corpus while returning tunnel frames with no wet road anywhere, and 0.773 → high on nuScenes for
 * the same reason (M2_DESIGN §10.6): the caption never contradicts "wet", it just never mentions it.
 * Leading the demo with a confident wrong answer sells the opposite of what the band is for.
 */
/* The hint is a translation key, not a string. It renders as the chip's tooltip on a page that can
   be English, and these were Vietnamese literals — the same class of defect #174 fixed for the
   vocabulary labels, in the one place a first-time visitor looks. Carried here from the closed #172
   because #174 does not touch this file.

   The queries themselves stay literal: they are sent to the parser, which reads English, and
   `models/schemas.py` documents why a query is never translated before it is embedded. */
export const EXAMPLE_QUERIES: { query: string; hintKey: string }[] = [
  { query: 'a truck to the left', hintKey: 'example_hint_confident' },
  { query: 'a pedestrian to the front-left', hintKey: 'example_hint_low_confidence' },
  { query: 'a bus on fire', hintKey: 'example_hint_no_results' },
  { query: 'a motorcycle cutting into our lane', hintKey: 'example_hint_source_clip' },
];
