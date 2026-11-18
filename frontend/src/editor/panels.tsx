import { BookmarkPlus, Check, Copy, Crosshair, Pencil, Plus, RefreshCw, RotateCcw, Trash2, Wand2, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api, errMsg } from '../api';
import { PresetEditorModal } from '../components/settings/PresetEditorModal';
import { Badge, Button, ConfirmDialog, Field, IconButton, inputCls, ScoreBar, ScoreRing, Segmented, Slider, StatusBadge } from '../components/ui';
import { fmtTime, titleCase } from '../lib/format';
import { useFetch } from '../lib/hooks';
import { toast } from '../stores/toast';
import type { Aspect, Preset, PresetConfig } from '../types';
import { ASPECTS, DIM_LABELS, SCORE_DIMENSIONS, TAG_LABELS } from '../types';
import { round3, zoomAt } from './geometry';
import { player } from './player';
import { useEditor } from './store';

export function Section({ title, children, actions }: { title: string; children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="border-b border-ink-600 px-3 py-3">
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-2xs font-semibold uppercase tracking-wider text-ink-300">{title}</h4>
        {actions}
      </div>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------- Clip
export function ClipPanel() {
  const data = useEditor((s) => s.data);
  const setClip = useEditor((s) => s.setClip);
  const flush = useEditor((s) => s.flush);
  const [title, setTitle] = useState(data?.clip.title ?? '');
  const [busy, setBusy] = useState<string | null>(null);
  useEffect(() => setTitle(data?.clip.title ?? ''), [data?.clip.id, data?.clip.title]);
  if (!data) return null;
  const c = data.clip;
  const saveTitle = async () => {
    if (!title.trim() || title === c.title) return;
    try {
      setClip(await api.updateClip(c.id, { title: title.trim() }));
      toast.success('Title saved');
    } catch (e) {
      toast.error('Could not save title', errMsg(e));
    }
  };
  const status = async (s: 'accepted' | 'rejected' | 'suggested') => {
    try {
      setClip(await api.updateClip(c.id, { status: s }));
    } catch (e) {
      toast.error('Could not update status', errMsg(e));
    }
  };
  const rescore = async () => {
    setBusy('rescore');
    try {
      await flush();
      setClip(await api.rescore(c.id));
      toast.success('Clip re-scored', 'Scores now reflect the current trim.');
    } catch (e) {
      toast.error('Rescore failed', errMsg(e));
    } finally {
      setBusy(null);
    }
  };
  return (
    <div>
      <Section title="Clip">
        <Field label="Title">
          <input className={inputCls} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} onBlur={saveTitle} onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()} />
        </Field>
        <div className="mt-3 flex items-center gap-3">
          <ScoreRing score={c.score} size={48} />
          <div className="min-w-0 flex-1 text-2xs text-ink-300">
            <div className="flex flex-wrap items-center gap-1">
              <StatusBadge status={c.status} />
              <Badge>{titleCase(c.category)}</Badge>
              <span>target {c.target_duration}s</span>
            </div>
            <div className="mt-1 font-mono">
              {fmtTime(c.start)} → {fmtTime(c.end)} ({c.duration.toFixed(1)}s)
            </div>
          </div>
        </div>
        {c.tags.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {c.tags.map((t) => (
              <Badge key={t} tone="amber">
                {TAG_LABELS[t] ?? t}
              </Badge>
            ))}
          </div>
        )}
        <div className="mt-3 flex flex-wrap gap-1.5">
          <Button size="sm" variant={c.status === 'accepted' ? 'primary' : 'subtle'} icon={<Check className="h-3.5 w-3.5" />} onClick={() => status(c.status === 'accepted' ? 'suggested' : 'accepted')}>
            {c.status === 'accepted' ? 'Accepted' : 'Accept'}
          </Button>
          <Button size="sm" variant={c.status === 'rejected' ? 'danger' : 'subtle'} icon={<X className="h-3.5 w-3.5" />} onClick={() => status(c.status === 'rejected' ? 'suggested' : 'rejected')}>
            {c.status === 'rejected' ? 'Rejected' : 'Reject'}
          </Button>
          <Button size="sm" variant="subtle" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={busy === 'rescore'} onClick={rescore}>
            Rescore
          </Button>
        </div>
      </Section>
      {c.hook && (
        <Section title="Hook">
          <p className="text-xs italic leading-relaxed text-ink-100">“{c.hook}”</p>
        </Section>
      )}
      <Section title="Why this clip">
        <p className="text-2xs leading-relaxed text-ink-200">{c.reason}</p>
        <div className="mt-3 flex flex-col gap-2.5">
          {SCORE_DIMENSIONS.filter((d) => c.scores[d] !== undefined).map((d) => (
            <ScoreBar key={d} label={DIM_LABELS[d]} value={c.scores[d]} explanation={typeof c.explanations[d] === 'string' ? (c.explanations[d] as string) : undefined} />
          ))}
        </div>
      </Section>
    </div>
  );
}

