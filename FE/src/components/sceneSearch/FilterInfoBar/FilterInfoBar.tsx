import React from 'react';
import { useTranslation } from 'react-i18next';
import { Info, LayoutGrid, List, Calendar, X } from 'lucide-react';
import { Dropdown, type DropdownOption } from '../../base/Dropdown/Dropdown';
import './FilterInfoBar.css';

export interface FilterInfoBarProps {
  totalResults: number;
  distinctScenes?: number;
  sortBy: string;
  onSortChange: (sort: string) => void;
  /**
   * How many results the **server** returns — `top_k`, not a page size.
   *
   * The name is historical and kept only because renaming it reaches into two files for no
   * user-visible gain; the label it renders says "Results". It stopped being a page size twice
   * over: PR #169 wired it to `top_k` so it changes what is fetched rather than what is shown, and
   * the page numbers under the grid were removed on 2026-08-31 because there was never a second
   * page — `top_k` is also the diversity window, and M2_DESIGN §7 measured widening it to fill
   * pages at a third of the ranking lift for no extra diversity.
   */
  pageSize: string;
  onPageSizeChange: (size: string) => void;
  viewMode: 'grid' | 'list';
  onViewModeChange: (mode: 'grid' | 'list') => void;
  selectedDate?: string;
  onDateChange?: (date: string) => void;
}

export const FilterInfoBar: React.FC<FilterInfoBarProps> = ({
  totalResults,
  distinctScenes,
  sortBy,
  onSortChange,
  pageSize,
  onPageSizeChange,
  viewMode,
  onViewModeChange,
  selectedDate = '',
  onDateChange,
}) => {
  const { t } = useTranslation();

  const sortOptions: DropdownOption[] = [
    { value: 'similarity_desc', label: t('sort_similarity_desc') },
    { value: 'similarity_asc', label: t('sort_similarity_asc') },
    { value: 'time_desc', label: t('sort_time_desc') },
    { value: 'time_asc', label: t('sort_time_asc') },
  ];

  const pageSizeOptions: DropdownOption[] = [
    { value: '10', label: '10' },
    { value: '20', label: '20' },
    { value: '50', label: '50' },
  ];

  // Normalize legacy sort values if any
  const normalizedSortBy =
    sortBy === 'similarity'
      ? 'similarity_desc'
      : sortBy === 'newest'
      ? 'time_desc'
      : sortBy === 'oldest'
      ? 'time_asc'
      : sortBy;

  return (
    <div className="ssp-filter-info-bar">
      <span className="ssp-results-count">
        <Info size={16} className="ssp-info-icon" />
        {distinctScenes !== undefined ? (
          <span>
            {t('results_distinct', { totalResults, distinctScenes })}
          </span>
        ) : (
          <span>{t('results_simple', { totalResults })}</span>
        )}
      </span>

      <div className="ssp-divider-v" />

      <div className="ssp-filter-controls">
        {/* Sort Dropdown */}
        <Dropdown
          label={t('sort_label')}
          options={sortOptions}
          value={normalizedSortBy}
          onChange={onSortChange}
        />

        {/* Date Filter Picker */}
        {onDateChange && (
          <div className="ssp-date-filter-wrap">
            <span className="ssp-date-label">{t('filter_date_label')}</span>
            <div className="ssp-date-input-container">
              <Calendar size={14} className="ssp-date-icon" />
              <input
                type="date"
                className="ssp-date-input"
                value={selectedDate}
                onChange={(e) => onDateChange(e.target.value)}
                aria-label={t('filter_date_label')}
              />
              {selectedDate && (
                <button
                  type="button"
                  className="ssp-date-clear-btn"
                  onClick={() => onDateChange('')}
                  title="Clear date filter"
                  aria-label="Clear date filter"
                >
                  <X size={12} />
                </button>
              )}
            </div>
          </div>
        )}

        {/* Page Size Dropdown */}
        <Dropdown
          label={t('page_size_label')}
          options={pageSizeOptions}
          value={pageSize}
          onChange={onPageSizeChange}
        />

        {/* Grid / List View Toggle */}
        <div className="ssp-view-toggle-group">
          <button
            type="button"
            className={`ssp-view-toggle-btn ${viewMode === 'grid' ? 'active' : ''}`}
            onClick={() => onViewModeChange('grid')}
            title={t('view_grid')}
            aria-label={t('view_grid')}
          >
            <LayoutGrid size={16} />
          </button>
          <button
            type="button"
            className={`ssp-view-toggle-btn ${viewMode === 'list' ? 'active' : ''}`}
            onClick={() => onViewModeChange('list')}
            title={t('view_list')}
            aria-label={t('view_list')}
          >
            <List size={16} />
          </button>
        </div>
      </div>
    </div>
  );
};

export default FilterInfoBar;
