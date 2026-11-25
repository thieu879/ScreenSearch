import React from 'react';
import { useTranslation } from 'react-i18next';
import { Search, Loader2, X } from 'lucide-react';
import './SearchHero.css';

export interface SearchHeroProps {
  value: string;
  onChange: (val: string) => void;
  onSubmit: () => void;
  isLoading?: boolean;
  placeholder?: string;
  exampleQueries?: Array<{ query: string; hintKey: string }>;
  onSelectExample?: (query: string) => void;
}

export const SearchHero: React.FC<SearchHeroProps> = ({
  value,
  onChange,
  onSubmit,
  isLoading = false,
  placeholder,
  exampleQueries,
  onSelectExample,
}) => {
  const { t } = useTranslation();
  const defaultPlaceholder = placeholder || t('search_placeholder');

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      onSubmit();
    }
  };

  return (
    <section className="ssp-search-hero">
      <div className="ssp-search-input-wrapper">
        <Search className="ssp-search-icon-inside" size={22} />
        <input
          type="text"
          className="ssp-search-input"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={defaultPlaceholder}
          disabled={isLoading}
        />
        <div className="ssp-search-right-actions">
          {value && (
            <button
              type="button"
              className="ssp-btn-clear"
              onClick={() => onChange('')}
              disabled={isLoading}
              aria-label={t('search_clear_tooltip')}
              title={t('search_clear_tooltip')}
            >
              <X size={18} />
            </button>
          )}
          <button
            type="button"
            className="ssp-btn-search"
            onClick={onSubmit}
            disabled={isLoading}
          >
            {isLoading ? (
              <span className="ssp-btn-loading-content">
                <Loader2 size={16} className="ssp-spinner" />
                {t('search_searching')}
              </span>
            ) : (
              t('search_btn')
            )}
          </button>
        </div>
      </div>

      {exampleQueries && exampleQueries.length > 0 && (
        <div className="ssp-example-queries">
          <span className="ssp-example-label">{t('suggested_queries')}</span>
          <div className="ssp-example-chips">
            {exampleQueries.map(({ query, hintKey }) => (
              <button
                key={query}
                type="button"
                className="ssp-example-chip"
                onClick={() => onSelectExample?.(query)}
                title={t(hintKey)}
              >
                <span>{query}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
};

export default SearchHero;