// ---------------------------------------------------------------- Format & Reframe
const MODES: { value: string; label: string; title: string }[] = [
  { value: 'auto', label: 'Auto', title: 'Track the active speaker / subject' },
  { value: 'single', label: 'Single', title: 'Follow one main subject' },
  { value: 'split', label: 'Split', title: 'Two-speaker split screen when both are on camera' },
  { value: 'center', label: 'Center', title: 'Static centre crop' },
  { value: 'manual', label: 'Manual', title: 'Keyframes you set by dragging the preview' },
];

export function FormatPanel() {
  const tl = useEditor((s) => s.timeline);
  const data = useEditor((s) => s.data);
  const time = useEditor((s) => s.time);
  const commit = useEditor((s) => s.commit);
  const flush = useEditor((s) => s.flush);
  const applyServerTimeline = useEditor((s) => s.applyServerTimeline);
  const [smooth, setSmooth] = useState(tl?.reframe?.smoothness ?? 0.75);
  const [busy, setBusy] = useState(false);
  useEffect(() => setSmooth(tl?.reframe?.smoothness ?? 0.75), [data?.clip.id, tl?.reframe?.smoothness]);
  if (!tl || !data) return null;
  const rf = tl.reframe;
  const recompute = async (mode: string, aspect: Aspect) => {
    setBusy(true);
    try {
      await flush();
      const r = await api.reframe(data.clip.id, { mode, aspect, smoothness: smooth });
      applyServerTimeline(r.timeline, r.version);
      toast.success('Reframe updated', `${aspect} · ${mode}${r.timeline.reframe.layouts?.length ? ` · ${r.timeline.reframe.layouts.length} split section(s)` : ''}`);
    } catch (e) {
      toast.error('Reframe failed', errMsg(e));
    } finally {
      setBusy(false);
    }
  };
  const zoomNow = zoomAt(tl.zooms, time);
  return (
    <div>
      <Section title="Aspect ratio">
        <div className="grid grid-cols-4 gap-1.5">
          {ASPECTS.map((a) => {
            const [w, h] = a.split(':').map(Number);
            return (
              <button
                key={a}
                disabled={busy}
                onClick={() => a !== tl.aspect && recompute(rf.mode === 'manual' ? 'auto' : rf.mode, a)}
                className={`flex flex-col items-center gap-1 rounded-md border py-2 text-2xs font-medium transition-colors ${tl.aspect === a ? 'border-amber-500/70 bg-amber-500/10 text-amber-300' : 'border-ink-600 bg-ink-850 text-ink-200 hover:border-ink-400'}`}
              >
                <span className="block rounded-[2px] border-2 border-current" style={{ width: (w / Math.max(w, h)) * 22, height: (h / Math.max(w, h)) * 22 }} />
                {a}
              </button>
            );
          })}
        </div>
        <div className="mt-2 text-2xs text-ink-300">Changing the aspect recomputes the tracking path for the new crop size.</div>
      </Section>
      <Section title="Reframe mode">
        <div className="flex flex-wrap gap-1">
          {MODES.map((m) => (
            <button
              key={m.value}
              title={m.title}
              disabled={busy}
              onClick={() => recompute(m.value, tl.aspect)}
              className={`h-7 rounded-md border px-2.5 text-xs font-medium ${rf.mode === m.value ? 'border-amber-500/70 bg-amber-500/10 text-amber-300' : 'border-ink-600 bg-ink-850 text-ink-200 hover:text-ink-50'}`}
            >
              {m.label}
            </button>
          ))}
        </div>
        <div className="mt-3">
          <Slider label="Smoothness" value={smooth} min={0} max={1} step={0.05} format={(v) => `${Math.round(v * 100)}%`} onChange={setSmooth} />
        </div>
        <Button className="mt-2" size="sm" variant="subtle" loading={busy} icon={<Wand2 className="h-3.5 w-3.5" />} onClick={() => recompute(rf.mode === 'manual' ? 'auto' : String(rf.mode), tl.aspect)}>
          Recompute tracking
        </Button>
        <div className="mt-2 text-2xs text-ink-300">
          {rf.keyframes?.length ?? 0} keyframes · {rf.layouts?.length ?? 0} split sections
        </div>
      </Section>
      <Section
        title="Manual position"
        actions={
          <Button
            size="xs"
            variant="ghost"
            icon={<RotateCcw className="h-3 w-3" />}
            onClick={() =>
              commit((s) => {
                s.timeline.reframe.offset = { x: 0, y: 0 };
                return s;
              })
            }
          >
            Reset
          </Button>
        }
      >
        <div className="text-2xs leading-relaxed text-ink-300">
          Drag the video inside the preview frame to reposition the crop.{' '}
          {rf.mode === 'manual' ? 'In manual mode each drag edits (or adds) the keyframe at the playhead.' : 'The offset applies on top of automatic tracking.'}
        </div>
        <div className="mt-2 grid grid-cols-2 gap-2">
          <Slider label="Offset X" value={rf.offset?.x ?? 0} min={-0.5} max={0.5} step={0.005} format={(v) => v.toFixed(3)} onChange={(v) => commit((s) => ((s.timeline.reframe.offset = { ...(s.timeline.reframe.offset ?? { x: 0, y: 0 }), x: v }), s), 'offx')} />
          <Slider label="Offset Y" value={rf.offset?.y ?? 0} min={-0.5} max={0.5} step={0.005} format={(v) => v.toFixed(3)} onChange={(v) => commit((s) => ((s.timeline.reframe.offset = { ...(s.timeline.reframe.offset ?? { x: 0, y: 0 }), y: v }), s), 'offy')} />
        </div>
        {rf.mode === 'manual' && (
          <div className="mt-2 flex flex-col gap-1">
            {(rf.keyframes ?? []).map((k, i) => (
              <div key={i} className="flex items-center gap-2 rounded border border-ink-600 bg-ink-850 px-2 py-1 text-2xs">
                <button className="font-mono text-ink-100 hover:text-amber-400" onClick={() => player.seek(k.t)}>
                  {fmtTime(k.t, true)}
                </button>
                <span className="text-ink-300">
                  x {k.x.toFixed(2)} y {k.y.toFixed(2)}
                </span>
                <div className="flex-1" />
                <button
                  className="text-ink-300 hover:text-red-300"
                  disabled={(rf.keyframes?.length ?? 0) <= 1}
                  onClick={() =>
                    commit((s) => {
                      s.timeline.reframe.keyframes = s.timeline.reframe.keyframes.filter((_, j) => j !== i);
                      return s;
                    })
                  }
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}
      </Section>
      <Section
        title="Punch-in zooms"
        actions={
          <Button
            size="xs"
            variant="subtle"
            icon={<Plus className="h-3 w-3" />}
            onClick={() =>
              commit((s) => {
                const st = round3(Math.max(s.timeline.start, Math.min(time, s.timeline.end - 0.5)));
                const en = round3(Math.min(s.timeline.end, st + 3));
                s.timeline.zooms = [...s.timeline.zooms.filter((z) => z.e <= st || z.s >= en), { s: st, e: en, scale: 1.15 }].sort((a, b) => a.s - b.s);
                return s;
              })
            }
          >
            Add at playhead
          </Button>
        }
      >
        {tl.zooms.length === 0 && <div className="text-2xs text-ink-300">No zooms. Add a punch-in to emphasise a moment.</div>}
        <div className="flex flex-col gap-2">
          {tl.zooms.map((z, i) => (
            <div key={i} className={`rounded-md border p-2 ${z.s <= time && time < z.e ? 'border-amber-500/50 bg-amber-500/5' : 'border-ink-600 bg-ink-850'}`}>
              <div className="flex items-center gap-2 text-2xs">
                <button className="font-mono text-ink-100 hover:text-amber-400" onClick={() => player.seek(z.s)}>
                  <Crosshair className="mr-1 inline h-3 w-3" />
                  {fmtTime(z.s, true)} – {fmtTime(z.e, true)}
                </button>
                <div className="flex-1" />
                <button
                  className="text-ink-300 hover:text-red-300"
                  onClick={() =>
                    commit((s) => {
                      s.timeline.zooms = s.timeline.zooms.filter((_, j) => j !== i);
                      return s;
                    })
                  }
                  title="Remove zoom"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
              <div className="mt-1.5 grid grid-cols-3 gap-2">
                <NumField label="Start" value={z.s} step={0.1} onChange={(v) => commit((s) => ((s.timeline.zooms[i].s = round3(Math.min(v, s.timeline.zooms[i].e - 0.2))), s), `zs${i}`)} />
                <NumField label="End" value={z.e} step={0.1} onChange={(v) => commit((s) => ((s.timeline.zooms[i].e = round3(Math.max(v, s.timeline.zooms[i].s + 0.2))), s), `ze${i}`)} />
                <NumField label="Scale" value={z.scale} step={0.01} min={1} max={2} onChange={(v) => commit((s) => ((s.timeline.zooms[i].scale = Math.min(2, Math.max(1, v))), s), `zc${i}`)} />
              </div>
            </div>
          ))}
        </div>
        <div className="mt-2 text-2xs text-ink-300">Zoom at playhead: {zoomNow.toFixed(2)}×</div>
      </Section>
    </div>
  );
}

export function NumField({ label, value, onChange, step = 0.1, min, max }: { label: string; value: number; onChange: (v: number) => void; step?: number; min?: number; max?: number }) {
  const [txt, setTxt] = useState(String(value));
  useEffect(() => setTxt(String(Math.round(value * 1000) / 1000)), [value]);
  return (
    <label className="flex flex-col gap-0.5">
      <span className="text-[9px] uppercase tracking-wider text-ink-400">{label}</span>
      <input
        type="number"
        className={`${inputCls} h-6 px-1.5 font-mono`}
        value={txt}
        step={step}
        min={min}
        max={max}
        onChange={(e) => {
          setTxt(e.target.value);
          const n = Number(e.target.value);
          if (e.target.value !== '' && isFinite(n)) onChange(n);
        }}
      />
    </label>
  );
}

// ---------------------------------------------------------------- Presets
export function PresetPanel() {
  const data = useEditor((s) => s.data);
  const tl = useEditor((s) => s.timeline);
  const captions = useEditor((s) => s.captions);
  const flush = useEditor((s) => s.flush);
  const replaceState = useEditor((s) => s.replaceState);
  const presets = useFetch<Preset[]>(() => api.presets(), []);
  const [confirm, setConfirm] = useState<Preset | null>(null);
  const [delPreset, setDelPreset] = useState<Preset | null>(null);
  const [editorModal, setEditorModal] = useState<null | { preset?: Preset; initialName?: string; initialDescription?: string; initialConfig?: Partial<PresetConfig>; title?: string }>(null);
  if (!data || !tl) return null;

  const apply = async (p: Preset) => {
    try {
      await flush();
      const d = await api.applyPreset(data.clip.id, p.id, tl.aspect);
      replaceState(d);
      toast.success(`Applied “${p.name}”`, 'Cuts, reframing, captions and audio were rebuilt.');
    } catch (e) {
      toast.error('Could not apply preset', errMsg(e));
    }
  };

  const duplicate = async (p: Preset) => {
    try {
      const created = await api.duplicatePreset(p.id);
      await presets.reload(true);
      toast.success(`Duplicated as “${created.name}”`);
    } catch (e) {
      toast.error('Could not duplicate preset', errMsg(e));
    }
  };

  const remove = async () => {
    if (!delPreset) return;
    try {
      await api.deletePreset(delPreset.id);
      await presets.reload(true);
      toast.success(`Deleted “${delPreset.name}”`);
    } catch (e) {
      toast.error('Could not delete preset', errMsg(e));
    }
  };

  const openSaveCurrent = () => {
    const cs = captions?.style;
    const cutCfg = (tl.cut_settings ?? {}) as { remove_silence?: boolean; min_silence?: number; keep_pad?: number };
    const dur = Math.max(1, tl.end - tl.start);
    const zCount = tl.zooms.length;
    const zFreq = zCount === 0 ? 'none' : dur / zCount < 6 ? 'high' : dur / zCount < 11 ? 'medium' : 'low';
    const zScale = zCount ? Number((tl.zooms.reduce((a, z) => a + z.scale, 0) / zCount).toFixed(2)) : 1.1;
    const sfxInt = tl.sfx.length === 0 ? 'none' : tl.sfx.length >= 4 ? 'high' : tl.sfx.length >= 2 ? 'medium' : 'low';
    const currentPreset = (presets.data ?? []).find((x) => x.id === tl.preset_id);
    const initialConfig: PresetConfig = {
      caption_style: cs?.id ?? 'podcast_pro',
      caption_overrides: cs ? { ...cs } : undefined,
      reframe: {
        mode: tl.reframe.mode === 'manual' ? 'auto' : String(tl.reframe.mode || 'auto'),
        smoothness: Number(tl.reframe.smoothness ?? 0.75),
        prefer_split: Boolean(tl.reframe.prefer_split),
      },
      zoom: { frequency: zFreq, scale: zScale },
      cuts: {
        remove_silence: cutCfg.remove_silence ?? tl.cuts.length > 0,
        min_silence: Number(cutCfg.min_silence ?? 0.7),
        keep_pad: Number(cutCfg.keep_pad ?? 0.18),
      },
      music: {
        enabled: Boolean(tl.music.asset_id),
        moods: currentPreset?.config.music?.moods?.length ? [...currentPreset.config.music.moods] : ['podcast', 'lofi'],
        volume: Number(tl.music.volume ?? 0.1),
        ducking: Boolean(tl.music.ducking),
        fade_in: Number(tl.music.fade_in ?? 1.0),
        fade_out: Number(tl.music.fade_out ?? 1.5),
      },
      sfx: { intensity: sfxInt },
      audio: {
        enhance_voice: Boolean(tl.audio.enhance_voice),
        denoise: Boolean(tl.audio.denoise),
        loudness: Number(tl.audio.loudness ?? -14),
      },
    };
    setEditorModal({
      title: 'Save current clip settings as preset',
      initialName: `${currentPreset?.name ?? 'Custom'} Studio`,
      initialDescription: `Saved from “${data.clip.title.slice(0, 60)}”`,
      initialConfig,
    });
  };

  return (
    <div>
      <Section
        title="Editing presets"
        actions={
          <Button size="xs" variant="primary" icon={<BookmarkPlus className="h-3 w-3" aria-hidden="true" />} onClick={openSaveCurrent}>
            Save current
          </Button>
        }
      >
        <div className="mb-2 text-2xs text-ink-300">
          Applying a preset rebuilds the automatic edit for the current trim (cuts, zooms, reframe, captions, music, SFX). Save your current clip styling as a reusable custom preset or duplicate any built-in preset.
        </div>
        <div className="flex flex-col gap-1.5">
          {(presets.data ?? []).map((p) => (
            <div key={p.id} className={`rounded-md border p-2.5 ${tl.preset_id === p.id ? 'border-amber-500/50 bg-amber-500/5' : 'border-ink-600 bg-ink-850'}`}>
              <div className="flex items-center gap-1.5">
                <span className="truncate text-xs font-medium text-ink-50">{p.name}</span>
                {!p.builtin && <Badge tone="violet">custom</Badge>}
                {tl.preset_id === p.id && <Badge tone="amber">current</Badge>}
                <div className="flex-1" />
                <IconButton title={`Duplicate ${p.name}`} onClick={() => duplicate(p)}>
                  <Copy className="h-3 w-3" aria-hidden="true" />
                </IconButton>
                {!p.builtin && (
                  <>
                    <IconButton title={`Edit ${p.name}`} onClick={() => setEditorModal({ preset: p })}>
                      <Pencil className="h-3 w-3" aria-hidden="true" />
                    </IconButton>
                    <IconButton title={`Delete ${p.name}`} onClick={() => setDelPreset(p)}>
                      <Trash2 className="h-3 w-3" aria-hidden="true" />
                    </IconButton>
                  </>
                )}
                <Button size="xs" variant="subtle" aria-label={`Apply ${p.name}`} onClick={() => setConfirm(p)}>
                  Apply
                </Button>
              </div>
              <div className="mt-1 text-2xs leading-snug text-ink-300">{p.description}</div>
              <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-ink-400">
                <span>captions: {p.config.caption_style}</span>·<span>zoom: {p.config.zoom?.frequency}</span>·<span>silence ≥ {p.config.cuts?.min_silence}s</span>·<span>music: {p.config.music?.enabled ? 'on' : 'off'}</span>
              </div>
            </div>
          ))}
        </div>
      </Section>
      <ConfirmDialog
        open={!!confirm}
        onClose={() => setConfirm(null)}
        title={`Apply “${confirm?.name}”?`}
        confirmLabel="Apply preset"
        message="This resets your manual edits for this clip (cuts, captions, music, reframe). You can’t undo this from the editor history."
        onConfirm={() => (confirm ? apply(confirm) : undefined)}
      />
      <ConfirmDialog
        open={!!delPreset}
        onClose={() => setDelPreset(null)}
        title={`Delete “${delPreset?.name}”?`}
        danger
        confirmLabel="Delete preset"
        message="This custom preset will be permanently removed."
        onConfirm={remove}
      />
      <PresetEditorModal
        open={!!editorModal}
        preset={editorModal?.preset}
        initialName={editorModal?.initialName}
        initialDescription={editorModal?.initialDescription}
        initialConfig={editorModal?.initialConfig}
        title={editorModal?.title}
        onClose={() => setEditorModal(null)}
        onSaved={() => presets.reload(true)}
      />
    </div>
  );
}

export function AspectSegmented({ value, onChange }: { value: Aspect; onChange: (a: Aspect) => void }) {
  return <Segmented value={value} onChange={onChange} options={ASPECTS.map((a) => ({ value: a, label: a }))} />;
}
