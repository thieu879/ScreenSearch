import React from 'react';
import { useTranslation } from 'react-i18next';
import { Bookmark, Check, X } from 'lucide-react';

import type { Decision } from '../../../types/api';
import './ReviewActions.css';

interface ReviewActionsProps {
  decision: Decision | undefined;
  onDecide: (decision: Decision) => void;
  /** `card` is the compact row on a result; `detail` is the larger row in the modal. */
  size?: 'card' | 'detail';
}

export const ReviewActions: React.FC<ReviewActionsProps> = ({ decision, onDecide, size = 'card' }) => {
  const { t } = useTranslation();

  const buttons: { value: Decision; icon: React.ReactNode; label: string; title: string }[] = [
    { value: 'approved', icon: <Check size={16} />, label: t('btn_approved_label'), title: t('btn_approved_title') },
    { value: 'rejected', icon: <X size={16} />, label: t('btn_rejected_label'), title: t('btn_rejected_title') },
    { value: 'bookmarked', icon: <Bookmark size={16} />, label: t('btn_bookmarked_label'), title: t('btn_bookmarked_title') },
  ];

  return (
    <div className={`review-actions review-actions--${size}`} role="group" aria-label="Evaluate frame">
      {buttons.map(({ value, icon, label, title }) => {
        const active = decision === value;
        return (
          <button
            key={value}
            type="button"
            className={`review-actions__btn review-actions__btn--${value} ${
              active ? 'review-actions__btn--active' : ''
            }`}
            aria-pressed={active}
            title={active ? `${title} ${t('toggle_undo')}` : title}
            onClick={(event) => {
              event.stopPropagation();
              onDecide(value);
            }}
          >
            {icon}
            <span className="review-actions__label">{label}</span>
          </button>
        );
      })}
    </div>
  );
};

export default ReviewActions;
