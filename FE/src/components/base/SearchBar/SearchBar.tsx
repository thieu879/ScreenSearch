import React from 'react';
import { Search, CornerDownLeft, X } from 'lucide-react';
import { MAX_QUERY_LENGTH } from '../../../api/client';
import './SearchBar.css';

interface SearchBarProps {
  value: string;
  onChange: (v: string) => void;
  /** Fired on Enter or the submit button — never per keystroke. */
  onSubmit: () => void;
  disabled?: boolean;
  placeholder?: string;
}

/**
 * A form, not a live filter.
 *
 * The mockup filtered a local array on every keystroke. Against the real API each search is an LLM
 * parse plus a retrieval pass — the only paid call in the system — so it fires on explicit submit.
 */
export const SearchBar: React.FC<SearchBarProps> = ({
  value,
  onChange,
  onSubmit,
  disabled = false,
  placeholder = 'Mô tả cảnh bạn cần, ví dụ: "a pedestrian to the front-left"',
}) => {
  return (
    <form
      className="search-bar"
      onSubmit={(e) => {
        e.preventDefault();
        if (!disabled) onSubmit();
      }}
      role="search"
    >
      <Search size={18} className="search-bar__icon" aria-hidden="true" />
      <input
        id="scene-search-input"
        type="search"
        className="search-bar__input"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        maxLength={MAX_QUERY_LENGTH}
        disabled={disabled}
        autoComplete="off"
        aria-label="Truy vấn tìm kiếm"
      />
      <div className="search-bar__right-actions">
        {value && (
          <button
            type="button"
            className="search-bar__clear"
            onClick={() => onChange('')}
            disabled={disabled}
            aria-label="Xóa nội dung tìm kiếm"
            title="Xóa truy vấn"
          >
            <X size={16} aria-hidden="true" />
          </button>
        )}
        <button type="submit" className="search-bar__submit" disabled={disabled} aria-label="Tìm kiếm">
          <CornerDownLeft size={15} aria-hidden="true" />
          <span className="search-bar__submit-text">Tìm</span>
        </button>
      </div>
    </form>
  );
};

export default SearchBar;
