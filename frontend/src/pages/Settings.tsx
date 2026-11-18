import {
  AlertTriangle, CheckCircle2, Copy, Cpu, FolderOpen, HardDrive, Layers, Lock, Pencil, Plus, RefreshCw, RotateCcw,
  ShieldCheck, Sliders, Sparkles, Trash2, WifiOff, Wrench, XCircle,
} from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { api, errMsg } from '../api';
import { SPOKEN_LANGUAGE_OPTIONS } from '../components/AnalysisOptions';
import { ModelsSection } from '../components/settings/ModelsSection';
import { PresetEditorModal } from '../components/settings/PresetEditorModal';
import { ProvidersSection } from '../components/settings/ProvidersSection';
import {
  Badge, Button, Chip, ConfirmDialog, ErrorState, Field, IconButton, inputCls, LoadingBlock, Panel, Select, Segmented, Slider, Toggle,
} from '../components/ui';
import { titleCase } from '../lib/format';
import { useFetch } from '../lib/hooks';
import { useJobs } from '../stores/jobs';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';
import type { Aspect, Preset, Settings } from '../types';
import { ASPECTS, CATEGORIES, DIM_LABELS, SCORE_DIMENSIONS } from '../types';

type TabId = 'general' | 'models' | 'providers' | 'discovery' | 'presets' | 'diagnostics' | 'privacy';

const TABS: { id: TabId; label: string; icon: typeof Sliders }[] = [
  { id: 'general', label: 'General & Storage', icon: Sliders },
  { id: 'models', label: 'AI Models', icon: Cpu },
  { id: 'providers', label: 'AI Providers', icon: Sparkles },
  { id: 'discovery', label: 'Clip Discovery', icon: Layers },
  { id: 'presets', label: 'Presets', icon: Wrench },
  { id: 'diagnostics', label: 'Diagnostics', icon: HardDrive },
  { id: 'privacy', label: 'Privacy & Data', icon: ShieldCheck },
];

const DEFAULT_WEIGHTS: Record<string, number> = {
  hook: 20,
  story: 20,
  engagement: 15,
  emotion: 15,
  information: 10,
  standalone: 10,
  av_quality: 10,
};

const PRESET_DURATIONS = [30, 45, 60, 90, 120, 150, 180];

const LANGUAGES = SPOKEN_LANGUAGE_OPTIONS;

