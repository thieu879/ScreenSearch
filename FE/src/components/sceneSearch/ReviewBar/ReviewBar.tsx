import React from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Download, X } from 'lucide-react';

import { exportUrl } from '../../../api/client';
import { useAuth } from '../../../contexts/AuthContext';
import type { ReviewSummary } from '../../../types/api';
import './ReviewBar.css';

interface ReviewBarProps {
  summary: ReviewSummary;
  /** Judged frames among the results currently on screen, out of how many are shown. */
  judgedHere: number;
  shownHere: number;
}

export const ReviewBar: React.FC<ReviewBarProps> = ({ summary, judgedHere, shownHere }) => {
  const { t } = useTranslation();
  // The export needs an account, not a role (`src/api/security.py`) — it is the engineer's own
  // work product, so any signed-in user may take it. Hidden rather than disabled for a
  // pseudonymous tester: they are not a failed operator, and a greyed control invites a click that
  // can only ever be refused.
  const { user } = useAuth();
  const canExport = user !== null;

  return (
    <div className="review-bar">
      <div className="review-bar__counts">
        <span className="review-bar__here">
          {t('judged_here', { judgedHere, shownHere })}
        </span>
        <span className="review-bar__totals" title="Summary across all evaluated queries">
          <span className="review-bar__stat review-bar__stat--approved">
            <Check size={14} aria-hidden="true" />
            {t('stat_approved', { approved: summary.approved })}
          </span>
          <span className="review-bar__stat review-bar__stat--rejected">
            <X size={14} aria-hidden="true" />
            {t('stat_rejected', { rejected: summary.rejected })}
          </span>
          <span
            className="review-bar__stat"
            title={t('queries_count_tooltip', { count: summary.queries_reviewed })}
          >
            {t('queries_count', { count: summary.queries_reviewed })}
          </span>
        </span>
      </div>

      {canExport && (
        <div className="review-bar__actions">
          <a
            className="review-bar__export review-bar__export--primary"
            href={exportUrl('json', 'approved')}
            download
            aria-disabled={summary.approved === 0}
            onClick={(event) => summary.approved === 0 && event.preventDefault()}
            title={
              summary.approved === 0
                ? t('export_json_disabled')
                : t('export_json_title')
            }
          >
            <Download size={15} aria-hidden="true" />
            {t('export_json_btn', { count: summary.approved })}
          </a>
          <a
            className="review-bar__export"
            href={exportUrl('csv', 'all')}
            download
            aria-disabled={summary.total === 0}
            onClick={(event) => summary.total === 0 && event.preventDefault()}
            title={t('export_csv_all_title')}
          >
            {t('export_csv_all_btn')}
          </a>
        </div>
      )}
    </div>
  );
};

export default ReviewBar;
