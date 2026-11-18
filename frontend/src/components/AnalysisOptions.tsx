import { Download, Plus } from 'lucide-react';
import { useEffect, useId, useMemo, useState } from 'react';
import { api, errMsg, type AnalyzeParams } from '../api';
import { useFetch } from '../lib/hooks';
import { useJobs } from '../stores/jobs';
import { toast } from '../stores/toast';
import type { Aspect, ModelsStatus, Preset, Settings } from '../types';
import { ASPECTS } from '../types';
import { Badge, Button, Chip, ConfirmDialog, Field, inputCls, ProgressBar, Segmented, Select, Slider, Toggle } from './ui';

export const DURATION_PRESETS = [30, 45, 60, 90, 120, 150, 180];

export const SPOKEN_LANGUAGE_OPTIONS = [
  { value: 'auto', label: 'Auto-detect language' },
  { value: 'hinglish', label: 'Hinglish — Hindi + English (Roman script)' },
  { value: 'hi', label: 'Hindi — हिन्दी (Devanagari script)' },
  { value: 'en', label: 'English' },
  { value: 'en_translate', label: 'English — Translate from Hindi / other audio' },
  { value: 'es', label: 'Spanish (es)' },
  { value: 'fr', label: 'French (fr)' },
  { value: 'de', label: 'German (de)' },
  { value: 'pt', label: 'Portuguese (pt)' },
  { value: 'it', label: 'Italian (it)' },
  { value: 'ja', label: 'Japanese (ja)' },
  { value: 'ko', label: 'Korean (ko)' },
  { value: 'zh', label: 'Chinese (zh)' },
  { value: 'ar', label: 'Arabic (ar)' },
  { value: 'ru', label: 'Russian (ru)' },
];

export interface AnalysisOptionsValue {
  duration_targets: number[];
  duration_tolerance: number;
  whisper_model: string;
  language: string;
  analysis_quality: 'fast' | 'balanced' | 'high';
  preset_id: string;
  aspect: Aspect;
  auto_analyze: boolean;
}

export function defaultAnalysisOptions(s: Settings | null): AnalysisOptionsValue {
  return {
    duration_targets: s?.duration_targets?.length ? s.duration_targets : [30, 60],
    duration_tolerance: s?.duration_tolerance ?? 0.2,
    whisper_model: s?.whisper_model ?? 'base',
    language: s?.transcription_language ?? 'auto',
    analysis_quality: s?.analysis_quality ?? 'balanced',
    preset_id: s?.default_preset ?? 'podcast_pro',
    aspect: s?.default_aspect ?? '9:16',
    auto_analyze: true,
  };
}

export function toAnalyzeParams(v: AnalysisOptionsValue): AnalyzeParams {
  return {
    duration_targets: v.duration_targets,
    duration_tolerance: v.duration_tolerance,
    whisper_model: v.whisper_model,
    language: v.language,
    analysis_quality: v.analysis_quality,
    preset_id: v.preset_id,
    aspect: v.aspect,
  };
}

export function DurationTargets({ value, onChange }: { value: number[]; onChange: (v: number[]) => void }) {
  const [custom, setCustom] = useState('');
  const toggle = (d: number) => onChange(value.includes(d) ? value.filter((x) => x !== d) : [...value, d].sort((a, b) => a - b));
  const extra = value.filter((v) => !DURATION_PRESETS.includes(v));
  const addCustom = () => {
    const n = Math.round(Number(custom));
    if (!n || n < 5 || n > 900) {
      toast.warning('Invalid duration', 'Custom targets must be between 5 and 900 seconds.');
      return;
    }
    if (!value.includes(n)) onChange([...value, n].sort((a, b) => a - b));
    setCustom('');
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {DURATION_PRESETS.map((d) => (
        <Chip key={d} active={value.includes(d)} onClick={() => toggle(d)}>
          {d < 60 ? `${d}s` : d % 60 === 0 ? `${d / 60} min` : `${Math.floor(d / 60)}:${String(d % 60).padStart(2, '0')}`}
        </Chip>
      ))}
      {extra.map((d) => (
        <Chip key={d} active onRemove={() => onChange(value.filter((x) => x !== d))}>
          {d}s
        </Chip>
      ))}
      <div className="flex items-center gap-1">
        <input
          className={`${inputCls} h-7 w-20`}
          type="number"
          min={5}
          max={900}
          placeholder="Custom s"
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && addCustom()}
        />
        <Button size="sm" variant="subtle" icon={<Plus className="h-3 w-3" />} onClick={addCustom} disabled={!custom}>
          Add
        </Button>
      </div>
    </div>
  );
}

