import React, { useEffect, useRef } from 'react';
import { CheckCircle, AlertTriangle, XCircle, Info, X } from 'lucide-react';
import './Toast.css';
import { useTranslation } from 'react-i18next';

export type ToastVariant = 'success' | 'warning' | 'error' | 'info';

export interface ToastMessage {
  id: string;
  variant: ToastVariant;
  title: string;
  description?: string;
}

interface ToastItemProps extends ToastMessage {
  onDismiss: (id: string) => void;
}

const icons: Record<ToastVariant, React.ReactNode> = {
  success: <CheckCircle size={18} />,
  warning: <AlertTriangle size={18} />,
  error: <XCircle size={18} />,
  info: <Info size={18} />,
};

export const ToastItem: React.FC<ToastItemProps> = ({
  id,
  variant,
  title,
  description,
  onDismiss,
}) => {
  const { t } = useTranslation();
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    timerRef.current = setTimeout(() => onDismiss(id), 3500);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [id, onDismiss]);

  return (
    <div className={`toast toast--${variant}`} role="alert">
      <span className="toast-icon">{icons[variant]}</span>
      <div className="toast-content">
        <p className="toast-title">{title}</p>
        {description && <p className="toast-desc">{description}</p>}
      </div>
      <button
        className="toast-close"
        onClick={() => onDismiss(id)}
        aria-label={t('a11y_close_toast')}
      >
        <X size={14} />
      </button>
    </div>
  );
};

/* ── Toast Container ─────────────────────────────────────── */
interface ToastContainerProps {
  messages: ToastMessage[];
  onDismiss: (id: string) => void;
}

export const ToastContainer: React.FC<ToastContainerProps> = ({
  messages,
  onDismiss,
}) => {
  if (messages.length === 0) return null;
  return (
    <div className="toast-container" aria-live="polite">
      {messages.map((msg) => (
        <ToastItem key={msg.id} {...msg} onDismiss={onDismiss} />
      ))}
    </div>
  );
};

/* The `useToast` hook lives in `./useToast.ts`. Keeping it here made this module export both a hook
   and components, which breaks Fast Refresh and fails `react-refresh/only-export-components`. */

export default ToastContainer;
