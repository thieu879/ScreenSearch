import React from 'react';
import './Checkbox.css';

export interface CheckboxProps {
  id: string;
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}

export const Checkbox: React.FC<CheckboxProps> = ({
  id,
  label,
  checked,
  onChange,
  disabled = false,
}) => {
  return (
    <label
      htmlFor={id}
      className={`checkbox-label ${disabled ? 'checkbox-label--disabled' : ''}`}
    >
      <div className="checkbox-wrapper">
        <input
          id={id}
          type="checkbox"
          className="checkbox-input"
          checked={checked}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span className={`checkbox-box ${checked ? 'checkbox-box--checked' : ''}`} aria-hidden="true">
          {checked && (
            <svg width="10" height="8" viewBox="0 0 10 8" fill="none">
              <path
                d="M1 4L3.5 6.5L9 1"
                stroke="white"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          )}
        </span>
      </div>
      <span className={`checkbox-text ${checked ? 'checkbox-text--checked' : ''}`}>
        {label}
      </span>
    </label>
  );
};

export default Checkbox;
