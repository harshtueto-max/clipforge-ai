import { AnimatePresence, motion } from 'framer-motion';
import { Activity, Film, FolderKanban, LayoutDashboard, Music2, Plus, Radio, Server, Settings as SettingsIcon, Wifi, WifiOff, Zap } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { getBackendOrigin, isRemoteHost, setBackendOrigin } from '../api';
import { cx } from '../lib/format';
import { useJobs } from '../stores/jobs';
import { useSettings } from '../stores/settings';
import { JobRow } from './JobRow';
import { Button, EmptyState, Field, inputCls, Modal } from './ui';

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/new', label: 'New Project', icon: Plus },
  { to: '/live', label: 'Live Clipper', icon: Radio },
  { to: '/projects', label: 'Projects', icon: FolderKanban },
  { to: '/clips', label: 'Clip Library', icon: Film },
  { to: '/audio', label: 'Audio Library', icon: Music2 },
  { to: '/settings', label: 'Settings', icon: SettingsIcon },
];

export function Layout() {
  const location = useLocation();
  const isEditor = location.pathname.startsWith('/editor');
  return (
    <div className="flex h-full overflow-hidden">
      <Sidebar collapsed={isEditor} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className={cx('min-h-0 flex-1', isEditor ? 'overflow-hidden' : 'overflow-y-auto')}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function Sidebar({ collapsed }: { collapsed: boolean }) {
  return (
    <aside className={cx('flex shrink-0 flex-col border-r border-ink-600 bg-ink-850 transition-[width] duration-150', collapsed ? 'w-[52px]' : 'w-[200px]')}>
      <div className="flex h-11 items-center gap-2 border-b border-ink-600 px-3.5">
        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-amber-500 text-ink-950">
          <Zap className="h-3.5 w-3.5" strokeWidth={2.5} />
        </div>
        {!collapsed && (
          <div className="leading-tight">
            <div className="text-[13px] font-semibold tracking-tight text-ink-50">ClipForge</div>
            <div className="text-[9px] font-medium uppercase tracking-[0.18em] text-ink-300">AI Studio</div>
          </div>
        )}
      </div>
      <nav className="flex flex-1 flex-col gap-0.5 p-2">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            title={n.label}
            className={({ isActive }) =>
              cx(
                'group flex h-8 items-center gap-2.5 rounded-md px-2.5 text-xs font-medium transition-colors',
                isActive ? 'bg-ink-700 text-ink-50 shadow-[inset_2px_0_0_0_#ffab1a]' : 'text-ink-200 hover:bg-ink-750 hover:text-ink-50',
              )
            }
          >
            <n.icon className="h-4 w-4 shrink-0" />
            {!collapsed && n.label}
          </NavLink>
        ))}
      </nav>
      {!collapsed && <div className="border-t border-ink-600 p-3 text-[10px] leading-relaxed text-ink-400">All processing runs locally on this PC.</div>}
    </aside>
  );
}

