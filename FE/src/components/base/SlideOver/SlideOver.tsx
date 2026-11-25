import React, { useEffect, useCallback } from 'react';
import { X } from 'lucide-react';
import './SlideOver.css';
import { useTranslation } from 'react-i18next';

export interface SlideOverProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  headerAction?: React.ReactNode;
  width?: string;
}

export const SlideOver: React.FC<SlideOverProps> = ({
  isOpen,
  onClose,
  title,
  children,
  headerAction,
  width = '600px',
}) => {
  const { t } = useTranslation();
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    },
    [onClose]
  );

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [isOpen, handleKeyDown]);

  return (
    <>
      <div
        className={`slide-over-overlay ${isOpen ? 'slide-over-overlay--visible' : ''}`}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        className={`slide-over-panel ${isOpen ? 'slide-over-panel--visible' : ''}`}
        style={{ maxWidth: width }}
        role="dialog"
        aria-modal="true"
        aria-label={title || 'Detail Panel'}
      >
        <header className="slide-over-header">
          <div className="slide-over-header-left">
            <button
              className="slide-over-close-btn"
              onClick={onClose}
              aria-label={t('a11y_close_panel')}
              type="button"
            >
              <X size={20} />
            </button>
            {title && <h3 className="slide-over-title">{title}</h3>}
          </div>
          {headerAction && <div className="slide-over-header-right">{headerAction}</div>}
        </header>

        <div className="slide-over-body">{children}</div>
      </aside>
    </>
  );
};

export default SlideOver;
