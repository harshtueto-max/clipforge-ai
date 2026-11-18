import { create } from 'zustand';

export type ToastKind = 'error' | 'success' | 'info' | 'warning';
export interface Toast {
  id: number;
  kind: ToastKind;
  title: string;
  message?: string;
}

interface ToastState {
  toasts: Toast[];
  push: (kind: ToastKind, title: string, message?: string, ttl?: number) => void;
  dismiss: (id: number) => void;
}

let seq = 1;

export const useToasts = create<ToastState>((set, get) => ({
  toasts: [],
  push: (kind, title, message, ttl) => {
    const id = seq++;
    set({ toasts: [...get().toasts.slice(-4), { id, kind, title, message }] });
    const life = ttl ?? (kind === 'error' ? 8000 : 4000);
    window.setTimeout(() => get().dismiss(id), life);
  },
  dismiss: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
}));

export const toast = {
  error: (title: string, message?: string) => useToasts.getState().push('error', title, message),
  success: (title: string, message?: string) => useToasts.getState().push('success', title, message),
  info: (title: string, message?: string) => useToasts.getState().push('info', title, message),
  warning: (title: string, message?: string) => useToasts.getState().push('warning', title, message),
};
