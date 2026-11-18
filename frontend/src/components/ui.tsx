import { AnimatePresence, motion } from 'framer-motion';
import { AlertTriangle, Loader2, X } from 'lucide-react';
import { forwardRef, useEffect, useId, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cx, scoreColor } from '../lib/format';

// ---------------------------------------------------------------- Button
type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'subtle';
type Size = 'xs' | 'sm' | 'md';
interface BtnProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
}
const variants: Record<Variant, string> = {
  primary: 'bg-amber-500 text-ink-950 hover:bg-amber-400 font-semibold border border-amber-400/60',
  secondary: 'bg-ink-700 text-ink-50 hover:bg-ink-650 border border-ink-600',
  ghost: 'text-ink-100 hover:bg-ink-700 hover:text-ink-50 border border-transparent',
  subtle: 'bg-ink-800 text-ink-100 hover:bg-ink-700 border border-ink-600/70',
  danger: 'bg-red-500/10 text-red-300 hover:bg-red-500/20 border border-red-500/30',
};
const sizes: Record<Size, string> = {
  xs: 'h-6 px-2 text-2xs gap-1 rounded',
  sm: 'h-7 px-2.5 text-xs gap-1.5 rounded-md',
  md: 'h-9 px-3.5 text-sm gap-2 rounded-md',
};
export const Button = forwardRef<HTMLButtonElement, BtnProps>(function Button(
  { variant = 'secondary', size = 'sm', loading, icon, className, children, disabled, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cx(
        'inline-flex items-center justify-center whitespace-nowrap transition-colors select-none disabled:opacity-45 disabled:cursor-not-allowed focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-500/70',
        variants[variant],
        sizes[size],
        className,
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : icon}
      {children}
    </button>
  );
});

export function IconButton({ title, className, active, type = 'button', ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { title: string; active?: boolean }) {
  return (
    <button
      type={type}
      title={title}
      aria-label={title}
      className={cx(
        'inline-flex h-7 w-7 items-center justify-center rounded-md text-ink-200 hover:bg-ink-700 hover:text-ink-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors',
        active && 'bg-amber-500/15 text-amber-400 hover:bg-amber-500/20 hover:text-amber-300',
        className,
      )}
      {...rest}
    />
  );
}

// ---------------------------------------------------------------- Spinner / states
export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx('animate-spin text-ink-300', className ?? 'h-4 w-4')} />;
}

export function LoadingBlock({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex h-40 items-center justify-center gap-2 text-sm text-ink-300">
      <Spinner /> {label}
    </div>
  );
}

export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-ink-600 bg-ink-850/50 px-6 py-10 text-center">
      {icon && <div className="mb-3 text-ink-400">{icon}</div>}
      <div className="text-sm font-medium text-ink-100">{title}</div>
      {children && <div className="mt-1 max-w-md text-xs text-ink-300">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-200">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
      <div className="flex-1">
        <div>{message}</div>
        {onRetry && (
          <Button size="xs" variant="danger" className="mt-2" onClick={onRetry}>
            Retry
          </Button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Panel / Card
export function Panel({ title, actions, children, className, bodyClass }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string }) {
  return (
    <section className={cx('rounded-lg border border-ink-600 bg-ink-800 shadow-panel', className)}>
      {(title || actions) && (
        <header className="flex h-10 items-center justify-between border-b border-ink-600 px-3.5">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-200">{title}</h3>
          <div className="flex items-center gap-1.5">{actions}</div>
        </header>
      )}
      <div className={cx('p-3.5', bodyClass)}>{children}</div>
    </section>
  );
}

// ---------------------------------------------------------------- Progress
export function ProgressBar({ value, className, tone = 'amber', indeterminate }: { value: number; className?: string; tone?: 'amber' | 'green' | 'red' | 'blue'; indeterminate?: boolean }) {
  const color = { amber: 'bg-amber-500', green: 'bg-emerald-400', red: 'bg-red-400', blue: 'bg-sky-400' }[tone];
  return (
    <div className={cx('relative h-1.5 w-full overflow-hidden rounded-full bg-ink-650', className)}>
      {indeterminate ? (
        <div className={cx('absolute inset-y-0 w-1/3 animate-[slide_1.2s_ease-in-out_infinite] rounded-full', color)} />
      ) : (
        <div className={cx('h-full rounded-full transition-[width] duration-300', color)} style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
      )}
    </div>
  );
}

export function ScoreRing({ score, size = 40, stroke = 3.5 }: { score: number; size?: number; stroke?: number }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(100, score));
  const col = scoreColor(v);
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} title={`Quality score ${v.toFixed(0)}/100`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="#26282e" strokeWidth={stroke} fill="none" />
        <circle cx={size / 2} cy={size / 2} r={r} stroke={col} strokeWidth={stroke} fill="none" strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} strokeLinecap="round" />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[11px] font-semibold" style={{ color: col, fontSize: size * 0.3 }}>
        {v.toFixed(0)}
      </div>
    </div>
  );
}

