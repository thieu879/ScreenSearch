/**
 * Download the reviewed set.
 *
 * This page was a mockup until 2026-08-07, and the most misleading kind: the export button worked.
 * It produced a file, named it after the dataset, and reported "~15.4 MB" — but the file contained
 * one line of `dataset_name,format,items_count` and none of the reviewer's verdicts. A tester who
 * clicked it would have believed their session was saved to disk.
 *
 * Everything shown here now comes from `/api/v1/reviews/summary`, and the button is a link to
 * `/api/v1/reviews/export` — the same endpoint `ReviewBar` uses, so the two cannot disagree.
 *
 * Deleted, because there was nothing behind any of it: twenty-four preview tiles built from four
 * stock photographs on `lh3.googleusercontent.com`; an estimated size and a `1920 x 1080` frame
 * resolution (thumbnails are 640px); `Engineer 01 (You)` and a fixed 2024 timestamp; two "export
 * processing nodes" with live-looking load bars; a REST API documentation tab with no document
 * behind it; and a footer promising Cloud archival, AES-256 encryption and an audit log, none of
 * which this system does. A claim about security that is decorative is worse than no claim.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, Archive, Code, Download, FileText, Loader2 } from 'lucide-react';

import { Sidebar } from '../../components/layout/Sidebar/Sidebar';
import { TopBar } from '../../components/layout/TopBar/TopBar';
import { useToast } from '../../components/base/Toast/useToast';
import { ToastContainer } from '../../components/base/Toast/Toast';
import {
  clearReview,
  exportUrl,
  fetchReviewExport,
  fetchReviewSummary,
  fetchReviewSummaryAll,
  thumbSrc,
  type ExportScope,
} from '../../api/client';
import { downloadFrame } from '../../lib/downloadFrame';
import { useAuth } from '../../contexts/AuthContext';
import type { ReviewExportItem, ReviewSummary } from '../../types/api';
import { SelectedResultsPreview } from '../../components/export/SelectedResultsPreview/SelectedResultsPreview';
import { SelectedItemsModal } from '../../components/export/SelectedItemsModal/SelectedItemsModal';

import './ExportData.css';

type ExportFormat = 'csv' | 'json' | 'zip';
type ExportSet = 'approved' | 'all';

export const ExportData: React.FC = () => {
  const { t } = useTranslation();
  const { messages, addToast, dismiss } = useToast();

  const [summary, setSummary] = useState<ReviewSummary | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [exportFormat, setExportFormat] = useState<ExportFormat>('json');
  const [exportSet, setExportSet] = useState<ExportSet>('approved');
  /**
   * Whose verdicts this page is showing and would download.
   *
   * `all` by default because that is what the page has meant since PR #173 and what the graded
   * dataset is — and because on this corpus every verdict predates account attribution, so `mine`
   * is legitimately empty for everyone right now. A default that showed nothing would read as a
   * broken page rather than an honest one.
   */
  const [scope, setScope] = useState<ExportScope>('all');
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  const [exportItems, setExportItems] = useState<ReviewExportItem[]>([]);
  const [itemsLoading, setItemsLoading] = useState<boolean>(true);
  const [itemsError, setItemsError] = useState<boolean>(false);
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);

  useEffect(() => {
    let cancelled = false;
    // **Follows `scope`, and that is the whole invariant of this page.** These two once disagreed —
    // the badge counted this browser's rows while the download carried everyone's — so the summary
    // and the export are now driven by one control and fetched from the matching endpoint.
    // `fetchReviewSummary` sends this account's identity; the unscoped one totals the table.
    const load = scope === 'mine' ? fetchReviewSummary : fetchReviewSummaryAll;
    load()
      .then((value) => !cancelled && setSummary(value))
      .catch(() => !cancelled && setLoadError(true));
    return () => {
      cancelled = true;
    };
  }, [scope]);

  // Two handlers rather than one `.finally`, and the distinction is the whole point: `finally` clears
  // the spinner on a rejection too, leaving an empty list that the preview renders as its *empty*
  // state — "no results selected yet, go and select some from the search page". A 401 or a 500 then
  // reads as an instruction to redo work that is already done. A failed load has to look like a
  // failed load. (Neither call is in the effect body, so `react-hooks/set-state-in-effect` is happy;
  // it was the synchronous `setItemsLoading(true)` that the rule objected to, and that lives in
  // `handleExportSetChange` below.)
  useEffect(() => {
    let cancelled = false;
    fetchReviewExport(exportSet, scope)
      .then((res) => {
        if (!cancelled) {
          setExportItems(res.decisions);
          setItemsLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setExportItems([]);
          setItemsError(true);
          setItemsLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [exportSet, scope]);

  const handleExportSetChange = (set: ExportSet) => {
    if (set !== exportSet) {
      setExportSet(set);
      setItemsLoading(true);
      setItemsError(false);
    }
  };

  // How many rows the chosen selection will actually contain, so the button cannot offer a download
  // that comes back empty.
  const rowCount = summary === null ? 0 : exportSet === 'approved' ? summary.approved : summary.total;

  // The export needs an account, not a role (`src/api/security.py`). Checked here so a click by a
  // signed-out visitor produces an explanation rather than navigating the page to a JSON 401.
  const { user } = useAuth();
  const isOperator = user !== null;

  /**
   * How this account's own verdicts are attributed, so the list can tell them from everyone else's.
   *
   * At `scope=all` the list is every reviewer's, while `DELETE /reviews` resolves its reviewer from
   * the session. Those two facts together mean a remove button offered on somebody else's row would
   * return 204 and change nothing: the endpoint would faithfully delete this account's verdict on
   * that frame, of which there is none. Rather than let the UI appear to do something it cannot,
   * rows that are not this account's are shown without the control. At `scope=mine` every row
   * matches, so every row has one — which is the point of that scope.
   *
   * Matches `services/reviews.py:reviewer_identity`. Verdicts recorded before 2026-08-30 carry a
   * browser id instead and therefore never match — correct, because nothing can prove whose they
   * were, and guessing is how one person ends up deleting another's work.
   */
  const myReviewer = user === null ? null : `user:${user.user_id}`;

  /**
   * Clear one of this account's verdicts from inside the export view.
   *
   * Before this, un-approving a frame meant going back to search, re-running the query that
   * produced it, finding the card and clicking the tick again — the reviewed set was assembled here
   * and editable only somewhere else.
   *
   * Optimistic with rollback, like `useReviews`: the tile goes on click, and comes back if the
   * server refused. The summary is then re-read rather than decremented locally, because it is what
   * the download button's row count is built from and a drifting count is the defect this page
   * already had once.
   */
  const handleUnselect = useCallback(
    async (item: ReviewExportItem) => {
      const previous = exportItems;
      setExportItems((rows) => rows.filter((r) => !(r.frame_id === item.frame_id && r.query === item.query)));
      try {
        await clearReview(item.query, item.frame_id);
        const refreshed = await fetchReviewSummaryAll();
        setSummary(refreshed);
        addToast('success', t('remove_from_reviewed', 'Bỏ chọn'), t('item_removed_success', 'Đã xóa khung hình khỏi tập duyệt.'));
      } catch {
        setExportItems(previous);
        addToast('error', t('unselect_failed_title'), t('unselect_failed_desc'));
      }
    },
    [exportItems, addToast, t],
  );

  const handleExportClick = useCallback(
    (event: React.MouseEvent) => {
      if (!isOperator) {
        event.preventDefault();
        addToast(
          'warning',
          t('export_login_title'),
          t('export_login_desc'),
        );
        return;
      }
      if (rowCount === 0) {
        event.preventDefault();
        addToast(
          'warning',
          t('export_empty_title'),
          t('export_empty_desc'),
        );
        return;
      }
      addToast('success', t('export_downloading'), t('export_downloading_desc', { rows: rowCount, format: exportFormat.toUpperCase() }));
    },
    [isOperator, rowCount, exportFormat, addToast, t],
  );

  const handleExportByFormat = useCallback(
    (format: ExportFormat) => {
      if (!isOperator) {
        addToast(
          'error',
          t('operator_notice', 'Bản xuất chỉ dành cho người điều phối buổi thử. Đánh giá của bạn vẫn được lưu bình thường.'),
        );
        return;
      }
      if (rowCount === 0) {
        addToast(
          'warning',
          t('btn_export_no_data', 'Chưa có dữ liệu để xuất'),
          'Hãy đánh giá ít nhất một khung hình trong trang tìm kiếm trước khi xuất.',
        );
        return;
      }
      const url = exportUrl(format, exportSet, scope);
      const a = document.createElement('a');
      a.href = url;
      a.download = '';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      addToast(
        'success',
        format === 'zip'
          ? t('export_zip_success', 'Đang tải xuống tệp nén ZIP chứa toàn bộ hình ảnh.')
          : t('export_success_notice', 'Đang tải xuống tệp dữ liệu.'),
      );
    },
    [isOperator, rowCount, exportSet, scope, addToast, t],
  );

  const handleDownloadImage = useCallback(
    async (item: ReviewExportItem) => {
      const imgUrl = thumbSrc(`/api/v1/frames/${item.frame_id}/thumb`);
      const outcome = await downloadFrame(imgUrl, `${item.frame_id}.jpg`);
      if (outcome === 'failed') {
        addToast('error', t('download_frame_img', 'Tải ảnh'), 'Không thể tải ảnh. Vui lòng thử lại.');
      } else {
        addToast('success', t('download_frame_img', 'Tải ảnh'), `${item.frame_id}.jpg`);
      }
    },
    [addToast, t],
  );

  return (
    <div className="ssp-app-layout">
      <Sidebar
        activeTab="export"
        isOpen={isMobileMenuOpen}
        onClose={() => setIsMobileMenuOpen(false)}
      />

      <div className="ssp-main-wrapper">
        <TopBar
          pageTitle={t('export_page_title')}
          onToggleMenu={() => setIsMobileMenuOpen((prev) => !prev)}
        />

        <main className="ssp-content-container">
          <div className="ssp-export-grid">
            <div className="ssp-column">
              {/* What is actually in the store */}
              <section className="ssp-card">
                <div className="ssp-card-header">
                  <h3 className="ssp-card-title">{t('stat_total_evaluated')}</h3>
                  {/* Say whose these are, always. The Reviewed Set card below has carried an
                      "all reviewers" badge for a while; these four tiles carried none, so on a
                      newly registered account they read as *your* 61 evaluated frames and land as
                      a bug report. One number qualified and the next one not is worse than
                      neither being qualified. */}
                  <span
                    className="ssp-count-badge"
                    title={summary !== null ? t('queries_count_tooltip', { count: summary.queries_reviewed }) : undefined}
                  >
                    {scope === 'mine' ? t('export_count_mine') : t('export_count_all')}
                    {summary !== null && ` ${t('queries_count', { count: summary.queries_reviewed })}`}
                  </span>
                </div>

                {loadError ? (
                  <div className="ssp-export-notice">
                    <AlertCircle size={18} />
                    <span>{t('stat_load_error')}</span>
                  </div>
                ) : summary === null ? (
                  <div className="ssp-export-notice">
                    <Loader2 size={18} className="ssp-spin" />
                    <span>{t('loading_stats')}</span>
                  </div>
                ) : (
                  <div className="ssp-export-stats">
                    <div className="ssp-export-stat">
                      <span className="ssp-export-stat-value ssp-stat-approved">{summary.approved}</span>
                      <span className="ssp-export-stat-label">{t('stat_approved_count')}</span>
                    </div>
                    <div className="ssp-export-stat">
                      <span className="ssp-export-stat-value ssp-stat-rejected">{summary.rejected}</span>
                      <span className="ssp-export-stat-label">{t('stat_rejected_count')}</span>
                    </div>
                    <div className="ssp-export-stat">
                      <span className="ssp-export-stat-value">{summary.bookmarked}</span>
                      <span className="ssp-export-stat-label">{t('stat_bookmarked_count')}</span>
                    </div>
                    <div className="ssp-export-stat">
                      <span className="ssp-export-stat-value">{summary.total}</span>
                      <span className="ssp-export-stat-label">{t('stat_total_count')}</span>
                    </div>
                  </div>
                )}
              </section>

              <SelectedResultsPreview
                whose={scope === 'mine' ? t('export_count_mine') : t('export_count_all')}
                items={exportItems}
                totalCount={rowCount}
                approvedCount={summary?.approved ?? 0}
                allCount={summary?.total ?? 0}
                exportSet={exportSet}
                onExportSetChange={handleExportSetChange}
                isLoading={itemsLoading}
                hasError={itemsError}
                onOpenModal={() => setIsModalOpen(true)}
              />

              <section className="ssp-card">
                <h3 className="ssp-card-title" style={{ marginBottom: '16px' }}>
                  {t('format_json_title')} & {t('format_csv_title')}
                </h3>

                {/* Three formats: JSON, CSV, and ZIP */}
                <div className="ssp-format-grid ssp-format-grid--triple">
                  <div
                    className={`ssp-format-card ${exportFormat === 'json' ? 'active' : ''}`}
                    onClick={() => setExportFormat('json')}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && setExportFormat('json')}
                  >
                    <div className="ssp-format-icon-wrap">
                      <Code size={24} />
                    </div>
                    <span className="ssp-format-label">{t('format_json_title')}</span>
                  </div>

                  <div
                    className={`ssp-format-card ${exportFormat === 'csv' ? 'active' : ''}`}
                    onClick={() => setExportFormat('csv')}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && setExportFormat('csv')}
                  >
                    <div className="ssp-format-icon-wrap">
                      <FileText size={24} />
                    </div>
                    <span className="ssp-format-label">{t('format_csv_title')}</span>
                  </div>

                  <div
                    className={`ssp-format-card ${exportFormat === 'zip' ? 'active' : ''}`}
                    onClick={() => setExportFormat('zip')}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && setExportFormat('zip')}
                  >
                    <div className="ssp-format-icon-wrap">
                      <Archive size={24} />
                    </div>
                    <span className="ssp-format-label">{t('format_zip_title', 'Hình ảnh (ZIP)')}</span>
                  </div>
                </div>

                <p className="ssp-form-hint">
                  {exportFormat === 'json'
                    ? t('format_json_desc')
                    : exportFormat === 'csv'
                    ? t('format_csv_desc')
                    : t('format_zip_desc', 'Tải toàn bộ các tệp ảnh JPEG của khung hình đã duyệt dưới dạng một tệp nén ZIP duy nhất.')}
                </p>

                <div className="ssp-form-group">
                  <span className="ssp-input-label">{t('export_scope')}</span>
                  <div className="ssp-format-grid ssp-format-grid--pair">
                    <div
                      className={`ssp-format-card ${exportSet === 'approved' ? 'active' : ''}`}
                      onClick={() => handleExportSetChange('approved')}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && handleExportSetChange('approved')}
                    >
                      <span className="ssp-format-label">{t('export_scope_approved')}</span>
                    </div>
                    <div
                      className={`ssp-format-card ${exportSet === 'all' ? 'active' : ''}`}
                      onClick={() => handleExportSetChange('all')}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && handleExportSetChange('all')}
                    >
                      <span className="ssp-format-label">{t('export_scope_all')}</span>
                    </div>
                  </div>
                </div>

                {/* Whose verdicts. Buttons rather than the `div role="button"` pair above, which is
                    the older pattern here: a button is focusable, activates on Space as well as
                    Enter, and announces its pressed state. */}
                <div className="ssp-form-group">
                  <span className="ssp-input-label">{t('export_whose')}</span>
                  <div className="ssp-format-grid ssp-format-grid--pair">
                    {(['all', 'mine'] as const).map((s) => (
                      <button
                        key={s}
                        type="button"
                        className={`ssp-format-card ${scope === s ? 'active' : ''}`}
                        aria-pressed={scope === s}
                        onClick={() => {
                          if (s === scope) return;
                          setScope(s);
                          setItemsLoading(true);
                          setItemsError(false);
                        }}
                      >
                        <span className="ssp-format-label">
                          {s === 'all' ? t('export_whose_all') : t('export_whose_mine')}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>

                {!isOperator && (
                  <div className="ssp-export-notice">
                    <AlertCircle size={18} />
                    <span>{t('operator_notice')}</span>
                  </div>
                )}
                <a
                  className="ssp-btn-export-main"
                  href={exportUrl(exportFormat, exportSet, scope)}
                  download
                  aria-disabled={rowCount === 0 || !isOperator}
                  onClick={handleExportClick}
                >
                  <Download size={22} />
                  <span>
                    {rowCount === 0
                      ? t('btn_export_no_data')
                      : t('btn_export_rows', { count: rowCount, format: exportFormat.toUpperCase() })}
                  </span>
                </a>
              </section>
            </div>

            <div className="ssp-column">
              <section className="ssp-schema-panel">
                <div className="ssp-schema-header">
                  <h3 className="ssp-schema-title">{t('schema_panel_title')}</h3>
                  <span className="ssp-schema-tag">v1.0 Standard</span>
                </div>

                {/* The field list matches src/services/export.py COLUMNS */}
                <div className="ssp-meta-rows">
                  <div className="ssp-meta-row">
                    <span className="ssp-meta-key">QUERY</span>
                    <span className="ssp-meta-value">{t('schema_query_desc')}</span>
                  </div>
                  <div className="ssp-meta-row">
                    <span className="ssp-meta-key">FRAME_ID</span>
                    <span className="ssp-meta-value">{t('schema_frame_id_desc')}</span>
                  </div>
                  <div className="ssp-meta-row">
                    <span className="ssp-meta-key">DECISION</span>
                    <span className="ssp-meta-value">{t('schema_decision_desc')}</span>
                  </div>
                  <div className="ssp-meta-row">
                    <span className="ssp-meta-key">NOTE</span>
                    <span className="ssp-meta-value">{t('schema_note_desc')}</span>
                  </div>
                  <div className="ssp-meta-row">
                    <span className="ssp-meta-key">REVIEWED_AT</span>
                    <span className="ssp-meta-value">{t('schema_reviewed_at_desc')}</span>
                  </div>
                  <div className="ssp-meta-row">
                    <span className="ssp-meta-key">SCENE_ID</span>
                    <span className="ssp-meta-value">{t('schema_scene_id_desc')}</span>
                  </div>
                  <div className="ssp-meta-row">
                    <span className="ssp-meta-key">TIMESTAMP_S</span>
                    <span className="ssp-meta-value">{t('schema_timestamp_s_desc')}</span>
                  </div>
                </div>

                <div className="ssp-security-note">
                  <p className="ssp-security-text">
                    {t('schema_security_note')}
                  </p>
                </div>
              </section>
            </div>
          </div>
        </main>
      </div>

      <SelectedItemsModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        items={exportItems}
        exportSet={exportSet}
        onExportSetChange={handleExportSetChange}
        isLoading={itemsLoading}
        myReviewer={myReviewer}
        onUnselect={handleUnselect}
        onDownloadImage={handleDownloadImage}
        onExportFormat={handleExportByFormat}
        onDownloadClick={() => {
          const downloadEl = document.querySelector<HTMLAnchorElement>('.ssp-btn-export-main');
          if (downloadEl) downloadEl.click();
        }}
      />

      <ToastContainer messages={messages} onDismiss={dismiss} />
    </div>
  );
};

export default ExportData;
