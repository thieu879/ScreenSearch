import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Search,
  Download,
  Trash2,
  ChevronLeft,
  ChevronRight,
  TrendingUp,
  Clock,
  AlertTriangle,
} from 'lucide-react';
import { Sidebar } from '../../components/layout/Sidebar/Sidebar';
import { TopBar } from '../../components/layout/TopBar/TopBar';
import { Modal } from '../../components/base/Modal/Modal';
import { Button } from '../../components/base/Button/Button';
import { useToast } from '../../components/base/Toast/useToast';
import { ToastContainer } from '../../components/base/Toast/Toast';
import {
  clearSearchHistoryAll,
  deleteSearchHistoryEntry,
  fetchSearchHistory,
} from '../../api/client';
import type { HistoryEntry } from '../../types/api';

import './SearchHistory.css';

interface DeleteModalState {
  isOpen: boolean;
  mode: 'all' | 'single';
  targetItem?: { id: string; keyword: string };
}

/** What a row needs to render. The server's shape, flattened and formatted once. */
interface HistoryRow {
  id: string;
  keyword: string;
  filters: string[];
  date: string;
  resultsCount: number;
}

/**
 * `DD/MM/YYYY HH:MM` in the reader's own timezone.
 *
 * The server stores UTC and sends ISO-8601, which is the right thing to transport and the wrong
 * thing to show — a reviewer in Hanoi comparing "when did I run that" against their own afternoon
 * should not be doing arithmetic. Formatting here rather than server-side is also what makes that
 * possible at all: the server does not know where the reader is.
 */
