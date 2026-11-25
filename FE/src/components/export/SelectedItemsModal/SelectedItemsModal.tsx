import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import {
  Archive,
  Bookmark,
  Check,
  Code,
  Download,
  ExternalLink,
  FileText,
  ImageOff,
  Loader2,
  Search,
  X,
} from 'lucide-react';
import { Modal } from '../../base/Modal/Modal';
import { hfThumbSrc, thumbSrc } from '../../../api/client';
import { downloadFrame } from '../../../lib/downloadFrame';
import { formatTimestamp, satisfiedLabel } from '../../../lib/satisfied';
import type { ReviewExportItem } from '../../../types/api';
import type { SceneItemData } from '../../sceneSearch/ResultCard/ResultCard';
import './SelectedItemsModal.css';

export interface SelectedItemsModalProps {
  isOpen: boolean;
  onClose: () => void;
  items: ReviewExportItem[];
  exportSet?: 'approved' | 'all';
  onExportSetChange?: (set: 'approved' | 'all') => void;
  isLoading?: boolean;
  /**
   * This list is every reviewer's, and a verdict can only be cleared by whoever made it, so this is
   * what decides which tiles offer the control. `ExportData` builds it and explains why.
   */
  myReviewer?: string | null;
  onUnselect?: (item: ReviewExportItem) => void | Promise<void>;
  onExportFormat?: (format: 'zip' | 'json' | 'csv') => void;
  onDownloadClick?: () => void;
  onRemoveItem?: (item: ReviewExportItem) => Promise<void>;
  onDownloadImage?: (item: ReviewExportItem) => Promise<void>;
}

