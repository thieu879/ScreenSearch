import React, { forwardRef } from 'react';
import './Input.css';

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  prefixIcon?: React.ReactNode;
  suffixNode?: React.ReactNode;
  error?: string;
  hint?: string;
  fullWidth?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  (
    {
      label,
      prefixIcon,
      suffixNode,
      error,
      hint,
      fullWidth = false,
      className = '',
      id,
      ...rest
    },
    ref
  ) => {
    const inputId = id ?? `input-${Math.random().toString(36).slice(2, 7)}`;

    return (
      <div className={`input-wrapper ${fullWidth ? 'input-wrapper--full' : ''} ${className}`}>
        {label && (
          <label className="input-label" htmlFor={inputId}>
            {label}
          </label>
        )}
        <div className={`input-field ${error ? 'input-field--error' : ''}`}>
          {prefixIcon && (
            <span className="input-prefix-icon" aria-hidden="true">
              {prefixIcon}
            </span>
          )}
          <input
            ref={ref}
            id={inputId}
            className="input-el"
            {...rest}
          />
          {suffixNode && <span className="input-suffix">{suffixNode}</span>}
        </div>
        {error && <p className="input-error">{error}</p>}
        {!error && hint && <p className="input-hint">{hint}</p>}
      </div>
    );
  }
);

Input.displayName = 'Input';
export default Input;
