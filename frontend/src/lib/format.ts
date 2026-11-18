export function fmtTime(sec: number | null | undefined, withMs = false): string {
  if (sec === null || sec === undefined || !isFinite(sec)) return '--:--';
  const neg = sec < 0;
  let s = Math.abs(sec);
  const h = Math.floor(s / 3600);
  s -= h * 3600;
  const m = Math.floor(s / 60);
  s -= m * 60;
  const whole = Math.floor(s);
  const frac = Math.floor((s - whole) * 10);
  const core = `${h > 0 ? `${h}:${String(m).padStart(2, '0')}` : m}:${String(whole).padStart(2, '0')}${withMs ? `.${frac}` : ''}`;
  return neg ? `-${core}` : core;
}

export function fmtDur(sec: number | null | undefined): string {
  if (sec === null || sec === undefined || !isFinite(sec)) return '—';
  if (sec < 60) return `${sec.toFixed(sec < 10 ? 1 : 0)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec - m * 60);
  if (m < 60) return `${m}m ${String(s).padStart(2, '0')}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${String(m % 60).padStart(2, '0')}m`;
}

export function fmtBytes(n: number | null | undefined): string {
  if (!n && n !== 0) return '—';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${u[i]}`;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  // backend returns naive UTC timestamps
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  if (isNaN(d.getTime())) return iso;
  const now = Date.now();
  const diff = (now - d.getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} d ago`;
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

export function clamp(v: number, a: number, b: number): number {
  return Math.max(a, Math.min(b, v));
}

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ');
}

export function titleCase(s: string): string {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function scoreColor(score: number): string {
  if (score >= 75) return '#4ade80';
  if (score >= 60) return '#ffbf47';
  if (score >= 45) return '#fb923c';
  return '#f87171';
}

export function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

export function deepClone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}
