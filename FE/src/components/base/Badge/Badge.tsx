import React from 'react';
import './Badge.css';

export type BadgeVariant = 'primary' | 'success' | 'error' | 'warning' | 'ghost' | 'info';

export interface BadgeProps {
  variant?: BadgeVariant;
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}

export const Badge: React.FC<BadgeProps> = ({
  variant = 'ghost',
  children,
  className = '',
  style,
}) => {
  return (
    <span
      className={`badge badge--${variant} ${className}`}
      style={style}
    >
      {children}
    </span>
  );
};

export default Badge;
