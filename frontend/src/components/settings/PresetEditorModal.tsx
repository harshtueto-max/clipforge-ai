import { useEffect, useId, useRef, useState } from 'react';
import { api, errMsg } from '../../api';
import { titleCase } from '../../lib/format';
import { toast } from '../../stores/toast';
import type { Preset, PresetConfig } from '../../types';
import { Button, Chip, Field, inputCls, Modal, Select, Slider, Toggle } from '../ui';

const CAPTION_STYLE_OPTIONS = [
  { value: 'podcast_pro', label: 'Podcast Pro' },
  { value: 'bold_viral', label: 'Bold Viral' },
  { value: 'clean_minimal', label: 'Clean Minimal' },
  { value: 'highlighted_keywords', label: 'Highlighted Keywords' },
  { value: 'karaoke', label: 'Karaoke' },
  { value: 'documentary', label: 'Documentary' },
  { value: 'educational', label: 'Educational' },
];

const MUSIC_MOODS = ['cinematic', 'motivational', 'emotional', 'corporate', 'podcast', 'documentary', 'suspense', 'comedy', 'lofi', 'energetic'];

export const DEFAULT_PRESET_CONFIG: PresetConfig = {
  caption_style: 'podcast_pro',
  reframe: { mode: 'auto', smoothness: 0.75, prefer_split: false },
  zoom: { frequency: 'low', scale: 1.1 },
  cuts: { remove_silence: true, min_silence: 0.7, keep_pad: 0.18 },
  music: { enabled: true, moods: ['podcast', 'lofi'], volume: 0.1, ducking: true, fade_in: 1.0, fade_out: 1.5 },
  sfx: { intensity: 'low' },
  audio: { enhance_voice: true, denoise: false, loudness: -14 },
};

function mergeConfig(src?: Partial<PresetConfig>): PresetConfig {
  return {
    ...src,
    caption_style: src?.caption_style ?? DEFAULT_PRESET_CONFIG.caption_style,
    reframe: { ...DEFAULT_PRESET_CONFIG.reframe, ...(src?.reframe ?? {}) },
    zoom: { ...DEFAULT_PRESET_CONFIG.zoom, ...(src?.zoom ?? {}) },
    cuts: { ...DEFAULT_PRESET_CONFIG.cuts, ...(src?.cuts ?? {}) },
    music: { ...DEFAULT_PRESET_CONFIG.music, ...(src?.music ?? {}), moods: src?.music?.moods?.length ? [...src.music.moods] : [...DEFAULT_PRESET_CONFIG.music.moods] },
    sfx: { ...DEFAULT_PRESET_CONFIG.sfx, ...(src?.sfx ?? {}) },
    audio: { ...DEFAULT_PRESET_CONFIG.audio, ...(src?.audio ?? {}) },
  };
}