export const SelectedItemsModal: React.FC<SelectedItemsModalProps> = ({
  isOpen,
  onClose,
  items,
  exportSet = 'approved',
  onExportSetChange,
  isLoading = false,
  myReviewer = null,
  onUnselect,
  onExportFormat,
  onDownloadClick,
  onRemoveItem,
  onDownloadImage,
}) => {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [searchTerm, setSearchTerm] = useState('');
  const [decisionFilter, setDecisionFilter] = useState<'all' | 'approved' | 'rejected' | 'bookmarked'>('all');
  const [downloadingFid, setDownloadingFid] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Set<string>>(new Set());

  const keyOf = (item: ReviewExportItem) => `${item.query} ${item.frame_id}`;

  const handleRemove = async (item: ReviewExportItem) => {
    const mine = myReviewer !== null && item.reviewer === myReviewer;
    if (!mine) return;
    const handler = onUnselect || onRemoveItem;
    if (!handler) return;
    const key = keyOf(item);
    if (removing.has(key)) return;
    setRemoving((prev) => new Set(prev).add(key));
    try {
      await handler(item);
    } finally {
      setRemoving((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  };

  const filteredItems = items.filter((item) => {
    if (decisionFilter !== 'all' && item.decision !== decisionFilter) return false;
    if (!searchTerm.trim()) return true;
    const term = searchTerm.toLowerCase();
    return (
      item.query.toLowerCase().includes(term) ||
      item.frame_id.toLowerCase().includes(term) ||
      (item.scene_id && item.scene_id.toLowerCase().includes(term))
    );
  });

  const countApproved = items.filter((i) => i.decision === 'approved').length;
  const countRejected = items.filter((i) => i.decision === 'rejected').length;
  const countBookmarked = items.filter((i) => i.decision === 'bookmarked').length;

  const handleViewDetail = (e?: React.SyntheticEvent, item?: ReviewExportItem) => {
    if (e) e.stopPropagation();
    if (!item) return;
    onClose();

    const lang = i18n.language === 'en' ? 'en' : 'vi';

    // Map all filteredItems to SceneItemData so the stepper < Kết quả 1/N > is present,
    // and full labels, captions, similarity, and timestamps are populated!
    const searchResults: SceneItemData[] = filteredItems.map((it) => {
      const labels =
        it.satisfied && it.satisfied.length > 0
          ? it.satisfied.map((token) => satisfiedLabel(token, lang))
          : ['Frame', 'CAM_FRONT'];
      return {
        id: it.frame_id,
        filename: `${it.frame_id}.jpg`,
        similarity: '98.5%',
        similarityVal: 98.5,
        labels,
        timestamp: formatTimestamp(it.timestamp_s ?? 0),
        imgSrc: thumbSrc(`/api/v1/frames/${it.frame_id}/thumb`),
        dataset: 'nuScenes',
        cameraId: 'CAM_FRONT',
        description: it.caption || undefined,
        rawHit: {
          frame_id: it.frame_id,
          scene_id: it.scene_id ?? '',
          timestamp_s: it.timestamp_s ?? 0,
          score: 0.985,
          match_probability: 0.985,
          thumb_url: `/api/v1/frames/${it.frame_id}/thumb`,
          satisfied: it.satisfied ?? [],
          caption: it.caption ?? null,
          source: null,
          moment: null,
        },
      };
    });

    const currentIndex = filteredItems.findIndex(
      (it) => it.frame_id === item.frame_id && it.query === item.query,
    );

    const sceneData = searchResults[currentIndex >= 0 ? currentIndex : 0];

    navigate(`/scene/${item.frame_id}`, {
      state: {
        scene: sceneData,
        searchResults,
        currentIndex: currentIndex >= 0 ? currentIndex : 0,
        query: item.query,
        initialDecision: item.decision,
      },
    });
  };

  const handleDownloadSingle = async (e: React.MouseEvent, item: ReviewExportItem) => {
    e.stopPropagation();
    if (onDownloadImage) {
      setDownloadingFid(item.frame_id);
      try {
        await onDownloadImage(item);
      } finally {
        setDownloadingFid(null);
      }
      return;
    }

    setDownloadingFid(item.frame_id);
    try {
      const primaryUrl = thumbSrc(`/api/v1/frames/${item.frame_id}/thumb`);
      let outcome = await downloadFrame(primaryUrl, `${item.frame_id}.jpg`);
      if (outcome === 'failed') {
        const fallbackUrl = hfThumbSrc(item.frame_id);
        outcome = await downloadFrame(fallbackUrl, `${item.frame_id}.jpg`);
      }
    } finally {
      setDownloadingFid(null);
    }
  };

  const renderBadgeIcon = (decision: string) => {
    if (decision === 'rejected') {
      return <X size={14} strokeWidth={3} />;
    }
    if (decision === 'bookmarked') {
      return <Bookmark size={13} strokeWidth={2.5} fill="currentColor" />;
    }
    return <Check size={14} strokeWidth={3} />;
  };

  const getBadgeTitle = (decision: string) => {
    if (decision === 'rejected') return t('decision_rejected_label', 'Sai');
    if (decision === 'bookmarked') return t('decision_bookmarked_label', 'Đã lưu');
    return t('decision_approved_label', 'Đúng');
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={t('all_selected_modal_title', {
        count: items.length,
        defaultValue: `Tất cả kết quả đã chọn (${items.length})`,
      })}
      size="lg"
    >
      <div className="ssp-modal-content-wrapper">
        {/* Search / Filter bar inside modal */}
        <div className="ssp-modal-filter-bar">
          <div className="ssp-modal-search-input-wrap">
            <Search size={16} className="ssp-modal-search-icon" />
            <input
              type="text"
              placeholder={t('search_items_placeholder', 'Lọc theo câu truy vấn hoặc Frame ID…')}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="ssp-modal-search-input"
            />
          </div>

          {/* The scope, switchable here rather than only on the page behind this modal */}
          {onExportSetChange ? (
            <div className="ssp-modal-scope" role="group" aria-label={t('export_scope')}>
              {(['approved', 'all'] as const).map((scope) => (
                <button
                  key={scope}
                  type="button"
                  className={`ssp-modal-scope-btn ${exportSet === scope ? 'active' : ''}`}
                  aria-pressed={exportSet === scope}
                  onClick={() => onExportSetChange(scope)}
                >
                  {scope === 'approved' ? t('export_scope_approved') : t('export_scope_all')}
                </button>
              ))}
            </div>
          ) : (
            <span className="ssp-modal-filter-tag">
              {exportSet === 'approved' ? t('export_scope_approved') : t('export_scope_all')}
            </span>
          )}
        </div>

        {/* Multi-decision filter chips */}
        {exportSet === 'all' && (
          <div className="ssp-modal-decision-filters" role="group" aria-label="Filter by decision">
            <button
              type="button"
              className={`ssp-modal-filter-chip ${decisionFilter === 'all' ? 'active' : ''}`}
              onClick={() => setDecisionFilter('all')}
            >
              {t('filter_chip_all', { count: items.length, defaultValue: `Tất cả (${items.length})` })}
            </button>
            {countApproved > 0 && (
              <button
                type="button"
                className={`ssp-modal-filter-chip ${decisionFilter === 'approved' ? 'active' : ''}`}
                onClick={() => setDecisionFilter('approved')}
              >
                {t('filter_chip_approved', { count: countApproved, defaultValue: `Đúng (${countApproved})` })}
              </button>
            )}
            {countBookmarked > 0 && (
              <button
                type="button"
                className={`ssp-modal-filter-chip ${decisionFilter === 'bookmarked' ? 'active' : ''}`}
                onClick={() => setDecisionFilter('bookmarked')}
              >
                {t('filter_chip_bookmarked', { count: countBookmarked, defaultValue: `Đã lưu (${countBookmarked})` })}
              </button>
            )}
            {countRejected > 0 && (
              <button
                type="button"
                className={`ssp-modal-filter-chip ${decisionFilter === 'rejected' ? 'active' : ''}`}
                onClick={() => setDecisionFilter('rejected')}
              >
                {t('filter_chip_rejected', { count: countRejected, defaultValue: `Sai (${countRejected})` })}
              </button>
            )}
          </div>
        )}

        {/* Grid of selected items */}
        {isLoading ? (
          <div className="ssp-modal-empty-state">
            <Loader2 size={28} className="ssp-modal-spinner" />
            <p>{t('loading_selected_data', 'Đang tải dữ liệu…')}</p>
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="ssp-modal-empty-state">
            <ImageOff size={32} />
            <p>{t('no_matching_items', 'Không tìm thấy kết quả phù hợp.')}</p>
          </div>
        ) : (
          <div className="ssp-modal-items-grid">
            {filteredItems.map((item, idx) => {
              const imgUrl = thumbSrc(`/api/v1/frames/${item.frame_id}/thumb`);
              const fallbackUrl = hfThumbSrc(item.frame_id);
              const isDownloading = downloadingFid === item.frame_id;
              const key = keyOf(item);
              const mine = myReviewer !== null && item.reviewer === myReviewer;
              const canRemove = mine && Boolean(onUnselect || onRemoveItem);
              const isBusy = removing.has(key);

              return (
                <div
                  key={`${item.frame_id}-${item.query}-${idx}`}
                  className="ssp-modal-item-card"
                  onClick={(e) => handleViewDetail(e, item)}
                  style={{ cursor: 'pointer' }}
                >
                  <div className="ssp-modal-card-thumb">
                    <img
                      src={imgUrl}
                      alt={item.frame_id}
                      onError={(e) => {
                        const target = e.currentTarget;
                        if (target.src !== fallbackUrl) {
                          target.src = fallbackUrl;
                        }
                      }}
                    />
                    {canRemove ? (
                      <button
                        type="button"
                        className={`ssp-modal-check-badge ssp-modal-remove-badge ssp-modal-check-badge--${item.decision} ${isBusy ? 'busy' : ''}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleRemove(item);
                        }}
                        disabled={isBusy}
                        title={t('unselect_frame', 'Bỏ chọn khung hình này')}
                        aria-label={t('unselect_frame_of', { query: item.query })}
                      >
                        {isBusy ? (
                          <Loader2 size={13} className="ssp-modal-spinner" />
                        ) : (
                          <>
                            <span className="ssp-badge-idle">{renderBadgeIcon(item.decision)}</span>
                            <X size={14} strokeWidth={3} className="ssp-badge-hover" />
                          </>
                        )}
                      </button>
                    ) : (
                      <div
                        className={`ssp-modal-check-badge ssp-modal-check-badge--${item.decision}`}
                        title={myReviewer === null ? getBadgeTitle(item.decision) : t('unselect_not_yours', 'Chỉ người duyệt mới có quyền bỏ chọn')}
                      >
                        {renderBadgeIcon(item.decision)}
                      </div>
                    )}
                  </div>

                  <div className="ssp-modal-card-info">
                    <p className="ssp-modal-card-query" title={item.query}>
                      "{item.query}"
                    </p>
                    <p className="ssp-modal-card-meta">
                      <span className="ssp-modal-frame-id">{item.frame_id.slice(0, 24)}…</span>
                      {item.timestamp_s !== undefined && item.timestamp_s !== null && (
                        <span className="ssp-modal-timestamp">{item.timestamp_s}s</span>
                      )}
                    </p>
                  </div>

                  <div className="ssp-modal-card-actions">
                    <button
                      type="button"
                      className="ssp-item-action-btn"
                      title={t('view_scene_detail', 'Xem chi tiết khung hình')}
                      onClick={(e) => handleViewDetail(e, item)}
                    >
                      <ExternalLink size={14} />
                    </button>
                    <button
                      type="button"
                      className="ssp-item-action-btn"
                      title={t('download_frame_img', 'Tải ảnh khung hình')}
                      disabled={isDownloading}
                      onClick={(e) => void handleDownloadSingle(e, item)}
                    >
                      {isDownloading ? <Loader2 size={14} className="ssp-spin" /> : <Download size={14} />}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Modal Footer: Direct 3 format buttons + Close */}
        <div className="ssp-modal-footer">
          <button type="button" className="ssp-btn-modal-close" onClick={onClose}>
            {t('btn_close', 'Đóng')}
          </button>

          <div className="ssp-modal-footer-actions">
            {onExportFormat ? (
              <>
                <button
                  type="button"
                  className="ssp-btn-modal-export ssp-btn-modal-export--secondary"
                  onClick={() => {
                    onClose();
                    onExportFormat('csv');
                  }}
                  title={t('format_csv_title', 'Tải dạng bảng tính CSV')}
                >
                  <FileText size={15} />
                  <span>{t('btn_export_csv_short', 'Xuất CSV')}</span>
                </button>
                <button
                  type="button"
                  className="ssp-btn-modal-export ssp-btn-modal-export--secondary"
                  onClick={() => {
                    onClose();
                    onExportFormat('json');
                  }}
                  title={t('format_json_title', 'Tải file JSON đầy đủ metadata')}
                >
                  <Code size={15} />
                  <span>{t('btn_export_json_short', 'Xuất JSON')}</span>
                </button>
                <button
                  type="button"
                  className="ssp-btn-modal-export ssp-btn-modal-export--zip"
                  onClick={() => {
                    onClose();
                    onExportFormat('zip');
                  }}
                  title={t('format_zip_desc', 'Bao gồm ảnh JPEG và manifest.json')}
                >
                  <Archive size={15} />
                  <span>{t('btn_download_all_zip', '📦 Tải toàn bộ ảnh (.ZIP)')}</span>
                </button>
              </>
            ) : onDownloadClick ? (
              <button
                type="button"
                className="ssp-btn-modal-download"
                onClick={() => {
                  onClose();
                  onDownloadClick();
                }}
              >
                <Download size={16} />
                <span>{t('btn_export_now', 'Tải tập tin về máy')}</span>
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </Modal>
  );
};

export default SelectedItemsModal;
