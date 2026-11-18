import { AnimatePresence, motion } from 'framer-motion';
import { AlertCircle, CheckCircle2, Info, TriangleAlert, X } from 'lucide-react';
import { useToasts } from '../stores/toast';

export function Toaster() {
  const { toasts, dismiss } = useToasts();
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-[360px] flex-col gap-2">
      <AnimatePresence initial={false}>
        {toasts.map((t) => {
          const Icon = { error: AlertCircle, success: CheckCircle2, info: Info, warning: TriangleAlert }[t.kind];
          const color = { error: 'text-red-400', success: 'text-emerald-400', info: 'text-sky-400', warning: 'text-amber-400' }[t.kind];
          return (
            <motion.div
              key={t.id}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, x: 20 }}
              transition={{ duration: 0.15 }}
              className="pointer-events-auto flex items-start gap-2.5 rounded-lg border border-ink-600 bg-ink-750 p-3 shadow-pop"
              role={t.kind === 'error' ? 'alert' : 'status'}
            >
              <Icon className={`mt-px h-4 w-4 shrink-0 ${color}`} />
              <div className="min-w-0 flex-1">
                <div className="text-xs font-semibold text-ink-50">{t.title}</div>
                {t.message && <div className="mt-0.5 break-words text-xs leading-snug text-ink-200">{t.message}</div>}
              </div>
              <button className="text-ink-300 hover:text-ink-50" onClick={() => dismiss(t.id)} aria-label="Dismiss">
                <X className="h-3.5 w-3.5" />
              </button>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