export function ScoreBar({ value, label, explanation }: { value: number; label: string; explanation?: string }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-2xs">
        <span className="text-ink-200">{label}</span>
        <span className="font-mono" style={{ color: scoreColor(value) }}>
          {value.toFixed(0)}
        </span>
      </div>
      <div className="h-1 overflow-hidden rounded-full bg-ink-650">
        <div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(100, value))}%`, background: scoreColor(value) }} />
      </div>
      {explanation && <div className="mt-1 text-2xs leading-snug text-ink-300">{explanation}</div>}
    </div>
  );
}

// ---------------------------------------------------------------- Badge
export function Badge({ children, tone = 'default', className, title }: { children: ReactNode; tone?: 'default' | 'amber' | 'green' | 'red' | 'blue' | 'violet'; className?: string; title?: string }) {
  const tones = {
    default: 'bg-ink-700 text-ink-100 border-ink-600',
    amber: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
    green: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
    red: 'bg-red-500/10 text-red-300 border-red-500/30',
    blue: 'bg-sky-500/10 text-sky-300 border-sky-500/30',
    violet: 'bg-violet-500/10 text-violet-300 border-violet-500/30',
  };
  return (
    <span title={title} className={cx('inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-px text-2xs font-medium', tones[tone], className)}>
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, 'default' | 'amber' | 'green' | 'red' | 'blue' | 'violet'> = {
    accepted: 'green', rejected: 'red', suggested: 'default', completed: 'green', failed: 'red', running: 'amber', queued: 'blue',
    cancelled: 'default', interrupted: 'violet', analyzed: 'green', analyzing: 'amber', ready: 'blue', importing: 'amber', created: 'default',
    proxy_ready: 'blue', error: 'red', failed_import: 'red',
  };
  return <Badge tone={map[status] ?? 'default'}>{status.replace(/_/g, ' ')}</Badge>;
}

// ---------------------------------------------------------------- Form controls
export function Toggle({ checked, onChange, label, disabled, hint }: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode; disabled?: boolean; hint?: ReactNode }) {
  return (
    <label className={cx('flex cursor-pointer select-none items-start gap-2.5', disabled && 'cursor-not-allowed opacity-50')}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cx('relative mt-0.5 inline-flex h-4 w-7 shrink-0 items-center rounded-full border transition-colors', checked ? 'border-amber-400 bg-amber-500' : 'border-ink-500 bg-ink-650')}
      >
        <span className={cx('inline-block h-3 w-3 rounded-full bg-white shadow transition-transform', checked ? 'translate-x-3' : 'translate-x-0.5')} />
      </button>
      {(label || hint) && (
        <span className="text-xs leading-5 text-ink-100">
          {label}
          {hint && <span className="block text-2xs leading-4 text-ink-300">{hint}</span>}
        </span>
      )}
    </label>
  );
}

export function Field({ label, children, hint, error, htmlFor, hintId, className }: { label: ReactNode; children: ReactNode; hint?: ReactNode; error?: ReactNode; htmlFor?: string; hintId?: string; className?: string }) {
  return (
    <div className={cx('flex flex-col gap-1', className)}>
      {htmlFor ? (
        <label htmlFor={htmlFor} className="text-2xs font-medium uppercase tracking-wider text-ink-300">
          {label}
        </label>
      ) : (
        <span className="text-2xs font-medium uppercase tracking-wider text-ink-300">{label}</span>
      )}
      {children}
      {error ? (
        <span id={hintId} className="text-2xs text-red-300">
          {error}
        </span>
      ) : (
        hint && (
          <span id={hintId} className="text-2xs text-ink-300">
            {hint}
          </span>
        )
      )}
    </div>
  );
}

export const inputCls =
  'h-8 w-full rounded-md border border-ink-600 bg-ink-900 px-2.5 text-xs text-ink-50 placeholder:text-ink-400 focus:border-amber-500/70 focus:outline-none focus:ring-1 focus:ring-amber-500/30 disabled:opacity-50 aria-[invalid=true]:border-red-500/70';

export function Select<T extends string | number>({ id, name, value, onChange, options, className, disabled }: { id?: string; name?: string; value: T; onChange: (v: T) => void; options: { value: T; label: string }[]; className?: string; disabled?: boolean }) {
  return (
    <select
      id={id}
      name={name}
      className={cx(inputCls, 'cursor-pointer pr-6', className)}
      value={String(value)}
      disabled={disabled}
      onChange={(e) => {
        const o = options.find((x) => String(x.value) === e.target.value);
        if (o) onChange(o.value);
      }}
    >
      {options.map((o) => (
        <option key={String(o.value)} value={String(o.value)}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function Slider({ value, min, max, step, onChange, format, label, onCommit }: { value: number; min: number; max: number; step: number; onChange: (v: number) => void; format?: (v: number) => string; label?: ReactNode; onCommit?: (v: number) => void }) {
  return (
    <div className="flex flex-col gap-1">
      {label && (
        <div className="flex items-center justify-between text-2xs">
          <span className="font-medium uppercase tracking-wider text-ink-300">{label}</span>
          <span className="font-mono text-ink-100">{format ? format(value) : value}</span>
        </div>
      )}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        onMouseUp={(e) => onCommit?.(Number((e.target as HTMLInputElement).value))}
        onKeyUp={(e) => onCommit?.(Number((e.target as HTMLInputElement).value))}
        className="cf-range w-full"
      />
    </div>
  );
}

export function Segmented<T extends string>({ value, onChange, options, size = 'sm' }: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode; title?: string }[]; size?: 'xs' | 'sm' }) {
  return (
    <div className="inline-flex rounded-md border border-ink-600 bg-ink-900 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          title={o.title}
          onClick={() => onChange(o.value)}
          className={cx(
            'rounded px-2 font-medium transition-colors',
            size === 'xs' ? 'h-5 text-2xs' : 'h-6 text-xs',
            value === o.value ? 'bg-ink-650 text-amber-400' : 'text-ink-200 hover:text-ink-50',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Chip({ active, onClick, children, onRemove }: { active?: boolean; onClick?: () => void; children: ReactNode; onRemove?: () => void }) {
  return (
    <span
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => e.key === 'Enter' && onClick?.()}
      className={cx(
        'inline-flex h-7 cursor-pointer select-none items-center gap-1 rounded-md border px-2.5 text-xs font-medium transition-colors',
        active ? 'border-amber-500/60 bg-amber-500/15 text-amber-300' : 'border-ink-600 bg-ink-850 text-ink-200 hover:border-ink-500 hover:text-ink-50',
      )}
    >
      {children}
      {onRemove && (
        <X
          className="h-3 w-3 opacity-70 hover:opacity-100"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
        />
      )}
    </span>
  );
}

// ---------------------------------------------------------------- Modal
export function Modal({ open, onClose, title, children, footer, width = 520 }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; width?: number }) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const t = window.setTimeout(() => {
      if (dialogRef.current && !dialogRef.current.contains(document.activeElement)) {
        dialogRef.current.focus();
      }
    }, 0);
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', h);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener('keydown', h);
      prev?.focus?.();
    };
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-4 backdrop-blur-[2px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.12 }} onMouseDown={onClose}>
          <motion.div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            tabIndex={-1}
            className="flex max-h-[90vh] w-full flex-col overflow-hidden rounded-lg border border-ink-600 bg-ink-800 shadow-pop focus:outline-none"
            style={{ maxWidth: width }}
            initial={{ scale: 0.97, y: 6 }}
            animate={{ scale: 1, y: 0 }}
            exit={{ scale: 0.97, y: 6 }}
            transition={{ duration: 0.14 }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <header className="flex h-11 shrink-0 items-center justify-between border-b border-ink-600 px-4">
              <h2 id={titleId} className="text-sm font-semibold text-ink-50">
                {title}
              </h2>
              <IconButton title="Close" onClick={onClose}>
                <X className="h-4 w-4" aria-hidden="true" />
              </IconButton>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">{children}</div>
            {footer && <footer className="flex shrink-0 items-center justify-end gap-2 border-t border-ink-600 bg-ink-850 px-4 py-2.5">{footer}</footer>}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function ConfirmDialog({ open, title, message, confirmLabel = 'Confirm', danger, onConfirm, onClose, typed, children }: {
  open: boolean; title: string; message: ReactNode; confirmLabel?: string; danger?: boolean; onConfirm: () => void | Promise<void>; onClose: () => void; typed?: string; children?: ReactNode;
}) {
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState('');
  const typedId = useId();
  useEffect(() => {
    if (open) setText('');
  }, [open]);
  const ok = !typed || text === typed;
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      width={460}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant={danger ? 'danger' : 'primary'}
            loading={busy}
            disabled={!ok}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm();
                onClose();
              } finally {
                setBusy(false);
              }
            }}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm text-ink-100">
        <div>{message}</div>
        {children}
        {typed && (
          <Field label={`Type ${typed} to confirm`} htmlFor={typedId}>
            <input id={typedId} name="confirm_code" className={inputCls} value={text} onChange={(e) => setText(e.target.value)} autoCorrect="off" autoCapitalize="none" spellCheck={false} autoFocus />
          </Field>
        )}
      </div>
    </Modal>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded border border-ink-500 bg-ink-700 px-1 font-mono text-[10px] text-ink-100">{children}</kbd>;
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-2xs uppercase tracking-wider text-ink-300">{label}</div>
      <div className="truncate text-sm font-medium text-ink-50">{value}</div>
      {sub && <div className="truncate text-2xs text-ink-300">{sub}</div>}
    </div>
  );
}
