/**
 * Split out of `Toast.tsx` so that file exports components only.
 *
 * Mixing a hook in with the components breaks React Fast Refresh — the whole module remounts on
 * edit instead of hot-swapping — and eslint's `react-refresh/only-export-components` flags it as an
 * error, which meant `npm run lint` could never pass.
 */
import { useCallback, useState } from 'react';
import type { ToastMessage, ToastVariant } from './Toast';

export function useToast() {
  const [messages, setMessages] = useState<ToastMessage[]>([]);

  const addToast = useCallback((variant: ToastVariant, title: string, description?: string) => {
    const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    setMessages((prev) => [...prev, { id, variant, title, description }]);
  }, []);

  const dismiss = useCallback((id: string) => {
    setMessages((prev) => prev.filter((m) => m.id !== id));
  }, []);

  return { messages, addToast, dismiss };
}