function formatWhen(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return '—';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(when.getDate())}/${pad(when.getMonth() + 1)}/${when.getFullYear()} ${pad(when.getHours())}:${pad(when.getMinutes())}`;
}

function toRow(entry: HistoryEntry): HistoryRow {
  return {
    id: entry.entry_id,
    keyword: entry.keyword,
    filters: entry.filters ?? [],
    date: formatWhen(entry.created_at),
    resultsCount: entry.results_count,
  };
}

export const SearchHistory: React.FC = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { messages, addToast, dismiss } = useToast();

  // Server-side and per account since 2026-08-30. It was five rows in `localStorage`, which is a
  // browser profile rather than a person: invisible on a second machine, and shared by every
  // account that signed in on one laptop. `src/services/history.py` carries the argument.
  const [searchTerm, setSearchTerm] = useState('');
  const [historyList, setHistoryList] = useState<HistoryRow[]>([]);
  const [loadFailed, setLoadFailed] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);

  useEffect(() => {
    let cancelled = false;
    fetchSearchHistory()
      .then((entries) => {
        if (!cancelled) setHistoryList(entries.map(toRow));
      })
      .catch(() => {
        // An empty table with no explanation reads as "you have never searched", which is a
        // different and wrong claim. Say the list could not be loaded instead.
        if (!cancelled) setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const pageSize = 10;

  // Confirmation Modal state
  const [deleteModalState, setDeleteModalState] = useState<DeleteModalState>({
    isOpen: false,
    mode: 'all',
  });

  const filteredHistory = useMemo(() => {
    return historyList.filter((item) =>
      item.keyword.toLowerCase().includes(searchTerm.toLowerCase())
    );
  }, [historyList, searchTerm]);

  const totalPages = Math.max(1, Math.ceil(filteredHistory.length / pageSize));
  const paginatedHistory = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredHistory.slice(start, start + pageSize);
  }, [filteredHistory, currentPage]);

  const handleRowClick = (keyword: string) => {
    addToast('info', t('toast_search_again'), t('toast_search_again_desc', { keyword }));
    navigate(`/search?q=${encodeURIComponent(keyword)}`, { state: { autoSearch: keyword } });
  };

  const openDeleteSingleModal = (id: string, keyword: string) => {
    setDeleteModalState({
      isOpen: true,
      mode: 'single',
      targetItem: { id, keyword },
    });
  };

  const openDeleteAllModal = () => {
    if (historyList.length === 0) {
      addToast('info', t('toast_info'), t('toast_history_empty'));
      return;
    }
    setDeleteModalState({
      isOpen: true,
      mode: 'all',
    });
  };

  /**
   * Delete optimistically, restore on failure.
   *
   * The row disappears the moment the modal is confirmed, because waiting on a round trip before a
   * confirmed deletion visibly happens is what makes a list feel slow. Restoring on failure is what
   * keeps that honest — the alternative would tell a reviewer their history was cleared when the
   * server still holds it, and they would find out on the next page load.
   */
  const handleConfirmDelete = () => {
    const previous = historyList;
    if (deleteModalState.mode === 'all') {
      setHistoryList([]);
      void clearSearchHistoryAll()
        .then(() => addToast('success', t('btn_confirm'), t('toast_clear_all_success')))
        .catch(() => {
          setHistoryList(previous);
          addToast('error', t('toast_error'), t('toast_history_delete_failed'));
        });
    } else if (deleteModalState.targetItem) {
      const { id, keyword } = deleteModalState.targetItem;
      setHistoryList((rows) => rows.filter((row) => row.id !== id));
      void deleteSearchHistoryEntry(id)
        .then(() => addToast('success', t('btn_confirm'), t('toast_removed_keyword', { keyword })))
        .catch(() => {
          setHistoryList(previous);
          addToast('error', t('toast_error'), t('toast_history_delete_failed'));
        });
    }
    setDeleteModalState({ isOpen: false, mode: 'all' });
  };

  const handleExportExcel = () => {
    if (filteredHistory.length === 0) {
      addToast('info', t('toast_no_data'), t('toast_no_history_export'));
      return;
    }
    const csvContent =
      'data:text/csv;charset=utf-8,' +
      [t('csv_headers')]
        .concat(
          filteredHistory.map(
            (r) => `"${r.keyword}","${r.filters.join('; ')}","${r.date}",${r.resultsCount}`
          )
        )
        .join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', 'search_history.csv');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    addToast('success', t('nav_export'), t('toast_export_success'));
  };

  return (
    <div className="ssp-app-layout">
      {/* Sidebar Navigation */}
      <Sidebar
        activeTab="history"
        isOpen={isMobileMenuOpen}
        onClose={() => setIsMobileMenuOpen(false)}
      />

      {/* Main Content Area */}
      <div className="ssp-main-wrapper">
        {/* Top Header Bar */}
        <TopBar
          pageTitle={t('history_page_title')}
          onToggleMenu={() => setIsMobileMenuOpen((prev) => !prev)}
        />

        {/* Content Container */}
        <main className="ssp-content-container">
          {/* Header Search Filter Bar */}
          <div className="ssp-history-search-filter-bar">
            <div className="ssp-header-search-wrapper">
              <Search className="ssp-header-search-icon" size={18} />
              <input
                type="text"
                className="ssp-header-search-input"
                placeholder={t('history_search_placeholder')}
                value={searchTerm}
                onChange={(e) => {
                  setSearchTerm(e.target.value);
                  setCurrentPage(1);
                }}
              />
            </div>
          </div>

          <div className="ssp-stats-grid ssp-stats-grid--three">
            <div className="ssp-stat-card">
              <p className="ssp-stat-label">{t('stat_total_queries')}</p>
              <div className="ssp-stat-content">
                <h3 className="ssp-stat-value">{historyList.length}</h3>
                <Clock size={20} className="ssp-icon-timer" />
              </div>
            </div>

            <div className="ssp-stat-card">
              <p className="ssp-stat-label">{t('stat_avg_results')}</p>
              <div className="ssp-stat-content">
                <h3 className="ssp-stat-value">
                  {historyList.length === 0
                    ? '—'
                    : (
                        historyList.reduce((sum, item) => sum + item.resultsCount, 0) / historyList.length
                      ).toFixed(1)}
                </h3>
                <TrendingUp size={20} className="ssp-icon-trend" />
              </div>
            </div>

            <div className="ssp-stat-card">
              <p className="ssp-stat-label">{t('stat_last_query')}</p>
              <div className="ssp-stat-content">
                <h3 className="ssp-stat-value ssp-stat-value--date">
                  {historyList.length === 0 ? '—' : historyList[0].date}
                </h3>
              </div>
            </div>
          </div>

          {/* History Table Card */}
          <div className="ssp-table-card">
            <div className="ssp-table-header">
              <h4 className="ssp-table-title">{t('history_page_title')}</h4>
              <div className="ssp-table-actions">
                <button
                  type="button"
                  className="ssp-btn-outline"
                  onClick={handleExportExcel}
                >
                  <Download size={16} />
                  <span>{t('btn_export_csv')}</span>
                </button>
                <button
                  type="button"
                  className="ssp-btn-outline danger"
                  onClick={openDeleteAllModal}
                >
                  <Trash2 size={16} />
                  <span>{t('btn_clear_all')}</span>
                </button>
              </div>
            </div>

            <div className="ssp-table-wrapper">
              <table className="ssp-history-table">
                <thead>
                  <tr>
                    <th>{t('th_keyword')}</th>
                    <th>{t('th_filters')}</th>
                    <th>{t('th_date')}</th>
                    <th>{t('th_count')}</th>
                    <th style={{ textAlign: 'right' }}>{t('th_actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {paginatedHistory.map((row) => (
                    <tr
                      key={row.id}
                      className="ssp-history-row"
                      onClick={() => handleRowClick(row.keyword)}
                    >
                      <td>
                        <div className="ssp-keyword-box">
                          <div className="ssp-search-icon-badge">
                            <Search size={18} />
                          </div>
                          <span className="ssp-keyword-text">{row.keyword}</span>
                        </div>
                      </td>
                      <td>
                        <div className="ssp-filter-tags">
                          {row.filters.length > 0 ? (
                            row.filters.map((filter, idx) => (
                              <span key={idx} className="ssp-filter-chip">
                                {filter}
                              </span>
                            ))
                          ) : (
                            <span className="ssp-text-muted" style={{ fontSize: '12px' }}>Default</span>
                          )}
                        </div>
                      </td>
                      <td>
                        <span className="ssp-text-muted">{row.date}</span>
                      </td>
                      <td>
                        <span className="ssp-text-bold">{row.resultsCount} {t('count_results_suffix')}</span>
                      </td>
                      <td style={{ textAlign: 'right' }} onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          className="ssp-btn-icon-round ssp-btn-delete-row"
                          title={t('confirm_delete_title')}
                          onClick={(e) => {
                            e.stopPropagation();
                            openDeleteSingleModal(row.id, row.keyword);
                          }}
                        >
                          <Trash2 size={16} />
                        </button>
                      </td>
                    </tr>
                  ))}

                  {paginatedHistory.length === 0 && (
                    <tr>
                      <td colSpan={5} style={{ textAlign: 'center', padding: '36px 24px', color: '#64748b' }}>
                        {loadFailed ? t('history_load_failed') : t('empty_history')}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination Footer */}
            <div className="ssp-table-footer">
              <span className="ssp-text-muted">
                {t('pagination_showing', {
                  start: paginatedHistory.length > 0 ? (currentPage - 1) * pageSize + 1 : 0,
                  end: Math.min(currentPage * pageSize, filteredHistory.length),
                  total: filteredHistory.length,
                })}
              </span>

              <div className="ssp-pagination">
                <button
                  type="button"
                  className="ssp-page-number"
                  disabled={currentPage <= 1}
                  onClick={() => setCurrentPage(currentPage - 1)}
                  aria-label={t('prev_page')}
                  title={t('prev_page')}
                >
                  <ChevronLeft size={16} />
                </button>

                {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
                  <button
                    key={p}
                    type="button"
                    className={`ssp-page-number ${currentPage === p ? 'active' : ''}`}
                    onClick={() => setCurrentPage(p)}
                  >
                    {p}
                  </button>
                ))}

                <button
                  type="button"
                  className="ssp-page-number"
                  disabled={currentPage >= totalPages}
                  onClick={() => setCurrentPage(currentPage + 1)}
                  aria-label={t('next_page')}
                  title={t('next_page')}
                >
                  <ChevronRight size={16} />
                </button>
              </div>
            </div>
          </div>
        </main>
      </div>

      {/* Confirmation Warning Modal for Deletion */}
      <Modal
        isOpen={deleteModalState.isOpen}
        onClose={() => setDeleteModalState({ isOpen: false, mode: 'all' })}
        title={deleteModalState.mode === 'all' ? t('confirm_clear_title') : t('confirm_delete_title')}
        size="sm"
      >
        <div className="ssp-delete-confirm-content">
          <div className="ssp-delete-warning-icon">
            <AlertTriangle size={36} />
          </div>

          <p className="ssp-delete-warning-text">
            {deleteModalState.mode === 'all' ? (
              <span>{t('confirm_clear_desc')}</span>
            ) : (
              <span>{t('confirm_delete_item', { keyword: deleteModalState.targetItem?.keyword })}</span>
            )}
          </p>

          <div className="ssp-delete-modal-actions">
            <Button
              variant="secondary"
              onClick={() => setDeleteModalState({ isOpen: false, mode: 'all' })}
            >
              {t('btn_cancel')}
            </Button>
            <Button
              variant="danger"
              onClick={handleConfirmDelete}
            >
              {t('btn_confirm_delete')}
            </Button>
          </div>
        </div>
      </Modal>

      <ToastContainer messages={messages} onDismiss={dismiss} />
    </div>
  );
};

export default SearchHistory;