/** Whisper model picker with install state, size/RAM info, and live download progress. */
export function WhisperModelSelect({ value, onChange, models, reloadModels }: { value: string; onChange: (v: string) => void; models: ModelsStatus | null; reloadModels: () => void }) {
  const jobs = useJobs((s) => s.jobs);
  const [confirm, setConfirm] = useState<string | null>(null);
  const dl = useMemo(
    () => Object.values(jobs).find((j) => j.kind === 'model_download' && (j.params as { name?: string }).name === value && (j.status === 'running' || j.status === 'queued')),
    [jobs, value],
  );
  const lastDone = useMemo(
    () => Object.values(jobs).filter((j) => j.kind === 'model_download' && j.status === 'completed').map((j) => j.id).join(','),
    [jobs],
  );
  useEffect(() => {
    if (lastDone) reloadModels();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastDone]);
  if (!models) return <div className="text-2xs text-ink-300">Loading models…</div>;
  const sel = models.whisper.find((m) => m.name === value);
  const start = async (name: string) => {
    try {
      await api.downloadModel('whisper', name);
      toast.info(`Downloading Whisper '${name}'`);
    } catch (e) {
      toast.error('Download failed to start', errMsg(e));
    }
  };
  const confirmModel = models.whisper.find((m) => m.name === confirm);
  return (
    <div className="flex flex-col gap-1.5">
      <Select
        value={value}
        onChange={onChange}
        options={models.whisper.map((m) => ({
          value: m.name,
          label: `${m.name} — ${m.quality}, ${m.size_mb >= 1000 ? `${(m.size_mb / 1000).toFixed(1)} GB` : `${m.size_mb} MB`}, ${m.ram_gb} GB RAM${m.installed ? ' ✓' : ''}${m.name === models.recommended_whisper ? ' (recommended)' : ''}`,
        }))}
      />
      {sel && (
        <div className="flex flex-wrap items-center gap-1.5 text-2xs text-ink-300">
          {sel.installed ? <Badge tone="green">installed</Badge> : <Badge tone="red">not downloaded</Badge>}
          {sel.fits_gpu ? <Badge tone="blue">GPU ok</Badge> : <Badge>CPU</Badge>}
          {!sel.fits_ram && <Badge tone="amber">may exceed RAM</Badge>}
          <span>{sel.speed}</span>
          {!sel.installed && !dl && (
            <Button size="xs" variant="primary" icon={<Download className="h-3 w-3" />} onClick={() => (sel.size_mb > 400 ? setConfirm(sel.name) : start(sel.name))} disabled={!sel.disk_ok}>
              Download
            </Button>
          )}
        </div>
      )}
      {dl && (
        <div>
          <ProgressBar value={dl.progress} />
          <div className="mt-0.5 flex justify-between text-2xs text-ink-300">
            <span className="truncate">{dl.message}</span>
            <span className="font-mono">{(dl.progress * 100).toFixed(0)}%</span>
          </div>
        </div>
      )}
      <ConfirmDialog
        open={!!confirm}
        onClose={() => setConfirm(null)}
        title="Large model download"
        confirmLabel="Download"
        message={
          confirmModel ? (
            <>
              Whisper <b>{confirmModel.name}</b> is about <b>{confirmModel.size_mb >= 1000 ? `${(confirmModel.size_mb / 1000).toFixed(1)} GB` : `${confirmModel.size_mb} MB`}</b> and needs ~{confirmModel.ram_gb} GB RAM ({confirmModel.vram_gb} GB VRAM on GPU). Free disk: {models.disk_free_gb} GB. Download from Hugging Face now?
            </>
          ) : null
        }
        onConfirm={() => (confirm ? start(confirm) : undefined)}
      />
    </div>
  );
}

