import { Cpu, Download, HardDrive, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { api, errMsg } from '../../api';
import { useFetch } from '../../lib/hooks';
import { useJobs } from '../../stores/jobs';
import { useSettings } from '../../stores/settings';
import { toast } from '../../stores/toast';
import { Badge, Button, ConfirmDialog, ErrorState, LoadingBlock, Panel, ProgressBar, Stat } from '../ui';

export function ModelsSection() {
  const q = useFetch(() => api.models(), []);
  const jobs = useJobs((s) => s.jobs);
  const { settings, save } = useSettings();
  const [confirm, setConfirm] = useState<null | { kind: 'whisper' | 'vision' | 'ollama'; name: string; size: string; extra?: string }>(null);
  const [del, setDel] = useState<null | { kind: string; name: string }>(null);
  const dlJobs = useMemo(() => Object.values(jobs).filter((j) => j.kind === 'model_download'), [jobs]);
  const doneKey = dlJobs.filter((j) => j.status !== 'running' && j.status !== 'queued').map((j) => `${j.id}:${j.status}`).join(',');
  useEffect(() => {
    if (doneKey) void q.reload(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doneKey]);
  const activeFor = (kind: string, name: string) => dlJobs.find((j) => (j.status === 'running' || j.status === 'queued') && j.params.kind === kind && j.params.name === name);
  const failedFor = (kind: string, name: string) => dlJobs.find((j) => j.status === 'failed' && j.params.kind === kind && j.params.name === name);
  const start = async (kind: 'whisper' | 'vision' | 'ollama', name: string) => {
    try {
      await api.downloadModel(kind, name);
      toast.info(`Downloading ${name}`);
    } catch (e) {
      toast.error('Download failed to start', errMsg(e));
    }
  };
  const remove = async () => {
    if (!del) return;
    try {
      await api.deleteModel(del.kind, del.name);
      toast.success(`Deleted ${del.name}`);
      await q.reload(true);
    } catch (e) {
      toast.error('Delete failed', errMsg(e));
    }
  };
  if (q.loading && !q.data) return <LoadingBlock label="Checking models and hardware…" />;
  if (q.error || !q.data) return <ErrorState message={q.error ?? 'Unavailable'} onRetry={() => q.reload()} />;
  const m = q.data;
  const progress = (kind: string, name: string) => {
    const j = activeFor(kind, name);
    if (!j) return null;
    return (
      <div className="mt-1.5">
        <ProgressBar value={j.progress} indeterminate={j.status === 'queued'} />
        <div className="mt-0.5 flex justify-between text-[10px] text-ink-300">
          <span className="truncate">{j.message}</span>
          <span className="font-mono">{(j.progress * 100).toFixed(0)}%</span>
        </div>
      </div>
    );
  };
  return (
    <div className="flex flex-col gap-4">
      <Panel title="Hardware & engine">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="CPU" value={`${m.hardware.cpu_cores} threads`} sub={m.hardware.cpu} />
          <Stat label="RAM" value={`${m.hardware.ram_gb} GB`} />
          <Stat label="GPU" value={m.hardware.gpus[0]?.name ?? 'None (CPU only)'} sub={m.hardware.gpus[0] ? `${m.hardware.gpu_vram_gb} GB VRAM · driver ${m.hardware.gpus[0].driver ?? '?'}` : m.hardware.all_gpus.join(', ')} />
          <Stat label="Free disk (models)" value={`${m.disk_free_gb} GB`} />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-2xs">
          <Badge tone={m.engine.available ? 'green' : 'red'}>
            <Cpu className="h-3 w-3" /> {m.engine.available ? m.engine.engine : `ASR engine unavailable: ${m.engine.error}`}
          </Badge>
          <Badge tone={m.cuda.usable ? 'green' : 'default'}>{m.cuda.usable ? 'CUDA usable' : `CUDA: ${m.cuda.message}`}</Badge>
          <span className="text-ink-300">
            Recommended Whisper model for this PC: <b className="text-amber-300">{m.recommended_whisper}</b>
          </span>
        </div>
      </Panel>
      <Panel title="Whisper speech recognition models">
        <div className="flex flex-col gap-2">
          {m.whisper.map((w) => {
            const size = w.size_mb >= 1000 ? `${(w.size_mb / 1000).toFixed(1)} GB` : `${w.size_mb} MB`;
            const failed = failedFor('whisper', w.name);
            return (
              <div key={w.name} className={`rounded-md border p-2.5 ${settings?.whisper_model === w.name ? 'border-amber-500/50 bg-amber-500/5' : 'border-ink-600 bg-ink-850'}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs font-semibold text-ink-50">{w.name}</span>
                  {w.installed ? <Badge tone="green">installed</Badge> : <Badge>not downloaded</Badge>}
                  {settings?.whisper_model === w.name && <Badge tone="amber">default</Badge>}
                  {w.name === m.recommended_whisper && <Badge tone="blue">recommended</Badge>}
                  {!w.fits_ram && <Badge tone="red">needs more RAM</Badge>}
                  {w.fits_gpu ? <Badge tone="green">fits GPU</Badge> : <Badge>CPU</Badge>}
                  <span className="text-2xs text-ink-300">
                    {size} · {w.ram_gb} GB RAM · {w.vram_gb} GB VRAM · {w.quality} · {w.speed}
                  </span>
                  <div className="flex-1" />
                  {w.installed && settings?.whisper_model !== w.name && (
                    <Button size="xs" variant="subtle" onClick={() => save({ whisper_model: w.name })}>
                      Set default
                    </Button>
                  )}
                  {!w.installed && !activeFor('whisper', w.name) && (
                    <Button size="xs" variant="primary" icon={<Download className="h-3 w-3" />} disabled={!w.disk_ok} title={w.disk_ok ? undefined : 'Not enough disk space'} onClick={() => setConfirm({ kind: 'whisper', name: w.name, size, extra: `Needs about ${w.ram_gb} GB RAM (${w.vram_gb} GB VRAM on GPU).` })}>
                      Download
                    </Button>
                  )}
                  {w.installed && (
                    <Button size="xs" variant="ghost" icon={<Trash2 className="h-3 w-3" />} onClick={() => setDel({ kind: 'whisper', name: w.name })}>
                      Delete
                    </Button>
                  )}
                </div>
                {progress('whisper', w.name)}
                {failed && !w.installed && !activeFor('whisper', w.name) && <div className="mt-1 text-2xs text-red-300">Last download failed: {failed.error}</div>}
              </div>
            );
          })}
        </div>
      </Panel>
      <Panel title="Vision models">
        {m.vision.map((v) => (
          <div key={v.name} className="rounded-md border border-ink-600 bg-ink-850 p-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-medium text-ink-50">{v.label}</span>
              {v.installed ? <Badge tone="green">installed</Badge> : <Badge>not installed</Badge>}
              <span className="text-2xs text-ink-300">{v.size_mb} MB · fallback: {v.fallback}</span>
              <div className="flex-1" />
              {!v.installed && !activeFor('vision', v.name) && (
                <Button size="xs" variant="primary" icon={<Download className="h-3 w-3" />} onClick={() => start('vision', v.name)}>
                  Download
                </Button>
              )}
              {v.installed && (
                <Button size="xs" variant="ghost" icon={<Trash2 className="h-3 w-3" />} onClick={() => setDel({ kind: 'vision', name: v.name })}>
                  Delete
                </Button>
              )}
            </div>
            {progress('vision', v.name)}
          </div>
        ))}
      </Panel>
      <Panel title="Ollama (local LLM)">
        {m.ollama.error ? (
          <div className="text-xs text-amber-300">{m.ollama.error}</div>
        ) : (
          <div className="text-xs text-ink-200">
            Installed models: {m.ollama.models.length ? m.ollama.models.map((x) => <Badge key={x} className="mr-1">{x}</Badge>) : <span className="text-ink-300">none</span>}
          </div>
        )}
        <div className="mt-3 text-2xs uppercase tracking-wider text-ink-300">Suggested models</div>
        <div className="mt-1.5 flex flex-col gap-1.5">
          {m.ollama.suggested.map((s) => {
            const installed = m.ollama.models.some((x) => x === s.name || x.startsWith(`${s.name}`));
            return (
              <div key={s.name} className="rounded-md border border-ink-600 bg-ink-850 p-2">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-ink-50">{s.name}</span>
                  <span className="text-2xs text-ink-300">
                    {s.size_gb} GB · {s.ram_gb} GB RAM
                  </span>
                  {installed && <Badge tone="green">installed</Badge>}
                  <div className="flex-1" />
                  {!installed && !activeFor('ollama', s.name) && (
                    <Button size="xs" variant="subtle" icon={<Download className="h-3 w-3" />} disabled={!!m.ollama.error} onClick={() => setConfirm({ kind: 'ollama', name: s.name, size: `${s.size_gb} GB`, extra: `Pulled through your local Ollama server; needs ~${s.ram_gb} GB RAM.` })}>
                      Pull
                    </Button>
                  )}
                </div>
                {progress('ollama', s.name)}
              </div>
            );
          })}
        </div>
      </Panel>
      <ConfirmDialog
        open={!!confirm}
        onClose={() => setConfirm(null)}
        title={`Download ${confirm?.name}?`}
        confirmLabel="Download"
        message={
          <span className="flex items-start gap-2">
            <HardDrive className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
            <span>
              This downloads about <b>{confirm?.size}</b>. Free disk space: <b>{m.disk_free_gb} GB</b>. {confirm?.extra}
            </span>
          </span>
        }
        onConfirm={() => (confirm ? start(confirm.kind, confirm.name) : undefined)}
      />
      <ConfirmDialog open={!!del} onClose={() => setDel(null)} title={`Delete ${del?.name}?`} danger confirmLabel="Delete" message="The model files are removed from disk. You can download them again later." onConfirm={remove} />
    </div>
  );
}
