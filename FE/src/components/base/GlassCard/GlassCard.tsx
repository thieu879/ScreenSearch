import React from 'react';
import './GlassCard.css';

export interface GlassCardProps {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
  onClick?: () => void;
  hoverable?: boolean;
}

export const GlassCard: React.FC<GlassCardProps> = ({
  children,
  className = '',
  style,
  onClick,
  hoverable = true,
}) => {
  return (
    <div
      className={`glass-card ${hoverable ? 'glass-card--hoverable' : ''} ${className}`}
      style={style}
      onClick={onClick}
    >
      {children}
    </div>
  );
};

export default GlassCard;