function TopBar() {
  const uid = useId();
  const engineInputId = `${uid}-engine-url`;
  const engineHintId = `${uid}-engine-hint`;
  const { settings, load, save } = useSettings();
  const connected = useJobs((s) => s.connected);
  const backendDown = useJobs((s) => s.backendDown);
  const jobs = useJobs((s) => s.jobs);
  const active = Object.values(jobs).filter((j) => j.status === 'queued' || j.status === 'running');
  const [open, setOpen] = useState(false);
  const [engineModal, setEngineModal] = useState(false);
  const [engineUrl, setEngineUrl] = useState(() => getBackendOrigin() || 'http://127.0.0.1:8765');
  const [engineErr, setEngineErr] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const remote = isRemoteHost();
  useEffect(() => {
    if (!settings) void load();
  }, [settings, load]);
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener('mousedown', h);
    return () => window.removeEventListener('mousedown', h);
  }, []);
  const offline = settings?.offline_mode ?? false;

  const saveEngine = (e: React.FormEvent) => {
    e.preventDefault();
    const v = engineUrl.trim();
    if (v && !/^https?:\/\/[^\s/]+/i.test(v)) {
      setEngineErr('Enter a valid http:// or https:// backend URL (e.g. http://127.0.0.1:8765).');
      return;
    }
    setBackendOrigin(v);
    setEngineModal(false);
    window.location.reload();
  };

  return (
    <header className="flex h-11 shrink-0 items-center justify-end gap-2 border-b border-ink-600 bg-ink-850 px-3">
      {backendDown && (
        <button
          type="button"
          onClick={() => setEngineModal(true)}
          className="mr-auto rounded border border-red-500/40 bg-red-500/10 px-2.5 py-1 text-left text-2xs text-red-300 hover:bg-red-500/20"
        >
          Backend unreachable ({getBackendOrigin() || '127.0.0.1:8765'}) — start <b>start.bat</b> on your PC or click to set Engine URL
        </button>
      )}
      {remote && (
        <button
          type="button"
          onClick={() => {
            setEngineUrl(getBackendOrigin() || 'http://127.0.0.1:8765');
            setEngineErr(null);
            setEngineModal(true);
          }}
          className="flex min-h-7 items-center gap-1.5 rounded-md border border-ink-600 px-2 py-0.5 text-2xs text-ink-200 hover:border-ink-400 hover:text-ink-50"
          title="Configure local PC GPU or cloud backend URL"
        >
          <Server className="h-3.5 w-3.5 text-amber-400" aria-hidden="true" />
          <span className="max-w-[160px] truncate font-mono">{(getBackendOrigin() || 'http://127.0.0.1:8765').replace(/^https?:\/\//, '')}</span>
        </button>
      )}
      <button
        onClick={() => settings && void save({ offline_mode: !offline }, true)}
        title={offline ? 'Offline mode is ON: no external network requests. Click to disable.' : 'Offline mode is OFF. Click to block all external requests.'}
        className={cx(
          'flex h-7 items-center gap-1.5 rounded-md border px-2 text-2xs font-semibold uppercase tracking-wider transition-colors',
          offline ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' : 'border-ink-600 text-ink-200 hover:text-ink-50',
        )}
      >
        {offline ? <WifiOff className="h-3.5 w-3.5" /> : <Wifi className="h-3.5 w-3.5" />}
        {offline ? 'Offline' : 'Online'}
      </button>
      <div className="relative" ref={ref}>
        <button
          onClick={() => setOpen((v) => !v)}
          className={cx('flex h-7 items-center gap-1.5 rounded-md border px-2 text-xs transition-colors', active.length ? 'border-amber-500/40 bg-amber-500/10 text-amber-300' : 'border-ink-600 text-ink-200 hover:text-ink-50')}
          title="Processing queue"
        >
          <Activity className={cx('h-3.5 w-3.5', active.length > 0 && 'animate-pulse')} />
          {active.length ? `${active.length} active` : 'Idle'}
        </button>
        <AnimatePresence>
          {open && (
            <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.1 }} className="absolute right-0 top-9 z-40 w-[380px] rounded-lg border border-ink-600 bg-ink-800 p-2 shadow-pop">
              <div className="mb-2 px-1 text-2xs font-semibold uppercase tracking-wider text-ink-300">Processing queue</div>
              <div className="flex max-h-[60vh] flex-col gap-1.5 overflow-y-auto">
                {active.length === 0 ? <EmptyState title="No active jobs" /> : active.map((j) => <JobRow key={j.id} job={j} compact />)}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      <span className={cx('flex items-center gap-1.5 text-2xs', connected ? 'text-ink-300' : 'text-amber-400')} title={connected ? 'Live updates connected' : 'Live updates disconnected — polling every 3s'}>
        <span className={cx('h-1.5 w-1.5 rounded-full', connected ? 'bg-emerald-400' : 'bg-amber-400')} />
        {connected ? 'Live' : 'Polling'}
      </span>

      <Modal open={engineModal} onClose={() => setEngineModal(false)} title="ClipForge GPU / Media Engine Connection" width={520}>
        <form onSubmit={saveEngine} noValidate className="flex flex-col gap-3">
          <p className="text-xs leading-relaxed text-ink-200">
            The web studio UI runs on Vercel while heavy FFmpeg rendering, NVENC GPU encoding, Live DVR capture, and Whisper AI run on your engine:
          </p>
          <Field
            label="Backend Engine URL"
            htmlFor={engineInputId}
            hintId={engineHintId}
            error={engineErr}
            hint={!engineErr ? 'Use http://127.0.0.1:8765 on your Windows PC (with start.bat running), or paste an HTTPS Cloudflare Tunnel / cloud backend URL for remote devices.' : undefined}
          >
            <input
              id={engineInputId}
              name="backend_url"
              type="url"
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="none"
              spellCheck={false}
              aria-invalid={engineErr ? true : undefined}
              aria-describedby={engineHintId}
              className={`${inputCls} font-mono`}
              value={engineUrl}
              onChange={(e) => {
                setEngineUrl(e.target.value);
                if (engineErr) setEngineErr(null);
              }}
            />
          </Field>
          <div className="flex items-center justify-between gap-2 pt-2">
            <Button
              type="button"
              size="xs"
              variant="ghost"
              onClick={() => {
                setEngineUrl('http://127.0.0.1:8765');
                setEngineErr(null);
              }}
            >
              Reset to Local PC (127.0.0.1:8765)
            </Button>
            <div className="flex items-center gap-2">
              <Button type="button" variant="ghost" onClick={() => setEngineModal(false)}>
                Cancel
              </Button>
              <Button type="submit" variant="primary">
                Save & Connect
              </Button>
            </div>
          </div>
        </form>
      </Modal>
    </header>
  );
}
