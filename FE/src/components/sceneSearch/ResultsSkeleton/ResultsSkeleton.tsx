import React from 'react';
import { useTranslation } from 'react-i18next';

import './ResultsSkeleton.css';

/**
 * What the results area shows while a search is in flight.
 *
 * **It used to show nothing.** `idle` rendered `StartState`, `done` rendered the grid, `error`
 * rendered a notice — and `loading` fell through every branch, so the whole canvas went empty for
 * the length of a search. That is not a flicker: a search is ~1s, and longer on a cold parse,
 * because the query goes through two `gpt-4o-mini` calls before retrieval starts. The only signal
 * anything was happening was the spinner inside the search button, at the top of the page, which is
 * where the eye is *not* once the query has been submitted.
 *
 * The shape matches `ResultCard` — thumbnail block, two chips, a title line, a meta line — so the
 * real results replace it in place rather than shifting the page. Count matches the requested page
 * size for the same reason.
 *
 * `aria-busy` with a live region rather than only a visual: a screen reader otherwise gets silence
 * between submitting and the results landing, which is the same defect in another medium.
 */
export const ResultsSkeleton: React.FC<{ count?: number }> = ({ count = 10 }) => {
  const { t } = useTranslation();

  return (
    <section
      className="ssp-results-grid ssp-results-skeleton"
      aria-busy="true"
      aria-live="polite"
      aria-label={t('search_searching')}
    >
      {Array.from({ length: count }, (_, i) => (
        // Staggered so the grid reads as one surface filling in rather than ten separate pulses.
        <div className="ssp-skeleton-card" key={i} style={{ animationDelay: `${(i % 5) * 90}ms` }}>
          <div className="ssp-skeleton-thumb" />
          <div className="ssp-skeleton-body">
            <div className="ssp-skeleton-chips">
              <span className="ssp-skeleton-chip" />
              <span className="ssp-skeleton-chip ssp-skeleton-chip--wide" />
            </div>
            <div className="ssp-skeleton-line ssp-skeleton-line--title" />
            <div className="ssp-skeleton-line ssp-skeleton-line--meta" />
          </div>
        </div>
      ))}
    </section>
  );
};