export function AnalysisOptions({ value, onChange, showAuto = true, compact }: { value: AnalysisOptionsValue; onChange: (v: AnalysisOptionsValue) => void; showAuto?: boolean; compact?: boolean }) {
  const uid = useId();
  const langId = `${uid}-lang`;
  const langHintId = `${uid}-lang-hint`;
  const models = useFetch(() => api.models(), []);
  const presets = useFetch<Preset[]>(() => api.presets(), []);
  const set = <K extends keyof AnalysisOptionsValue>(k: K, v: AnalysisOptionsValue[K]) => onChange({ ...value, [k]: v });
  return (
    <div className={compact ? 'flex flex-col gap-3' : 'grid grid-cols-1 gap-4 lg:grid-cols-2'}>
      <Field label="Clip duration targets" className="lg:col-span-2" hint={value.duration_targets.length === 0 ? 'Select at least one target' : `${value.duration_targets.length} target(s) selected`}>
        <DurationTargets value={value.duration_targets} onChange={(v) => set('duration_targets', v)} />
      </Field>
      <Slider label="Duration tolerance" value={value.duration_tolerance} min={0.05} max={0.6} step={0.05} format={(v) => `±${Math.round(v * 100)}%`} onChange={(v) => set('duration_tolerance', v)} />
      <Field label="Analysis quality">
        <Segmented
          value={value.analysis_quality}
          onChange={(v) => set('analysis_quality', v)}
          options={[
            { value: 'fast', label: 'Fast', title: 'Lower frame sampling, fastest' },
            { value: 'balanced', label: 'Balanced' },
            { value: 'high', label: 'High', title: 'Denser face tracking and scene detection' },
          ]}
        />
      </Field>
      <Field label="Speech recognition model">
        <WhisperModelSelect value={value.whisper_model} onChange={(v) => set('whisper_model', v)} models={models.data} reloadModels={() => models.reload(true)} />
      </Field>
      <Field
        label="Spoken / caption language"
        htmlFor={langId}
        hintId={langHintId}
        hint="Pick Hinglish for Hindi + English in Roman script, Hindi for Devanagari (हिन्दी), or English — Translate."
      >
        <Select
          id={langId}
          name="language"
          aria-describedby={langHintId}
          value={SPOKEN_LANGUAGE_OPTIONS.some((o) => o.value === value.language) ? value.language : 'auto'}
          onChange={(v) => set('language', v)}
          options={SPOKEN_LANGUAGE_OPTIONS}
        />
      </Field>
      <Field label="Editing preset" hint={presets.data?.find((p) => p.id === value.preset_id)?.description}>
        <Select value={value.preset_id} onChange={(v) => set('preset_id', v)} options={(presets.data ?? [{ id: value.preset_id, name: value.preset_id } as Preset]).map((p) => ({ value: p.id, label: p.name + (p.builtin ? '' : ' (custom)') }))} />
      </Field>
      <Field label="Aspect ratio">
        <Segmented value={value.aspect} onChange={(v) => set('aspect', v)} options={ASPECTS.map((a) => ({ value: a, label: a }))} />
      </Field>
      {showAuto && (
        <div className="flex items-end lg:col-span-2">
          <Toggle checked={value.auto_analyze} onChange={(v) => set('auto_analyze', v)} label="Auto-analyze after import" hint="Starts transcription, analysis and clip discovery as soon as the import finishes." />
        </div>
      )}
    </div>
  );
}
