import { AlertTriangle, CheckCircle2, Cpu, FolderInput, HardDrive, MemoryStick, MonitorCog, Plus, Radio, Upload, WifiOff } from 'lucide-react';
import { useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { ExportRow } from '../components/ExportRow';
import { JobRow } from '../components/JobRow';
import { PageHeader } from '../components/PageHeader';
import { Thumb } from '../components/Thumb';
import { Badge, Button, EmptyState, ErrorState, LoadingBlock, Panel, ProgressBar, StatusBadge } from '../components/ui';
import { fmtDate, fmtDur } from '../lib/format';
import { useFetch, useInterval, useWsEvent } from '../lib/hooks';
import { useJobs } from '../stores/jobs';

export function DashboardPage() {
  const nav = useNavigate();
  const projects = useFetch(() => api.projects(), []);
  const exportsQ = useFetch(() => api.exports({ limit: 8 }), []);
  const status = useFetch(() => api.systemStatus(), []);
  const deps = useFetch(() => api.dependencies(), []);
  const jobs = useJobs((s) => s.jobs);
  useInterval(() => void status.reload(true), 5000);
  useWsEvent((m) => {
    if (m.type === 'project' || m.type === 'clips') void projects.reload(true);
    if (m.type === 'export') void exportsQ.reload(true);
    if (m.type === 'job' && m.data.kind === 'render' && (m.data.status === 'queued' || m.data.status === 'completed' || m.data.status === 'failed')) void exportsQ.reload(true);
  });
  const names = useMemo(() => Object.fromEntries((projects.data ?? []).map((p) => [p.id, p.name])), [projects.data]);
  const all = Object.values(jobs).sort((a, b) => b.created_at.localeCompare(a.created_at));
  const active = all.filter((j) => j.status === 'running' || j.status === 'queued');
  const problems = all.filter((j) => j.status === 'failed' || j.status === 'interrupted').slice(0, 6);
  const jobByExport = useMemo(() => {
    const m: Record<string, (typeof all)[number]> = {};
    for (const j of all) if (j.kind === 'render' && typeof j.params.export_id === 'string') m[j.params.export_id] ??= j;
    return m;
  }, [all]);
  const failingDeps = (deps.data?.checks ?? []).filter((c) => !c.ok);

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle="Local AI clipping studio — import a long video, get ranked short clips, refine and export."
        actions={
          <>
            <Button variant="secondary" size="md" icon={<Radio className="h-4 w-4 text-red-400" aria-hidden="true" />} onClick={() => nav('/live')}>
              Live Clipper
            </Button>
            <Button variant="secondary" size="md" icon={<FolderInput className="h-4 w-4" aria-hidden="true" />} onClick={() => nav('/new?source=local')}>
              Import Video
            </Button>
            <Button variant="primary" size="md" icon={<Plus className="h-4 w-4" aria-hidden="true" />} onClick={() => nav('/new')}>
              New Project
            </Button>
          </>
        }
      />
      <div className="grid grid-cols-1 gap-4 p-6 xl:grid-cols-[1fr_380px]">
        <div className="flex min-w-0 flex-col gap-4">
          {failingDeps.length > 0 && (
            <Panel title={<span className="flex items-center gap-1.5 text-amber-300"><AlertTriangle className="h-3.5 w-3.5" /> Dependency warnings</span>}>
              <div className="flex flex-col gap-2">
                {failingDeps.map((c) => (
                  <div key={c.name} className="flex items-start gap-2 text-xs">
                    <Badge tone={c.required ? 'red' : 'amber'}>{c.required ? 'required' : 'optional'}</Badge>
                    <div className="min-w-0">
                      <div className="font-medium text-ink-50">
                        {c.name} <span className="font-normal text-ink-300">— {c.detail}</span>
                      </div>
                      {c.fix && <div className="text-2xs text-ink-300">Fix: {c.fix}</div>}
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          )}
          <Panel title="Recent projects" actions={<Link to="/projects" className="text-2xs text-ink-300 hover:text-amber-400">View all</Link>}>
            {projects.loading && !projects.data ? (
              <LoadingBlock />
            ) : projects.error ? (
              <ErrorState message={projects.error} onRetry={() => projects.reload()} />
            ) : !projects.data?.length ? (
              <EmptyState icon={<Upload className="h-7 w-7" />} title="No projects yet" action={<Button variant="primary" onClick={() => nav('/new')}>Create your first project</Button>}>
                Import a podcast, interview or talking-head video to discover the best short clips.
              </EmptyState>
            ) : (
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 2xl:grid-cols-4">
                {projects.data.slice(0, 8).map((p) => (
                  <Link key={p.id} to={`/projects/${p.id}`} className="group overflow-hidden rounded-md border border-ink-600 bg-ink-850 transition-colors hover:border-ink-400">
                    <Thumb src={p.has_thumbnail ? `/api/projects/${p.id}/thumbnail?v=${encodeURIComponent(p.updated_at)}` : null} alt={p.name} className="aspect-video">
                      {p.media && <span className="absolute bottom-1 right-1 rounded bg-black/75 px-1 font-mono text-[10px] text-ink-50">{fmtDur(p.media.duration)}</span>}
                    </Thumb>
                    <div className="p-2">
                      <div className="truncate text-xs font-medium text-ink-50 group-hover:text-amber-300">{p.name}</div>
                      <div className="mt-1 flex items-center justify-between gap-1">
                        <StatusBadge status={p.status} />
                        <span className="text-2xs text-ink-300">{p.clip_count} clips · {fmtDate(p.updated_at)}</span>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </Panel>
          <Panel title="Recent exports">
            {exportsQ.loading && !exportsQ.data ? (
              <LoadingBlock />
            ) : exportsQ.error ? (
              <ErrorState message={exportsQ.error} onRetry={() => exportsQ.reload()} />
            ) : !exportsQ.data?.length ? (
              <EmptyState title="No exports yet">Rendered clips will appear here with playback, download and folder shortcuts.</EmptyState>
            ) : (
              <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
                {exportsQ.data.map((e) => (
                  <ExportRow key={e.id} ex={e} job={jobByExport[e.id]} onChanged={() => exportsQ.reload(true)} />
                ))}
              </div>
            )}
          </Panel>
        </div>
        <div className="flex flex-col gap-4">
          <Panel title="Processing queue" actions={<span className="text-2xs text-ink-300">{active.length} active</span>}>
            <div className="flex flex-col gap-2">
              {active.length === 0 && problems.length === 0 && <div className="py-4 text-center text-xs text-ink-300">Nothing processing right now.</div>}
              {active.map((j) => (
                <JobRow key={j.id} job={j} projectName={j.project_id ? names[j.project_id] : undefined} />
              ))}
              {problems.length > 0 && <div className="mt-1 text-2xs font-semibold uppercase tracking-wider text-ink-300">Needs attention</div>}
              {problems.map((j) => (
                <JobRow key={j.id} job={j} projectName={j.project_id ? names[j.project_id] : undefined} />
              ))}
            </div>
          </Panel>
          <SystemPanel status={status.data} error={status.error} />
          {deps.data && failingDeps.length === 0 && (
            <div className="flex items-center gap-2 rounded-lg border border-emerald-500/25 bg-emerald-500/5 px-3 py-2 text-xs text-emerald-300">
              <CheckCircle2 className="h-4 w-4" /> All {deps.data.checks.length} dependency checks passed
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Meter({ icon, label, value, pct, tone }: { icon: React.ReactNode; label: string; value: string; pct: number; tone?: 'amber' | 'green' | 'red' | 'blue' }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-2xs">
        <span className="flex items-center gap-1.5 text-ink-200">
          {icon}
          {label}
        </span>
        <span className="font-mono text-ink-100">{value}</span>
      </div>
      <ProgressBar value={pct} tone={tone ?? (pct > 0.9 ? 'red' : pct > 0.7 ? 'amber' : 'green')} />
    </div>
  );
}

function SystemPanel({ status, error }: { status: import('../types').SystemStatus | null; error: string | null }) {
  if (error && !status) return <Panel title="System"><ErrorState message={error} /></Panel>;
  if (!status) return <Panel title="System"><LoadingBlock /></Panel>;
  const l = status.live;
  const gpu = l.gpus[0];
  return (
    <Panel title="System resources" actions={status.offline_mode ? <Badge tone="green"><WifiOff className="h-3 w-3" /> offline</Badge> : null}>
      <div className="flex flex-col gap-3">
        <Meter icon={<Cpu className="h-3 w-3" />} label={`CPU · ${status.hardware.cpu_cores} threads`} value={`${l.cpu_percent.toFixed(0)}%`} pct={l.cpu_percent / 100} />
        <Meter icon={<MemoryStick className="h-3 w-3" />} label="RAM" value={`${l.ram_used_gb.toFixed(1)} / ${l.ram_total_gb.toFixed(1)} GB`} pct={l.ram_percent / 100} />
        {gpu ? (
          <>
            <Meter icon={<MonitorCog className="h-3 w-3" />} label={`GPU · ${gpu.name}`} value={`${gpu.utilization}%`} pct={gpu.utilization / 100} />
            <Meter icon={<MonitorCog className="h-3 w-3" />} label="VRAM" value={`${(gpu.vram_used_mb / 1024).toFixed(1)} / ${(gpu.vram_total_mb / 1024).toFixed(1)} GB`} pct={gpu.vram_used_mb / Math.max(1, gpu.vram_total_mb)} />
          </>
        ) : (
          <div className="text-2xs text-ink-300">No NVIDIA GPU detected — processing runs on CPU.</div>
        )}
        <Meter icon={<HardDrive className="h-3 w-3" />} label="Disk free (projects)" value={`${l.disk_free_gb.toFixed(0)} GB free`} pct={1 - l.disk_free_gb / Math.max(1, l.disk_total_gb)} />
        <div className="flex items-center justify-between border-t border-ink-600 pt-2 text-2xs">
          <span className="text-ink-300">Whisper model</span>
          <span className="flex items-center gap-1.5">
            <span className="font-mono text-ink-100">{status.whisper_model}</span>
            {status.whisper_installed ? <Badge tone="green">installed</Badge> : <Link to="/settings#models"><Badge tone="red">not installed</Badge></Link>}
          </span>
        </div>
      </div>
    </Panel>
  );
}