export function PresetEditorModal({
  open,
  preset,
  initialName = '',
  initialDescription = '',
  initialConfig,
  title,
  onClose,
  onSaved,
}: {
  open: boolean;
  preset?: Preset | null;
  initialName?: string;
  initialDescription?: string;
  initialConfig?: Partial<PresetConfig>;
  title?: string;
  onClose: () => void;
  onSaved: (saved: Preset) => void;
}) {
  const uid = useId();
  const formId = `${uid}-preset-form`;
  const nameId = `${uid}-name`;
  const nameErrId = `${uid}-name-err`;
  const descId = `${uid}-desc`;
  const capId = `${uid}-cap`;
  const rfModeId = `${uid}-rf-mode`;
  const zoomFreqId = `${uid}-zoom-freq`;
  const sfxId = `${uid}-sfx`;
  const nameRef = useRef<HTMLInputElement>(null);

  const [name, setName] = useState('');
  const [nameTouched, setNameTouched] = useState(false);
  const [nameErr, setNameErr] = useState<string | null>(null);
  const [description, setDescription] = useState('');
  const [cfg, setCfg] = useState<PresetConfig>(() => mergeConfig(initialConfig));
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName(preset ? preset.name : initialName);
    setDescription(preset ? preset.description : initialDescription);
    setCfg(mergeConfig(preset ? preset.config : initialConfig));
    setNameTouched(false);
    setNameErr(null);
  }, [open, preset, initialName, initialDescription, initialConfig]);

  const validateName = (v: string): string | null => {
    const trimmed = v.trim();
    if (!trimmed) return 'Enter a name for this preset (1–120 characters).';
    if (trimmed.length > 120) return 'Preset name must be 120 characters or fewer.';
    return null;
  };

  const toggleMood = (m: string) => {
    setCfg((prev) => {
      const has = prev.music.moods.includes(m);
      const next = has ? prev.music.moods.filter((x) => x !== m) : [...prev.music.moods, m];
      return { ...prev, music: { ...prev.music, moods: next.length ? next : [m] } };
    });
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const err = validateName(name);
    if (err) {
      setNameTouched(true);
      setNameErr(err);
      nameRef.current?.focus();
      return;
    }
    setBusy(true);
    try {
      const payload = { name: name.trim(), description: description.trim(), config: cfg };
      const saved = preset && !preset.builtin ? await api.updatePreset(preset.id, payload) : await api.createPreset(payload);
      toast.success(preset && !preset.builtin ? `Updated “${saved.name}”` : `Saved preset “${saved.name}”`);
      onSaved(saved);
      onClose();
    } catch (ex) {
      toast.error('Could not save preset', errMsg(ex));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title ?? (preset && !preset.builtin ? `Edit preset — ${preset.name}` : 'New custom preset')}
      width={620}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form={formId} variant="primary" loading={busy}>
            Save preset
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={submit} noValidate className="flex flex-col gap-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="Preset name *" htmlFor={nameId} hintId={nameErrId} error={nameErr} hint="1–120 characters">
            <input
              ref={nameRef}
              id={nameId}
              name="name"
              required
              maxLength={120}
              aria-invalid={nameErr ? true : undefined}
              aria-describedby={nameErrId}
              className={inputCls}
              value={name}
              onChange={(e) => {
                const v = e.target.value;
                setName(v);
                if (nameErr && !validateName(v)) setNameErr(null);
              }}
              onBlur={() => {
                if (name !== (preset?.name ?? initialName) || nameTouched) {
                  setNameTouched(true);
                  setNameErr(validateName(name));
                }
              }}
            />
          </Field>
          <Field label="Description" htmlFor={descId} hint="Optional summary shown in preset pickers">
            <input id={descId} name="description" maxLength={500} className={inputCls} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
        </div>

        <fieldset className="rounded-md border border-ink-600 bg-ink-850 p-3">
          <legend className="px-1.5 text-2xs font-semibold uppercase tracking-wider text-ink-200">Captions & reframing</legend>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <Field label="Caption style" htmlFor={capId}>
              <Select id={capId} name="caption_style" value={cfg.caption_style} onChange={(v) => setCfg((c) => ({ ...c, caption_style: v }))} options={CAPTION_STYLE_OPTIONS} />
            </Field>
            <Field label="Reframe mode" htmlFor={rfModeId}>
              <Select
                id={rfModeId}
                name="reframe_mode"
                value={cfg.reframe.mode}
                onChange={(v) => setCfg((c) => ({ ...c, reframe: { ...c.reframe, mode: v } }))}
                options={[
                  { value: 'auto', label: 'Auto speaker / subject tracking' },
                  { value: 'single', label: 'Single subject' },
                  { value: 'split', label: 'Two-speaker split screen' },
                  { value: 'center', label: 'Static center crop' },
                ]}
              />
            </Field>
          </div>
          <div className="mt-3 grid grid-cols-1 items-center gap-3 md:grid-cols-2">
            <Slider
              label="Tracking smoothness"
              value={cfg.reframe.smoothness}
              min={0}
              max={1}
              step={0.05}
              format={(v) => `${Math.round(v * 100)}%`}
              onChange={(v) => setCfg((c) => ({ ...c, reframe: { ...c.reframe, smoothness: v } }))}
            />
            <Toggle
              checked={cfg.reframe.prefer_split}
              onChange={(v) => setCfg((c) => ({ ...c, reframe: { ...c.reframe, prefer_split: v } }))}
              label="Prefer split screen on wide two-shots"
            />
          </div>
        </fieldset>

        <fieldset className="rounded-md border border-ink-600 bg-ink-850 p-3">
          <legend className="px-1.5 text-2xs font-semibold uppercase tracking-wider text-ink-200">Pacing, silence cuts & zooms</legend>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <div className="flex items-center">
              <Toggle checked={cfg.cuts.remove_silence} onChange={(v) => setCfg((c) => ({ ...c, cuts: { ...c.cuts, remove_silence: v } }))} label="Remove dead-air silences" />
            </div>
            <Slider
              label="Min silence to cut"
              value={cfg.cuts.min_silence}
              min={0.25}
              max={1.8}
              step={0.05}
              format={(v) => `${v.toFixed(2)}s`}
              onChange={(v) => setCfg((c) => ({ ...c, cuts: { ...c.cuts, min_silence: v } }))}
            />
            <Slider
              label="Speech padding"
              value={cfg.cuts.keep_pad}
              min={0.04}
              max={0.45}
              step={0.02}
              format={(v) => `${v.toFixed(2)}s`}
              onChange={(v) => setCfg((c) => ({ ...c, cuts: { ...c.cuts, keep_pad: v } }))}
            />
          </div>
          <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
            <Field label="Punch-in zoom frequency" htmlFor={zoomFreqId}>
              <Select
                id={zoomFreqId}
                name="zoom_frequency"
                value={cfg.zoom.frequency}
                onChange={(v) => setCfg((c) => ({ ...c, zoom: { ...c.zoom, frequency: v } }))}
                options={[
                  { value: 'none', label: 'None' },
                  { value: 'low', label: 'Low (~every 14s)' },
                  { value: 'medium', label: 'Medium (~every 8s)' },
                  { value: 'high', label: 'High (~every 4.5s)' },
                ]}
              />
            </Field>
            <Slider
              label="Zoom scale"
              value={cfg.zoom.scale}
              min={1.0}
              max={1.35}
              step={0.01}
              format={(v) => `${v.toFixed(2)}×`}
              onChange={(v) => setCfg((c) => ({ ...c, zoom: { ...c.zoom, scale: v } }))}
            />
          </div>
        </fieldset>

        <fieldset className="rounded-md border border-ink-600 bg-ink-850 p-3">
          <legend className="px-1.5 text-2xs font-semibold uppercase tracking-wider text-ink-200">Music, SFX & voice mastering</legend>
          <div className="flex flex-wrap items-center gap-4">
            <Toggle checked={cfg.music.enabled} onChange={(v) => setCfg((c) => ({ ...c, music: { ...c.music, enabled: v } }))} label="Enable background music" />
            <Toggle checked={cfg.music.ducking} onChange={(v) => setCfg((c) => ({ ...c, music: { ...c.music, ducking: v } }))} label="Auto-duck under speech" disabled={!cfg.music.enabled} />
            <Toggle checked={cfg.audio.enhance_voice} onChange={(v) => setCfg((c) => ({ ...c, audio: { ...c.audio, enhance_voice: v } }))} label="Voice presence EQ + compression" />
            <Toggle checked={cfg.audio.denoise} onChange={(v) => setCfg((c) => ({ ...c, audio: { ...c.audio, denoise: v } }))} label="FFT denoise" />
          </div>
          {cfg.music.enabled && (
            <div className="mt-3">
              <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-ink-300">Preferred music moods</div>
              <div className="flex flex-wrap gap-1">
                {MUSIC_MOODS.map((m) => (
                  <Chip key={m} active={cfg.music.moods.includes(m)} onClick={() => toggleMood(m)}>
                    {titleCase(m)}
                  </Chip>
                ))}
              </div>
            </div>
          )}
          <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
            <Slider
              label="Music volume"
              value={cfg.music.volume}
              min={0}
              max={0.35}
              step={0.01}
              format={(v) => `${Math.round(v * 100)}%`}
              onChange={(v) => setCfg((c) => ({ ...c, music: { ...c.music, volume: v } }))}
            />
            <Field label="SFX intensity" htmlFor={sfxId}>
              <Select
                id={sfxId}
                name="sfx_intensity"
                value={cfg.sfx.intensity}
                onChange={(v) => setCfg((c) => ({ ...c, sfx: { intensity: v } }))}
                options={[
                  { value: 'none', label: 'None' },
                  { value: 'low', label: 'Subtle (max 1)' },
                  { value: 'medium', label: 'Moderate (up to 3)' },
                  { value: 'high', label: 'Energetic (up to 5)' },
                ]}
              />
            </Field>
            <Slider
              label="Target loudness"
              value={cfg.audio.loudness}
              min={-20}
              max={-10}
              step={1}
              format={(v) => `${v} LUFS`}
              onChange={(v) => setCfg((c) => ({ ...c, audio: { ...c.audio, loudness: v } }))}
            />
          </div>
        </fieldset>
      </form>
    </Modal>
  );
}
