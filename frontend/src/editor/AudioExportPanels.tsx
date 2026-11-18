import { Plus, Sparkles, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { api, errMsg } from '../api';
import { PreviewButton, useAudioPreview } from '../components/AudioPreview';
import { ExportRow } from '../components/ExportRow';
import { ExportSettingsForm } from '../components/ExportDialog';
import { Badge, Button, EmptyState, Slider, Toggle } from '../components/ui';
import { cx, fmtDur, fmtTime, titleCase, uid } from '../lib/format';
import { useFetch, useWsEvent } from '../lib/hooks';
import { useJobs } from '../stores/jobs';
import { toast } from '../stores/toast';
import type { AudioAsset, ExportSettings } from '../types';
import { DEFAULT_EXPORT } from '../types';
import { round3 } from './geometry';
import { Section } from './panels';
import { player } from './player';
import { useEditor } from './store';

export function AudioPanel() {
  const data = useEditor((s) => s.data);
  const tl = useEditor((s) => s.timeline);
  const time = useEditor((s) => s.time);
  const selSfx = useEditor((s) => s.selSfx);
  const commit = useEditor((s) => s.commit);
  const stop = useAudioPreview((s) => s.stop);
  useEffect(() => () => stop(), [stop]);
  const groups = useMemo(() => {
    const music: Record<string, AudioAsset[]> = {};
    const sfx: Record<string, AudioAsset[]> = {};
    for (const a of data?.assets ?? []) {
      const tgt = a.kind === 'sfx' ? sfx : music;
      (tgt[a.category] ??= []).push(a);
    }
    return { music, sfx };
  }, [data?.assets]);
  if (!data || !tl) return null;
  const assets = Object.fromEntries(data.assets.map((a) => [a.id, a]));
  const m = tl.music;
  const setMusic = (patch: Partial<typeof m>, key?: string) =>
    commit((s) => {
      s.timeline.music = { ...s.timeline.music, ...patch };
      return s;
    }, key);
  const setAudio = (patch: Partial<typeof tl.audio>, key?: string) =>
    commit((s) => {
      s.timeline.audio = { ...s.timeline.audio, ...patch };
      return s;
    }, key);
  return (
    <div>
      <Section title="Background music">
        <button
          onClick={() => setMusic({ asset_id: null })}
          className={cx('mb-1.5 flex w-full items-center rounded-md border px-2 py-1.5 text-left text-xs', !m.asset_id ? 'border-amber-500/60 bg-amber-500/10 text-amber-300' : 'border-ink-600 bg-ink-850 text-ink-200 hover:text-ink-50')}
        >
          No music
        </button>
        <div className="max-h-64 overflow-y-auto pr-1">
          {Object.entries(groups.music).map(([cat, list]) => (
            <div key={cat} className="mb-1.5">
              <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-ink-400">{titleCase(cat)}</div>
              {list.map((a) => (
                <div
                  key={a.id}
                  onClick={() => setMusic({ asset_id: a.id })}
                  className={cx('flex cursor-pointer items-center gap-1.5 rounded-md border px-1.5 py-1 text-xs', m.asset_id === a.id ? 'border-amber-500/60 bg-amber-500/10 text-amber-200' : 'border-transparent text-ink-100 hover:bg-ink-700')}
                >
                  <PreviewButton id={a.id} url={a.url} />
                  <span className="min-w-0 flex-1 truncate">{a.name}</span>
                  {m.recommended_id === a.id && (
                    <Badge tone="amber">
                      <Sparkles className="h-2.5 w-2.5" /> recommended
                    </Badge>
                  )}
                  {a.origin === 'user' && <Badge tone="violet">yours</Badge>}
                  <span className="font-mono text-[10px] text-ink-400">{fmtDur(a.duration)}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
        {m.asset_id && (
          <div className="mt-2 flex flex-col gap-2 border-t border-ink-600 pt-2">
            <div className="text-[10px] text-ink-400" title={assets[m.asset_id]?.license}>
              License: {assets[m.asset_id]?.license ?? '—'}
            </div>
            <Slider label="Volume" value={m.volume} min={0} max={1} step={0.01} format={(v) => `${Math.round(v * 100)}%`} onChange={(v) => setMusic({ volume: v }, 'mvol')} />
            <div className="grid grid-cols-2 gap-3">
              <Slider label="Fade in" value={m.fade_in} min={0} max={5} step={0.1} format={(v) => `${v.toFixed(1)}s`} onChange={(v) => setMusic({ fade_in: v }, 'mfi')} />
              <Slider label="Fade out" value={m.fade_out} min={0} max={5} step={0.1} format={(v) => `${v.toFixed(1)}s`} onChange={(v) => setMusic({ fade_out: v }, 'mfo')} />
            </div>
            <Slider label="Start offset in track" value={m.offset ?? 0} min={0} max={Math.max(1, (assets[m.asset_id]?.duration ?? 60) - 1)} step={0.5} format={(v) => `${v.toFixed(1)}s`} onChange={(v) => setMusic({ offset: v }, 'moff')} />
            <Toggle checked={m.ducking} onChange={(v) => setMusic({ ducking: v })} label="Auto-ducking under speech" />
          </div>
        )}
      </Section>
      <Section title={`Sound effects on timeline (${tl.sfx.length})`}>
        {tl.sfx.length === 0 && <div className="text-2xs text-ink-300">No SFX placed. Add one at the playhead from the library below.</div>}
        <div className="flex flex-col gap-1.5">
          {tl.sfx.map((fx) => (
            <div key={fx.id} className={cx('rounded-md border p-1.5', selSfx === fx.id ? 'border-fuchsia-400/60 bg-fuchsia-500/5' : 'border-ink-600 bg-ink-850')}>
              <div className="flex items-center gap-1.5 text-xs">
                <PreviewButton id={`fx-${fx.id}`} url={assets[fx.asset_id]?.url ?? ''} />
                <span className="min-w-0 flex-1 truncate text-ink-100">{assets[fx.asset_id]?.name ?? 'Missing asset'}</span>
                <button className="font-mono text-2xs text-ink-300 hover:text-amber-400" onClick={() => player.seek(fx.t)}>
                  {fmtTime(fx.t, true)}
                </button>
                <button
                  className="text-ink-300 hover:text-red-300"
                  title="Remove"
                  onClick={() => commit((s) => ((s.timeline.sfx = s.timeline.sfx.filter((x) => x.id !== fx.id)), s))}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
              <Slider
                value={fx.volume}
                min={0}
                max={1.5}
                step={0.05}
                label="Volume"
                format={(v) => `${Math.round(v * 100)}%`}
                onChange={(v) =>
                  commit((s) => {
                    const x = s.timeline.sfx.find((y) => y.id === fx.id);
                    if (x) x.volume = v;
                    return s;
                  }, `sfxv-${fx.id}`)
                }
              />
            </div>
          ))}
        </div>
      </Section>
      <Section title="SFX library">
        <div className="max-h-56 overflow-y-auto pr-1">
          {Object.entries(groups.sfx).map(([cat, list]) => (
            <div key={cat} className="mb-1.5">
              <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-ink-400">{titleCase(cat)}</div>
              {list.map((a) => (
                <div key={a.id} className="flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-xs text-ink-100 hover:bg-ink-700">
                  <PreviewButton id={a.id} url={a.url} />
                  <span className="min-w-0 flex-1 truncate">{a.name}</span>
                  {tl.sfx_recommended_id === a.id && <Badge tone="amber">rec.</Badge>}
                  <Button
                    size="xs"
                    variant="ghost"
                    icon={<Plus className="h-3 w-3" />}
                    onClick={() =>
                      commit((s) => {
                        const t = round3(Math.max(s.timeline.start, Math.min(s.timeline.end, time)));
                        s.timeline.sfx = [...s.timeline.sfx, { id: uid(), asset_id: a.id, t, volume: 0.4 }].sort((x, y) => x.t - y.t);
                        return s;
                      })
                    }
                  >
                    at playhead
                  </Button>
                </div>
              ))}
            </div>
          ))}
        </div>
      </Section>
      <Section title="Voice & loudness">
        <div className="flex flex-col gap-2.5">
          <Toggle checked={tl.audio.enhance_voice} onChange={(v) => setAudio({ enhance_voice: v })} label="Voice enhance" hint="High-pass, presence EQ and gentle compression" />
          <Toggle checked={tl.audio.denoise} onChange={(v) => setAudio({ denoise: v })} label="Noise reduction" hint="FFT denoiser — use for hiss or room noise" />
          <Slider label="Loudness target" value={tl.audio.loudness} min={-16} max={-10} step={0.5} format={(v) => `${v.toFixed(1)} LUFS`} onChange={(v) => setAudio({ loudness: v }, 'loud')} />
          <Slider label="Voice gain" value={tl.audio.voice_gain_db ?? 0} min={-6} max={12} step={0.5} format={(v) => `${v > 0 ? '+' : ''}${v.toFixed(1)} dB`} onChange={(v) => setAudio({ voice_gain_db: v }, 'vgain')} />
        </div>
      </Section>
    </div>
  );
}

export function ExportPanel() {
  const data = useEditor((s) => s.data);
  const tl = useEditor((s) => s.timeline);
  const commit = useEditor((s) => s.commit);
  const flush = useEditor((s) => s.flush);
  const jobs = useJobs((s) => s.jobs);
  const clipId = data?.clip.id ?? '';
  const history = useFetch(() => (clipId ? api.clipExports(clipId) : Promise.resolve([])), [clipId]);
  const [settings, setSettings] = useState<ExportSettings>({ ...DEFAULT_EXPORT, ...(tl?.export ?? {}), output_dir: null, captions: true });
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setSettings({ ...DEFAULT_EXPORT, ...(useEditor.getState().timeline?.export ?? {}), output_dir: null, captions: true });
  }, [clipId]);
  useWsEvent((m) => {
    if (m.type === 'export' || (m.type === 'job' && m.data.kind === 'render' && (m.data.params as { clip_id?: string }).clip_id === clipId && m.data.status !== 'running')) void history.reload(true);
  });
  if (!data || !tl) return null;
  const outSize = data.output_sizes[tl.aspect]?.[settings.resolution];
  const start = async () => {
    setBusy(true);
    try {
      const nextExp = {
        ...tl.export,
        resolution: settings.resolution,
        fps: settings.fps,
        codec: settings.codec,
        quality: settings.quality,
        bitrate_kbps: settings.bitrate_kbps,
        audio_bitrate_kbps: settings.audio_bitrate_kbps,
      };
      if (JSON.stringify(nextExp) !== JSON.stringify(tl.export)) {
        commit((s) => {
          s.timeline.export = nextExp;
          return s;
        });
      }
      const ok = await flush();
      if (!ok) {
        const reason = useEditor.getState().saveError;
        throw new Error(reason ? `Could not save latest edits (${reason})` : 'Save the edit first — the latest changes could not be saved');
      }
      await api.exportClip(clipId, settings);
      toast.success('Export queued', 'The render uses your current edit.');
      await history.reload(true);
    } catch (e) {
      toast.error('Export failed to start', errMsg(e));
    } finally {
      setBusy(false);
    }
  };
  const jobFor = (jid: string | null) => (jid ? jobs[jid] : undefined);
  return (
    <div>
      <Section title="Export settings">
        <ExportSettingsForm value={settings} onChange={setSettings} />
        <div className="mt-3 flex items-center justify-between gap-2">
          <span className="text-2xs text-ink-300">
            {tl.aspect} · {outSize ? `${outSize[0]}×${outSize[1]}` : settings.resolution}
          </span>
          <Button variant="primary" size="md" loading={busy} onClick={start}>
            Export clip
          </Button>
        </div>
      </Section>
      <Section title="Export history">
        {history.loading && !history.data ? (
          <div className="text-2xs text-ink-300">Loading…</div>
        ) : !history.data?.length ? (
          <EmptyState title="No exports yet">Rendered files are validated with FFprobe and listed here.</EmptyState>
        ) : (
          <div className="flex flex-col gap-1.5">
            {history.data.map((e) => (
              <ExportRow key={e.id} ex={e} job={jobFor(e.job_id)} showClip={false} onChanged={() => history.reload(true)} />
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}
