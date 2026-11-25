import type { LucideIcon } from 'lucide-react';

/* ── Filter ─────────────────────────────────────────────── */
export interface FilterItem {
  id: string;
  label: string;
  checked: boolean;
}

export interface FilterSectionDef {
  key: string;
  title: string;
  icon: LucideIcon;
  /** Rendered but not interactive — see the `actions` section in `constants/sceneSearch.ts`. */
  disabled?: boolean;
  /** Shown in place of the controls, so a disabled section explains itself. */
  disabledNote?: string;
}

/* Result shapes come from the API and live in `types/api.ts` — `FrameHit` and `SearchResponse`.
 *
 * The old `ResultItem` was the mockup's shape (title, image, match, overlayBadges, camLabel,
 * severity, description) and shared not one field with what the server actually returns. Adapting
 * between them would have meant carrying fields with no source and inventing values for them,
 * which is how "98.4% Độ khớp" ended up on every card in the first place. */