function hashToTab(hash: string): TabId {
  const clean = hash.replace(/^#/, '').toLowerCase();
  if (clean === 'danger') return 'privacy';
  const found = TABS.find((t) => t.id === clean);
  return found ? found.id : 'general';
}

export function SettingsPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const uid = useId();
  const { settings, loading, load, save } = useSettings();
  const [activeTab, setActiveTab] = useState<TabId>(() => hashToTab(location.hash));
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  useEffect(() => {
    if (!settings && !loading) void load();
  }, [settings, loading, load]);

  useEffect(() => {
    setActiveTab(hashToTab(location.hash));
  }, [location.hash]);

  useEffect(() => {
    const btn = tabRefs.current[activeTab];
    btn?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [activeTab]);

  const selectTab = (id: TabId) => {
    setActiveTab(id);
    navigate({ pathname: '/settings', hash: `#${id}` }, { replace: true });
  };

  const onTabKeyDown = (e: React.KeyboardEvent, idx: number) => {
    let next = -1;
    if (e.key === 'ArrowRight') next = (idx + 1) % TABS.length;
    else if (e.key === 'ArrowLeft') next = (idx - 1 + TABS.length) % TABS.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = TABS.length - 1;
    if (next >= 0) {
      e.preventDefault();
      const targetId = TABS[next].id;
      tabRefs.current[targetId]?.focus();
    }
  };

  if (loading && !settings) return <LoadingBlock label="Loading studio settings…" />;
  if (!settings) return <ErrorState message="Settings could not be loaded from the local backend." onRetry={() => load()} />;

  const activeTabButtonId = `${uid}-tab-${activeTab}`;

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink-50">Studio Settings</h1>
          <p className="text-xs text-ink-300">
            Configure local storage, Faster-Whisper models, optional AI providers, clip scoring weights, presets and privacy controls.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {settings.offline_mode ? (
            <Badge tone="green">
              <WifiOff className="h-3 w-3" aria-hidden="true" /> Offline Mode Active
            </Badge>
          ) : (
            <Badge tone="blue">Local-First Hybrid Mode</Badge>
          )}
          <Button size="sm" variant="subtle" icon={<FolderOpen className="h-3.5 w-3.5" aria-hidden="true" />} onClick={() => api.openFolder('data')}>
            App data folder
          </Button>
        </div>
      </div>

      <div
        role="tablist"
        aria-label="Settings categories"
        className="flex overflow-x-auto border-b border-ink-600"
      >
        {TABS.map((t, idx) => {
          const Icon = t.icon;
          const selected = activeTab === t.id;
          return (
            <button
              key={t.id}
              ref={(el) => {
                tabRefs.current[t.id] = el;
              }}
              id={`${uid}-tab-${t.id}`}
              type="button"
              role="tab"
              aria-selected={selected}
              tabIndex={selected ? 0 : -1}
              onClick={() => selectTab(t.id)}
              onKeyDown={(e) => onTabKeyDown(e, idx)}
              className="relative flex flex-none items-center gap-2 px-3.5 py-2.5 text-xs font-medium text-ink-200 transition-colors hover:text-ink-50 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-amber-500/80 aria-selected:text-amber-300 aria-selected:after:absolute aria-selected:after:inset-x-0 aria-selected:after:bottom-0 aria-selected:after:border-b-[3px] aria-selected:after:border-amber-400 aria-selected:after:content-['']"
            >
              <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              <span>{t.label}</span>
            </button>
          );
        })}
      </div>

      <div role="tabpanel" aria-labelledby={activeTabButtonId}>
        <div className="pt-1">
          {activeTab === 'general' && <GeneralSection settings={settings} save={save} />}
          {activeTab === 'models' && <ModelsAndAsrSection settings={settings} save={save} />}
          {activeTab === 'providers' && <ProvidersSection />}
          {activeTab === 'discovery' && <DiscoverySection settings={settings} save={save} />}
          {activeTab === 'presets' && <PresetsManagerSection settings={settings} save={save} />}
          {activeTab === 'diagnostics' && <DiagnosticsSection />}
          {activeTab === 'privacy' && <PrivacySection settings={settings} save={save} onReload={load} />}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- General & Storage
function GeneralSection({ settings, save }: { settings: Settings; save: (p: Partial<Settings>, q?: boolean) => Promise<boolean> }) {
  const uid = useId();
  const projId = `${uid}-projects-dir`;
  const projErrId = `${uid}-projects-err`;
  const expId = `${uid}-exports-dir`;
  const expErrId = `${uid}-exports-err`;
  const proxyId = `${uid}-proxy`;
  const hwId = `${uid}-hw`;
  const projRef = useRef<HTMLInputElement>(null);
  const expRef = useRef<HTMLInputElement>(null);

  const [projectsDir, setProjectsDir] = useState(settings.projects_dir);
  const [exportsDir, setExportsDir] = useState(settings.exports_dir);
  const [projErr, setProjErr] = useState<string | null>(null);
  const [expErr, setExpErr] = useState<string | null>(null);
  const [savingPaths, setSavingPaths] = useState(false);

  useEffect(() => {
    setProjectsDir(settings.projects_dir);
    setExportsDir(settings.exports_dir);
  }, [settings.projects_dir, settings.exports_dir]);

  const checkDir = (v: string, label: string): string | null => {
    const t = v.trim();
    if (!t) return `Enter a valid Windows folder path for ${label}.`;
    if (t.length < 3) return `${label} path is too short.`;
    return null;
  };

  const browseFolder = async (which: 'projects' | 'exports') => {
    try {
      const r = await api.dialog('folder', which === 'projects' ? 'Select Projects Directory' : 'Select Exports Directory');
      if (!r.path) return;
      if (which === 'projects') {
        setProjectsDir(r.path);
        setProjErr(null);
      } else {
        setExportsDir(r.path);
        setExpErr(null);
      }
    } catch (e) {
      toast.error('Folder picker unavailable', errMsg(e));
    }
  };

  const submitPaths = async (e: React.FormEvent) => {
    e.preventDefault();
    const pe = checkDir(projectsDir, 'projects folder');
    const ee = checkDir(exportsDir, 'exports folder');
    setProjErr(pe);
    setExpErr(ee);
    if (pe) {
      projRef.current?.focus();
      return;
    }
    if (ee) {
      expRef.current?.focus();
      return;
    }
    setSavingPaths(true);
    try {
      await save({ projects_dir: projectsDir.trim(), exports_dir: exportsDir.trim() });
    } finally {
      setSavingPaths(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <Panel title="Network & offline mode">
        <Toggle
          checked={settings.offline_mode}
          onChange={(v) => save({ offline_mode: v })}
          label="Global Offline Mode (100% air-gapped operation)"
          hint="Blocks all external network calls: disables cloud AI providers, YouTube downloads and online model downloads while keeping every installed local engine active."
        />
      </Panel>

      <Panel title="Local storage directories">
        <form onSubmit={submitPaths} noValidate className="flex flex-col gap-3">
          <Field
            label="Projects workspace directory *"
            htmlFor={projId}
            hintId={projErrId}
            error={projErr}
            hint="Stores analysis audio, transcripts, waveforms, proxies and imported project media."
          >
            <div className="flex flex-wrap gap-1.5">
              <input
                ref={projRef}
                id={projId}
                name="projects_dir"
                required
                autoCorrect="off"
                autoCapitalize="none"
                spellCheck={false}
                aria-invalid={projErr ? true : undefined}
                aria-describedby={projErrId}
                className={`${inputCls} min-w-[240px] flex-1 font-mono`}
                value={projectsDir}
                onChange={(e) => {
                  setProjectsDir(e.target.value);
                  if (projErr && !checkDir(e.target.value, 'projects folder')) setProjErr(null);
                }}
                onBlur={() => {
                  if (projectsDir !== settings.projects_dir) setProjErr(checkDir(projectsDir, 'projects folder'));
                }}
              />
              <Button size="sm" variant="subtle" onClick={() => browseFolder('projects')}>
                Browse…
              </Button>
              <Button size="sm" variant="ghost" icon={<FolderOpen className="h-3.5 w-3.5" aria-hidden="true" />} onClick={() => api.openFolder('projects')}>
                Open
              </Button>
            </div>
          </Field>

          <Field
            label="Default MP4 exports directory *"
            htmlFor={expId}
            hintId={expErrId}
            error={expErr}
            hint="Rendered short-form videos are written here unless overridden per export."
          >
            <div className="flex flex-wrap gap-1.5">
              <input
                ref={expRef}
                id={expId}
                name="exports_dir"
                required
                autoCorrect="off"
                autoCapitalize="none"
                spellCheck={false}
                aria-invalid={expErr ? true : undefined}
                aria-describedby={expErrId}
                className={`${inputCls} min-w-[240px] flex-1 font-mono`}
                value={exportsDir}
                onChange={(e) => {
                  setExportsDir(e.target.value);
                  if (expErr && !checkDir(e.target.value, 'exports folder')) setExpErr(null);
                }}
                onBlur={() => {
                  if (exportsDir !== settings.exports_dir) setExpErr(checkDir(exportsDir, 'exports folder'));
                }}
              />
              <Button size="sm" variant="subtle" onClick={() => browseFolder('exports')}>
                Browse…
              </Button>
              <Button size="sm" variant="ghost" icon={<FolderOpen className="h-3.5 w-3.5" aria-hidden="true" />} onClick={() => api.openFolder('exports')}>
                Open
              </Button>
            </div>
          </Field>

          <div className="flex items-center justify-between pt-1">
            <Toggle
              checked={settings.copy_imports}
              onChange={(v) => save({ copy_imports: v })}
              label="Copy local video files into project folder by default"
              hint="When off, local path imports reference the source file in place without duplicating disk usage."
            />
            <Button
              type="submit"
              variant="primary"
              size="sm"
              loading={savingPaths}
            >
              Save storage paths
            </Button>
          </div>
        </form>
      </Panel>

      <Panel title="Performance, proxies & hardware encoding">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label="Editor preview proxy generation" htmlFor={proxyId} hint="720p H.264 preview proxies keep timeline scrubbing smooth on heavy MKV/HEVC/4K sources.">
            <Select
              id={proxyId}
              name="proxy_mode"
              value={settings.proxy_mode}
              onChange={(v) => save({ proxy_mode: v as Settings['proxy_mode'] })}
              options={[
                { value: 'auto', label: 'Automatic (only for non-browser codecs / 4K)' },
                { value: 'always', label: 'Always build 720p preview proxy' },
                { value: 'never', label: 'Never (stream original file)' },
              ]}
            />
          </Field>
          <Field label="GPU hardware video encoding" htmlFor={hwId} hint="Uses NVIDIA NVENC / Intel QSV / AMD AMF when supported and falls back to x264/x265 automatically.">
            <Select
              id={hwId}
              name="hardware_encoding"
              value={settings.hardware_encoding}
              onChange={(v) => save({ hardware_encoding: v as Settings['hardware_encoding'] })}
              options={[
                { value: 'auto', label: 'Auto (prefer GPU encoder when verified)' },
                { value: 'off', label: 'Software CPU only (libx264 / libx265)' },
              ]}
            />
          </Field>
          <Slider
            label="Concurrent analysis jobs"
            value={settings.analysis_concurrency}
            min={1}
            max={4}
            step={1}
            format={(v) => `${v} worker${v > 1 ? 's' : ''}`}
            onChange={(v) => useSettings.setState({ settings: { ...settings, analysis_concurrency: v } })}
            onCommit={(v) => save({ analysis_concurrency: v })}
          />
          <Slider
            label="Concurrent export render jobs"
            value={settings.render_concurrency}
            min={1}
            max={4}
            step={1}
            format={(v) => `${v} worker${v > 1 ? 's' : ''}`}
            onChange={(v) => useSettings.setState({ settings: { ...settings, render_concurrency: v } })}
            onCommit={(v) => save({ render_concurrency: v })}
          />
        </div>
        <div className="mt-2 text-2xs text-ink-300">
          Worker pool concurrency changes take full effect the next time ClipForge AI starts (keep at 1–2 on 4 GB VRAM laptops to avoid GPU contention).
        </div>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------- AI Models & Transcription
function ModelsAndAsrSection({ settings, save }: { settings: Settings; save: (p: Partial<Settings>, q?: boolean) => Promise<boolean> }) {
  const uid = useId();
  const devId = `${uid}-device`;
  const langId = `${uid}-lang`;
  const qualId = `${uid}-qual`;

  return (
    <div className="flex flex-col gap-4">
      <Panel title="Transcription & analysis engine defaults">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <Field label="Inference compute device" htmlFor={devId} hint="Auto uses CUDA int8_float16 when available and falls back to CPU int8.">
            <Select
              id={devId}
              name="whisper_device"
              value={settings.whisper_device}
              onChange={(v) => save({ whisper_device: v as Settings['whisper_device'] })}
              options={[
                { value: 'auto', label: 'Auto (CUDA GPU if available, else CPU)' },
                { value: 'cuda', label: 'NVIDIA CUDA GPU' },
                { value: 'cpu', label: 'CPU only (int8)' },
              ]}
            />
          </Field>
          <Field label="Default spoken language" htmlFor={langId} hint="Auto-detects spoken language per video unless pinned.">
            <Select
              id={langId}
              name="transcription_language"
              value={LANGUAGES.some((l) => l.value === settings.transcription_language) ? settings.transcription_language : 'auto'}
              onChange={(v) => save({ transcription_language: v })}
              options={LANGUAGES}
            />
          </Field>
          <Field label="Visual analysis quality" htmlFor={qualId} hint="Controls frame-sampling FPS and vision proxy resolution.">
            <Select
              id={qualId}
              name="analysis_quality"
              value={settings.analysis_quality}
              onChange={(v) => save({ analysis_quality: v as Settings['analysis_quality'] })}
              options={[
                { value: 'fast', label: 'Fast (1 fps · 480p)' },
                { value: 'balanced', label: 'Balanced (2 fps · 640p)' },
                { value: 'high', label: 'High (4 fps · 854p)' },
              ]}
            />
          </Field>
        </div>
        <div className="mt-4 grid grid-cols-1 items-center gap-4 border-t border-ink-600 pt-3 md:grid-cols-2">
          <Toggle
            checked={settings.enable_diarization}
            onChange={(v) => save({ enable_diarization: v })}
            label="Enable local speaker turn clustering (diarization)"
            hint="Assigns anonymous labels (Speaker 1, Speaker 2…) using local MFCC clustering — never fabricates real names."
          />
          <Slider
            label="Maximum speakers to cluster"
            value={settings.max_speakers}
            min={2}
            max={8}
            step={1}
            format={(v) => `Up to ${v} speakers`}
            onChange={(v) => useSettings.setState({ settings: { ...settings, max_speakers: v } })}
            onCommit={(v) => save({ max_speakers: v })}
          />
        </div>
      </Panel>
      <ModelsSection />
    </div>
  );
}

// ---------------------------------------------------------------- Clip Discovery & Scoring
function DiscoverySection({ settings, save }: { settings: Settings; save: (p: Partial<Settings>, q?: boolean) => Promise<boolean> }) {
  const uid = useId();
  const customDurId = `${uid}-custom-dur`;
  const customDurErrId = `${uid}-custom-dur-err`;
  const presetSelId = `${uid}-default-preset`;
  const presets = useFetch<Preset[]>(() => api.presets(), []);

  const [weights, setWeights] = useState<Record<string, number>>(() => ({ ...DEFAULT_WEIGHTS, ...settings.score_weights }));
  const [customDur, setCustomDur] = useState('');
  const [customDurErr, setCustomDurErr] = useState<string | null>(null);
  const [minScore, setMinScore] = useState<number>(Number(settings.discovery_preferences?.min_score ?? 0));

  useEffect(() => {
    setWeights({ ...DEFAULT_WEIGHTS, ...settings.score_weights });
    setMinScore(Number(settings.discovery_preferences?.min_score ?? 0));
  }, [settings.score_weights, settings.discovery_preferences]);

  const toggleTarget = (sec: number) => {
    const cur = settings.duration_targets;
    const exists = cur.includes(sec);
    if (exists && cur.length <= 1) {
      toast.info('Keep at least one duration target selected.');
      return;
    }
    const next = exists ? cur.filter((x) => x !== sec) : [...cur, sec].sort((a, b) => a - b);
    void save({ duration_targets: next });
  };

  const addCustomTarget = (e: React.FormEvent) => {
    e.preventDefault();
    const n = Number(customDur.trim());
    if (!Number.isFinite(n) || n < 5 || n > 900) {
      setCustomDurErr('Enter a custom duration between 5 and 900 seconds.');
      return;
    }
    const rounded = Math.round(n);
    const next = [...new Set([...settings.duration_targets, rounded])].sort((a, b) => a - b);
    setCustomDur('');
    setCustomDurErr(null);
    void save({ duration_targets: next });
  };

  const weightTotal = SCORE_DIMENSIONS.reduce((acc, k) => acc + (weights[k] ?? 0), 0);

  const saveWeights = async () => {
    if (weightTotal <= 0) {
      toast.error('Invalid weights', 'At least one scoring dimension must be greater than zero.');
      return;
    }
    await save({ score_weights: weights });
  };

  const resetWeights = async () => {
    setWeights({ ...DEFAULT_WEIGHTS });
    await save({ score_weights: { ...DEFAULT_WEIGHTS } });
  };

  const prefCats = settings.discovery_preferences?.categories ?? [];
  const toggleCategory = (cat: string) => {
    const next = prefCats.includes(cat) ? prefCats.filter((x) => x !== cat) : [...prefCats, cat];
    void save({ discovery_preferences: { ...settings.discovery_preferences, categories: next } });
  };

  return (
    <div className="flex flex-col gap-4">
      <Panel title="Default duration targets & editing format">
        <div className="flex flex-col gap-3">
          <div>
            <div className="mb-1.5 text-2xs font-medium uppercase tracking-wider text-ink-300">Target clip durations</div>
            <div className="flex flex-wrap items-center gap-1.5">
              {PRESET_DURATIONS.map((d) => (
                <Chip key={d} active={settings.duration_targets.includes(d)} onClick={() => toggleTarget(d)}>
                  {d}s
                </Chip>
              ))}
              {settings.duration_targets
                .filter((d) => !PRESET_DURATIONS.includes(d))
                .map((d) => (
                  <Chip key={d} active onRemove={() => toggleTarget(d)} onClick={() => toggleTarget(d)}>
                    {d}s (custom)
                  </Chip>
                ))}
            </div>
          </div>

          <form onSubmit={addCustomTarget} noValidate className="flex flex-wrap items-start gap-2">
            <Field label="Add custom duration (5–900s)" htmlFor={customDurId} hintId={customDurErrId} error={customDurErr} className="w-56">
              <div className="flex gap-1.5">
                <input
                  id={customDurId}
                  name="custom_duration"
                  type="text"
                  inputMode="numeric"
                  placeholder="e.g. 75"
                  aria-invalid={customDurErr ? true : undefined}
                  aria-describedby={customDurErrId}
                  className={`${inputCls} font-mono`}
                  value={customDur}
                  onChange={(e) => {
                    setCustomDur(e.target.value);
                    if (customDurErr) setCustomDurErr(null);
                  }}
                />
                <Button type="submit" size="sm" variant="subtle" icon={<Plus className="h-3.5 w-3.5" aria-hidden="true" />}>
                  Add
                </Button>
              </div>
            </Field>
          </form>

          <div className="grid grid-cols-1 gap-4 border-t border-ink-600 pt-3 md:grid-cols-4">
            <Slider
              label="Duration tolerance"
              value={settings.duration_tolerance}
              min={0.1}
              max={0.4}
              step={0.05}
              format={(v) => `±${Math.round(v * 100)}%`}
              onChange={(v) => useSettings.setState({ settings: { ...settings, duration_tolerance: v } })}
              onCommit={(v) => save({ duration_tolerance: v })}
            />
            <Slider
              label="Max clips per target"
              value={settings.max_clips_per_target}
              min={1}
              max={12}
              step={1}
              format={(v) => `${v} clips`}
              onChange={(v) => useSettings.setState({ settings: { ...settings, max_clips_per_target: v } })}
              onCommit={(v) => save({ max_clips_per_target: v })}
            />
            <Field label="Default editing preset" htmlFor={presetSelId}>
              <Select
                id={presetSelId}
                name="default_preset"
                value={settings.default_preset}
                onChange={(v) => save({ default_preset: v })}
                options={(presets.data ?? [{ id: settings.default_preset, name: settings.default_preset }]).map((p) => ({ value: p.id, label: p.name }))}
              />
            </Field>
            <Field label="Default aspect ratio">
              <Segmented value={settings.default_aspect} onChange={(v: Aspect) => save({ default_aspect: v })} options={ASPECTS.map((a) => ({ value: a, label: a }))} />
            </Field>
          </div>
        </div>
      </Panel>

      <Panel
        title="Editorial clip quality scoring weights (0–100)"
        actions={
          <div className="flex items-center gap-1.5">
            <Button size="xs" variant="ghost" icon={<RotateCcw className="h-3 w-3" aria-hidden="true" />} onClick={resetWeights}>
              Reset defaults
            </Button>
            <Button size="xs" variant="primary" onClick={saveWeights}>
              Save weights
            </Button>
          </div>
        }
      >
        <p className="mb-3 text-2xs text-ink-300">
          Customize how the discovery engine weights each editorial dimension when ranking candidate clips. Total weight: <b className="font-mono text-ink-50">{weightTotal}</b> (normalized automatically to 0–100). Scores estimate editorial quality, not guaranteed social virality.
        </p>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {SCORE_DIMENSIONS.map((dim) => {
            const val = weights[dim] ?? 0;
            const pct = weightTotal > 0 ? Math.round((val / weightTotal) * 100) : 0;
            return (
              <div key={dim} className="rounded-md border border-ink-600 bg-ink-850 p-2.5">
                <Slider
                  label={DIM_LABELS[dim]}
                  value={val}
                  min={0}
                  max={50}
                  step={1}
                  format={(v) => `${v} (${pct}%)`}
                  onChange={(v) => setWeights((w) => ({ ...w, [dim]: v }))}
                />
              </div>
            );
          })}
        </div>
      </Panel>

      <Panel title="Discovery preferences & duplicate handling">
        <div className="flex flex-col gap-3">
          <div>
            <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-ink-300">Preferred moment categories (empty = all categories equally)</div>
            <div className="flex flex-wrap gap-1.5">
              {CATEGORIES.map((c) => (
                <Chip key={c} active={prefCats.includes(c)} onClick={() => toggleCategory(c)}>
                  {titleCase(c)}
                </Chip>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-1 items-center gap-4 border-t border-ink-600 pt-3 md:grid-cols-2">
            <Slider
              label="Minimum quality score filter"
              value={minScore}
              min={0}
              max={85}
              step={5}
              format={(v) => (v === 0 ? 'Off (show all)' : `${v}+ / 100`)}
              onChange={setMinScore}
              onCommit={(v) => save({ discovery_preferences: { ...settings.discovery_preferences, min_score: v } })}
            />
            <Toggle
              checked={Boolean(settings.discovery_preferences?.allow_alternates ?? true)}
              onChange={(v) => save({ discovery_preferences: { ...settings.discovery_preferences, allow_alternates: v } })}
              label="Allow distinct duration variants of strong moments"
              hint="Permits e.g. both a tight 30s hook cut and a fuller 90s story cut when boundaries differ meaningfully."
            />
          </div>
        </div>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------- Presets Manager
function PresetsManagerSection({ settings, save }: { settings: Settings; save: (p: Partial<Settings>, q?: boolean) => Promise<boolean> }) {
  const presets = useFetch<Preset[]>(() => api.presets(), []);
  const [modal, setModal] = useState<null | { preset?: Preset }>(null);
  const [delPreset, setDelPreset] = useState<Preset | null>(null);

  const duplicate = async (p: Preset) => {
    try {
      const created = await api.duplicatePreset(p.id);
      await presets.reload(true);
      toast.success(`Duplicated “${created.name}”`);
    } catch (e) {
      toast.error('Duplicate failed', errMsg(e));
    }
  };

  const remove = async () => {
    if (!delPreset) return;
    try {
      await api.deletePreset(delPreset.id);
      if (settings.default_preset === delPreset.id) {
        await save({ default_preset: 'podcast_pro' }, true);
      }
      await presets.reload(true);
      toast.success(`Deleted “${delPreset.name}”`);
    } catch (e) {
      toast.error('Delete failed', errMsg(e));
    }
  };

  if (presets.loading && !presets.data) return <LoadingBlock label="Loading presets…" />;
  if (presets.error) return <ErrorState message={presets.error} onRetry={() => presets.reload()} />;

  return (
    <div className="flex flex-col gap-4">
      <Panel
        title="Built-in & custom editing presets"
        actions={
          <Button size="xs" variant="primary" icon={<Plus className="h-3 w-3" aria-hidden="true" />} onClick={() => setModal({})}>
            New custom preset
          </Button>
        }
      >
        <p className="mb-3 text-2xs text-ink-300">
          Built-in presets are read-only templates. Duplicate any preset to customize its caption style, jump-cut silence threshold, reframing smoothness, zoom cadence, music moods and loudness target.
        </p>
        <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
          {(presets.data ?? []).map((p) => {
            const isDefault = settings.default_preset === p.id;
            return (
              <div key={p.id} className={`flex flex-col justify-between rounded-md border p-3 ${isDefault ? 'border-amber-500/50 bg-amber-500/5' : 'border-ink-600 bg-ink-850'}`}>
                <div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-xs font-semibold text-ink-50">{p.name}</span>
                    {p.builtin ? <Badge>built-in</Badge> : <Badge tone="violet">custom</Badge>}
                    {isDefault && <Badge tone="amber">default</Badge>}
                    <div className="flex-1" />
                    <IconButton title={`Duplicate ${p.name}`} onClick={() => duplicate(p)}>
                      <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                    </IconButton>
                    {!p.builtin && (
                      <>
                        <IconButton title={`Edit ${p.name}`} onClick={() => setModal({ preset: p })}>
                          <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                        </IconButton>
                        <IconButton title={`Delete ${p.name}`} onClick={() => setDelPreset(p)}>
                          <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                        </IconButton>
                      </>
                    )}
                  </div>
                  <p className="mt-1 text-2xs leading-relaxed text-ink-200">{p.description || 'Custom editing preset.'}</p>
                </div>
                <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 border-t border-ink-600/70 pt-2 text-[11px] text-ink-300">
                  <span>
                    captions: <b className="text-ink-100">{p.config.caption_style}</b> · zoom: <b className="text-ink-100">{p.config.zoom?.frequency}</b> · loudness: <b className="text-ink-100">{p.config.audio?.loudness} LUFS</b>
                  </span>
                  {!isDefault && (
                    <Button size="xs" variant="subtle" aria-label={`Set default ${p.name}`} onClick={() => save({ default_preset: p.id })}>
                      Set default
                    </Button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </Panel>
      <PresetEditorModal open={!!modal} preset={modal?.preset} onClose={() => setModal(null)} onSaved={() => presets.reload(true)} />
      <ConfirmDialog
        open={!!delPreset}
        onClose={() => setDelPreset(null)}
        title={`Delete “${delPreset?.name}”?`}
        danger
        confirmLabel="Delete preset"
        message="This custom preset will be permanently deleted. Existing clips already using it keep their timelines."
        onConfirm={remove}
      />
    </div>
  );
}

// ---------------------------------------------------------------- Diagnostics
function DiagnosticsSection() {
  const deps = useFetch(() => api.dependencies(), []);

  if (deps.loading && !deps.data) return <LoadingBlock label="Running local environment diagnostics…" />;
  if (deps.error || !deps.data) return <ErrorState message={deps.error ?? 'Diagnostics failed'} onRetry={() => deps.reload()} />;

  return (
    <div className="flex flex-col gap-4">
      <Panel
        title="Dependency & runtime verification"
        actions={
          <div className="flex items-center gap-1.5">
            <Button size="xs" variant="ghost" icon={<FolderOpen className="h-3 w-3" aria-hidden="true" />} onClick={() => api.openFolder('logs')}>
              Open logs
            </Button>
            <Button size="xs" variant="subtle" icon={<RefreshCw className="h-3 w-3" aria-hidden="true" />} onClick={() => deps.reload()}>
              Re-check
            </Button>
          </div>
        }
      >
        <div className="mb-3 flex items-center gap-2 text-xs">
          {deps.data.ready ? (
            <Badge tone="green">
              <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" /> All required dependencies verified
            </Badge>
          ) : (
            <Badge tone="red">
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" /> Action required on missing dependencies
            </Badge>
          )}
        </div>
        <div className="divide-y divide-ink-600 rounded-md border border-ink-600 bg-ink-850">
          {deps.data.checks.map((c) => (
            <div key={c.name} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5 text-xs">
              <div className="flex items-center gap-2">
                {c.ok ? (
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" aria-hidden="true" />
                ) : c.required ? (
                  <XCircle className="h-4 w-4 shrink-0 text-red-400" aria-hidden="true" />
                ) : (
                  <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" aria-hidden="true" />
                )}
                <span className="font-medium text-ink-50">{c.name}</span>
                {!c.required && <Badge>optional</Badge>}
              </div>
              <div className="min-w-0 flex-1 text-right font-mono text-2xs text-ink-200">{c.detail}</div>
              {!c.ok && c.fix && <div className="w-full pl-6 text-2xs text-amber-300">Fix: {c.fix}</div>}
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------- Privacy & Data
function PrivacySection({
  settings,
  save,
  onReload,
}: {
  settings: Settings;
  save: (p: Partial<Settings>, q?: boolean) => Promise<boolean>;
  onReload: () => Promise<void>;
}) {
  const privacy = useFetch(() => api.privacySummary(), []);
  const refreshJobs = useJobs((s) => s.refresh);
  const [confirmReset, setConfirmReset] = useState(false);
  const [includeExports, setIncludeExports] = useState(false);
  const [includeModels, setIncludeModels] = useState(false);

  const wipeAll = async () => {
    try {
      await api.deleteAllData(includeExports, includeModels);
      await Promise.all([onReload(), refreshJobs()]);
      toast.success('Local ClipForge data deleted');
    } catch (e) {
      toast.error('Could not delete local data', errMsg(e));
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <Panel title="Privacy & local-first guarantees">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="rounded-md border border-ink-600 bg-ink-850 p-3">
            <div className="flex items-center gap-2 text-xs font-semibold text-emerald-300">
              <Lock className="h-4 w-4" aria-hidden="true" /> 100% Local Media Engine
            </div>
            <p className="mt-1 text-2xs leading-relaxed text-ink-200">
              Source videos, extracted WAV audio, Faster-Whisper transcription, OpenCV tracking and FFmpeg exports run strictly on your Windows machine bound to <code className="text-ink-50">127.0.0.1</code>.
            </p>
          </div>
          <div className="rounded-md border border-ink-600 bg-ink-850 p-3">
            <div className="flex items-center gap-2 text-xs font-semibold text-amber-300">
              <ShieldCheck className="h-4 w-4" aria-hidden="true" /> Encrypted Secrets & Zero Telemetry
            </div>
            <p className="mt-1 text-2xs leading-relaxed text-ink-200">
              ClipForge AI collects zero telemetry or analytics. Optional AI provider keys are encrypted locally with Windows DPAPI (<code className="text-ink-50">CryptProtectData</code>) and never returned to the browser.
            </p>
          </div>
          <div className="rounded-md border border-ink-600 bg-ink-850 p-3">
            <div className="flex items-center gap-2 text-xs font-semibold text-sky-300">
              <WifiOff className="h-4 w-4" aria-hidden="true" /> Explicit Cloud Opt-In
            </div>
            <p className="mt-1 text-2xs leading-relaxed text-ink-200">
              Cloud LLMs are disabled by default. Even when enabled, original media files are never uploaded — only transcript excerpts and timestamps (plus 512px still frames only if explicitly opted in).
            </p>
          </div>
        </div>

        {privacy.data && (
          <div className="mt-3 grid grid-cols-1 gap-3 rounded-md border border-ink-600 bg-ink-850 p-3 text-2xs md:grid-cols-2">
            <div>
              <div className="mb-1 font-semibold uppercase tracking-wider text-amber-300">May be sent when a cloud LLM is enabled</div>
              <ul className="list-disc space-y-0.5 pl-4 text-ink-100">
                {privacy.data.sent.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            </div>
            <div>
              <div className="mb-1 font-semibold uppercase tracking-wider text-emerald-300">Never transmitted externally</div>
              <ul className="list-disc space-y-0.5 pl-4 text-ink-100">
                {privacy.data.never_sent.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            </div>
          </div>
        )}

        <div className="mt-3">
          <Toggle
            checked={settings.offline_mode}
            onChange={(v) => save({ offline_mode: v })}
            label="Enforce Global Offline Mode"
            hint="Immediately disables any active cloud AI providers and prevents outbound network requests."
          />
        </div>
      </Panel>

      <Panel title="Danger zone — delete local application data" className="border-red-500/35">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="max-w-2xl text-xs text-ink-200">
            <div className="font-semibold text-red-300">Delete all local ClipForge AI projects, transcripts, database records & stored API keys</div>
            <p className="mt-1 text-2xs leading-relaxed text-ink-300">
              Cancels active jobs, wipes the SQLite database (projects, clips, jobs, custom presets, user audio imports, AI providers), deletes project working directories and clears DPAPI-encrypted provider secrets. Source videos outside the projects folder are never touched.
            </p>
          </div>
          <Button
            variant="danger"
            size="md"
            icon={<Trash2 className="h-4 w-4" aria-hidden="true" />}
            onClick={() => {
              setIncludeExports(false);
              setIncludeModels(false);
              setConfirmReset(true);
            }}
          >
            Delete all local data…
          </Button>
        </div>
      </Panel>

      <ConfirmDialog
        open={confirmReset}
        onClose={() => setConfirmReset(false)}
        title="Delete all local ClipForge AI data?"
        danger
        typed="DELETE"
        confirmLabel="Permanently delete"
        message="This permanently removes all projects, clip candidates, edit timelines, custom presets, imported library audio and saved provider keys."
        onConfirm={wipeAll}
      >
        <div className="space-y-2 rounded-md border border-ink-600 bg-ink-850 p-3">
          <Toggle
            checked={includeExports}
            onChange={setIncludeExports}
            label="Also delete rendered MP4 files in the exports history"
          />
          <Toggle
            checked={includeModels}
            onChange={setIncludeModels}
            label="Also delete downloaded Whisper & YuNet AI models (requires re-downloading)"
          />
        </div>
      </ConfirmDialog>
    </div>
  );
}
