import React from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, Bookmark, Check, ImageOff, Loader2, Maximize2, X } from 'lucide-react';
import { hfThumbSrc, thumbSrc } from '../../../api/client';
import type { ReviewExportItem } from '../../../types/api';
import './SelectedResultsPreview.css';

export interface SelectedResultsPreviewProps {
  items: ReviewExportItem[];
  totalCount: number;
  approvedCount?: number;
  allCount?: number;
  exportSet?: 'approved' | 'all';
  onExportSetChange?: (set: 'approved' | 'all') => void;
  isLoading: boolean;
  /** The list could not be read. Distinct from an empty list — see the render below. */
  hasError: boolean;
  onOpenModal: () => void;
  /** Whose set this is, already translated — the badge states it so a count is never unqualified. */
  whose: string;
}

export const SelectedResultsPreview: React.FC<SelectedResultsPreviewProps> = ({
  items,
  totalCount,
  approvedCount,
  allCount,
  exportSet = 'approved',
  onExportSetChange,
  isLoading,
  hasError,
  onOpenModal,
  whose,
}) => {
  const { t } = useTranslation();

  // Show up to 4 items in the preview row
  const previewItems = items.slice(0, 4);
  const overflowCount = totalCount > 4 ? totalCount - 4 : items.length > 4 ? items.length - 4 : 0;

  const renderBadge = (decision: string) => {
    if (decision === 'rejected') {
      return (
        <div className="ssp-preview-status-badge ssp-preview-status-badge--rejected" title={t('decision_rejected_label', 'Sai')}>
          <X size={14} strokeWidth={3} />
        </div>
      );
    }
    if (decision === 'bookmarked') {
      return (
        <div className="ssp-preview-status-badge ssp-preview-status-badge--bookmarked" title={t('decision_bookmarked_label', 'Đã lưu')}>
          <Bookmark size={13} strokeWidth={2.5} fill="currentColor" />
        </div>
      );
    }
    return (
      <div className="ssp-preview-status-badge ssp-preview-status-badge--approved" title={t('decision_approved_label', 'Đúng')}>
        <Check size={14} strokeWidth={3} />
      </div>
    );
  };

  return (
    <section className="ssp-card ssp-selected-card">
      <div className="ssp-selected-card-header">
        <div className="ssp-selected-header-left">
          <h3 className="ssp-card-title">
            {exportSet === 'all'
              ? t('selected_results_title_all', 'Toàn bộ dữ liệu đã đánh giá (Đúng / Sai / Đã lưu)')
              : t('selected_results_title_approved', 'Bộ dữ liệu đã duyệt (Đúng)')}
          </h3>
        </div>

        <div className="ssp-selected-header-actions">
          {onExportSetChange && (
            <div className="ssp-selected-scope-tabs" role="tablist" aria-label="Export scope">
              <button
                type="button"
                role="tab"
                aria-selected={exportSet === 'approved'}
                className={`ssp-selected-scope-tab ${exportSet === 'approved' ? 'active' : ''}`}
                onClick={() => onExportSetChange('approved')}
              >
                {t('selected_scope_tab_approved', { count: approvedCount ?? 0, defaultValue: `Chỉ Đúng (${approvedCount ?? 0})` })}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={exportSet === 'all'}
                className={`ssp-selected-scope-tab ${exportSet === 'all' ? 'active' : ''}`}
                onClick={() => onExportSetChange('all')}
              >
                {t('selected_scope_tab_all', { count: allCount ?? totalCount, defaultValue: `Tất cả (${allCount ?? totalCount})` })}
              </button>
            </div>
          )}

          {/* The badge opens the list too. It reads as the way in — it is the only thing in this
              header that names a count — and it was inert, so clicking it did nothing and the actual
              way in was to click a thumbnail, which looks like it would open that one frame. */}
          <button
            type="button"
            className="ssp-selected-count-badge ssp-selected-count-badge--action"
            onClick={onOpenModal}
            disabled={totalCount === 0 || items.length === 0}
            title={t('view_all_selected')}
          >
            <Maximize2 size={13} className="ssp-selected-badge-icon" />
            <span>{t('selected_results_count', { count: totalCount, whose })}</span>
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="ssp-selected-notice">
          <Loader2 size={18} className="ssp-spin" />
          <span>{t('loading_selected_data', 'Đang tải danh sách kết quả đã chọn…')}</span>
        </div>
      ) : hasError ? (
        // Before the empty state, never folded into it: "we could not read your list" and "your list
        // is empty" are different facts, and only one of them is the user's to act on.
        <div className="ssp-selected-notice ssp-selected-notice--error">
          <AlertCircle size={18} />
          <span>{t('selected_items_load_failed', 'Không tải được danh sách. Hãy thử tải lại trang.')}</span>
        </div>
      ) : totalCount === 0 || items.length === 0 ? (
        <div className="ssp-selected-empty">
          <ImageOff size={24} />
          <span>{t('no_selected_items_hint', 'Chưa có khung hình nào trong danh mục này.')}</span>
        </div>
      ) : (
        <div className="ssp-selected-grid-row">
          {previewItems.map((item, idx) => {
            const imgUrl = thumbSrc(`/api/v1/frames/${item.frame_id}/thumb`);
            const hfUrl = hfThumbSrc(item.frame_id);
            return (
              <div
                key={`${item.frame_id}-${idx}`}
                className="ssp-preview-tile"
                onClick={onOpenModal}
                title={`${item.query} — ${item.frame_id}`}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onOpenModal()}
              >
                <img
                  src={imgUrl}
                  alt={item.frame_id}
                  onError={(e) => {
                    const target = e.currentTarget;
                    if (target.src !== hfUrl) {
                      target.src = hfUrl;
                    } else {
                      target.style.display = 'none';
                    }
                  }}
                />
                <div className="ssp-preview-check-overlay">
                  {renderBadge(item.decision)}
                </div>
              </div>
            );
          })}

          {overflowCount > 0 && (
            <div
              className="ssp-preview-tile ssp-preview-tile-more"
              onClick={onOpenModal}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onOpenModal()}
              title={t('view_all_selected', 'Xem toàn bộ danh sách khung hình')}
            >
              <span className="ssp-more-number">+{overflowCount}</span>
              <span className="ssp-more-label">ITEMS</span>
            </div>
          )}
        </div>
      )}
    </section>
  );
};

export default SelectedResultsPreview;
