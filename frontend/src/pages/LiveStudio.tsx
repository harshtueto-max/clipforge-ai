import Hls from 'hls.js';
import {
  CheckCircle2, Download, ExternalLink, Flag, Flame, FolderOpen, Languages, Loader2, Pause, Pencil, Play,
  Radio, RotateCcw, Scissors, Sparkles, Square, Trash2, Tv, Volume2, VolumeX, Zap,
} from 'lucide-react';
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, apiUrl, errMsg } from '../api';
import { SPOKEN_LANGUAGE_OPTIONS } from '../components/AnalysisOptions';
import { ClipPreviewModal } from '../components/ClipCard';
import { PageHeader } from '../components/PageHeader';
import { Thumb } from '../components/Thumb';
import { Badge, Button, EmptyState, Field, IconButton, inputCls, Panel, ProgressBar, Segmented, Select, Toggle } from '../components/ui';
import { cx, fmtDur, scoreColor } from '../lib/format';
import { useFetch, useInterval, useWsEvent } from '../lib/hooks';
import { useJobs } from '../stores/jobs';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';
import type { Aspect, Clip, ExportItem, LivePendingClip, LiveSessionDetail, LiveSessionSummary, Preset } from '../types';
import { ASPECTS, DEFAULT_EXPORT } from '../types';

const FLASH_DURATIONS = [30, 45, 60, 90] as const;

function fmtClock(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}` : `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
}

function validateYtInput(v: string): string | null {
  const t = v.trim();
  if (!t) return 'Paste a YouTube Live or video URL (e.g. https://www.youtube.com/live/... or https://www.youtube.com/@Channel/live).';
  if (!/^https?:\/\/([a-z0-9-]+\.)?(youtube\.com|youtu\.be)\//i.test(t)) {
    return 'Enter a valid https://youtube.com or https://youtu.be URL.';
  }
  return null;
}

function syncSliderVars(el: HTMLInputElement | null, min: number, max: number, val: number) {
  if (!el) return;
  el.style.setProperty('--attr-min', String(min));
  el.style.setProperty('--attr-max', String(max));
  el.style.setProperty('--control-value', String(val));
}

export function LiveStudioPage() {
  const uid = useId();
  const formHeadingId = `${uid}-connect-heading`;
  const urlId = `${uid}-live-url`;
  const urlErrId = `${uid}-live-url-err`;
  const rightsId = `${uid}-rights`;
  const rightsErrId = `${uid}-rights-err`;
  const langId = `${uid}-lang`;
  const presetIdAttr = `${uid}-preset`;
  const dvrMinId = `${uid}-dvr-min`;
  const dvrSliderId = `${uid}-dvr-slider`;

  const { settings, load: loadSettings } = useSettings();
  const presetsQ = useFetch<Preset[]>(() => api.presets(), []);
  const sessionsQ = useFetch<LiveSessionSummary[]>(() => api.liveSessions(), []);
  const exportsQ = useFetch<ExportItem[]>(() => api.exports({ limit: 40 }), []);
  const jobs = useJobs((s) => s.jobs);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [session, setSession] = useState<LiveSessionDetail | null>(null);
  const [showNewForm, setShowNewForm] = useState(false);

  // Connect form state
  const [url, setUrl] = useState('');
  const [urlTouched, setUrlTouched] = useState(false);
  const [urlErr, setUrlErr] = useState<string | null>(null);
  const [confirmRights, setConfirmRights] = useState(false);
  const [rightsErr, setRightsErr] = useState<string | null>(null);
  const [language, setLanguage] = useState<string>('hinglish');
  const [presetId, setPresetId] = useState<string>('podcast_pro');
  const [aspect, setAspect] = useState<Aspect>('9:16');
  const [autoHighlight, setAutoHighlight] = useState(true);
  const [dvrMinutes, setDvrMinutes] = useState(30);
  const [targetDuration, setTargetDuration] = useState(45);
  const [connecting, setConnecting] = useState(false);

  // Player & DVR state
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<Hls | null>(null);
  const sliderRef = useRef<HTMLInputElement>(null);
  const urlInputRef = useRef<HTMLInputElement>(null);
  const rightsInputRef = useRef<HTMLInputElement>(null);

  const [playing, setPlaying] = useState(true);
  const [muted, setMuted] = useState(false);
  const [seekRange, setSeekRange] = useState<{ start: number; end: number }>({ start: 0, end: 0 });
  const [videoTime, setVideoTime] = useState(0);
  const [inMark, setInMark] = useState<number | null>(null);
  const [outMark, setOutMark] = useState<number | null>(null);
  const [rightTab, setRightTab] = useState<'clips' | 'transcript'>('clips');
  const [clippingBusy, setClippingBusy] = useState(false);
  const [previewClip, setPreviewClip] = useState<Clip | null>(null);
  const [pendingLocal, setPendingLocal] = useState<Record<string, LivePendingClip>>({});
  const [exportingIds, setExportingIds] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!settings) void loadSettings();
  }, [settings, loadSettings]);

  useEffect(() => {
    if (!settings) return;
    if (settings.transcription_language && settings.transcription_language !== 'auto') {
      setLanguage(settings.transcription_language);
    }
    if (settings.default_preset) setPresetId(settings.default_preset);
    if (settings.default_aspect) setAspect(settings.default_aspect);
  }, [settings]);

  // Auto-select most recent active (or latest) session on initial load
  useEffect(() => {
    if (selectedId || showNewForm) return;
    const list = sessionsQ.data ?? [];
    if (!list.length) return;
    const liveOne = list.find((s) => s.status === 'live' || s.status === 'connecting') ?? list[0];
    if (liveOne) setSelectedId(liveOne.id);
  }, [sessionsQ.data, selectedId, showNewForm]);

  const loadDetail = useCallback(async (id: string) => {
    try {
      const d = await api.liveSession(id);
      setSession(d);
    } catch {
      // session may have been deleted
    }
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setSession(null);
      return;
    }
    void loadDetail(selectedId);
    setInMark(null);
    setOutMark(null);
  }, [selectedId, loadDetail]);

  // Poll active session lightly so DVR timestamps & transcript stay fresh even between WS events
  useInterval(() => {
    if (selectedId && session && (session.status === 'connecting' || session.status === 'live')) {
      void loadDetail(selectedId);
    }
  }, 2500);

  useWsEvent((m) => {
    if (m.type === 'live_session') {
      void sessionsQ.reload(true);
      if (m.data.id === selectedId) {
        setSession((prev) => (prev ? { ...prev, ...m.data } : prev));
      }
    } else if (m.type === 'live_clip_status' && m.data.session_id === selectedId) {
      if (m.data.status === 'failed') {
        toast.error('Live clip failed', m.data.error || 'Could not assemble clip');
        setPendingLocal((prev) => {
          const n = { ...prev };
          delete n[m.data.task_id];
          return n;
        });
      } else {
        setPendingLocal((prev) => ({ ...prev, [m.data.task_id]: m.data }));
      }
    } else if (m.type === 'live_clip_ready' && m.data.session_id === selectedId) {
      setPendingLocal({});
      void loadDetail(selectedId);
      if (m.data.source === 'auto_ai') {
        toast.info('Auto AI Highlight captured!', m.data.title);
      } else {
        toast.success('Live clip ready!', m.data.title);
      }
    } else if (m.type === 'export' || (m.type === 'job' && m.data.kind === 'render')) {
      void exportsQ.reload(true);
      if (selectedId) void loadDetail(selectedId);
    }
  });

  // Attach hls.js to the live stream playlist once ready
  const hlsUrl = session?.playlist_ready ? apiUrl(session.hls_url) : null;
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !hlsUrl) return;

    if (hlsRef.current) {
      hlsRef.current.destroy();
      hlsRef.current = null;
    }

    if (Hls.isSupported()) {
      const hls = new Hls({
        lowLatencyMode: false,
        liveSyncDurationCount: 2,
        liveMaxLatencyDurationCount: 6,
        backBufferLength: 1800,
        maxBufferLength: 60,
      });
      hlsRef.current = hls;
      hls.loadSource(hlsUrl);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        video.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
      });
      hls.on(Hls.Events.ERROR, (_evt, data) => {
        if (!data.fatal) return;
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR) hls.startLoad();
        else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) hls.recoverMediaError();
      });
      return () => {
        hls.destroy();
        hlsRef.current = null;
      };
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = hlsUrl;
      video.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
    }
  }, [hlsUrl]);

  // Sync video seekable window & current playhead
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const sync = () => {
      if (video.seekable && video.seekable.length > 0) {
        const s = video.seekable.start(0);
        const e = video.seekable.end(video.seekable.length - 1);
        setSeekRange({ start: s, end: e });
      }
      setVideoTime(video.currentTime || 0);
      setPlaying(!video.paused);
    };
    video.addEventListener('timeupdate', sync);
    video.addEventListener('progress', sync);
    video.addEventListener('play', sync);
    video.addEventListener('pause', sync);
    return () => {
      video.removeEventListener('timeupdate', sync);
      video.removeEventListener('progress', sync);
      video.removeEventListener('play', sync);
      video.removeEventListener('pause', sync);
    };
  }, [hlsUrl]);

  const dvrStart = session?.dvr_start ?? 0;
  const dvrEnd = session?.dvr_end ?? 0;
  const secondsBehindLive = useMemo(() => {
    if (seekRange.end <= seekRange.start) return 0;
    return Math.max(0, seekRange.end - videoTime);
  }, [seekRange, videoTime]);

  const isAtLiveEdge = secondsBehindLive <= 5.0;
  const playheadStreamTime = useMemo(() => {
    if (!session) return 0;
    return Math.max(dvrStart, Math.min(dvrEnd, dvrEnd - secondsBehindLive));
  }, [session, dvrStart, dvrEnd, secondsBehindLive]);

  useEffect(() => {
    syncSliderVars(sliderRef.current, dvrStart, Math.max(dvrStart + 1, dvrEnd), playheadStreamTime);
  }, [dvrStart, dvrEnd, playheadStreamTime]);

  const seekToStreamTime = useCallback(
    (targetStreamTime: number) => {
      const video = videoRef.current;
      if (!video || seekRange.end <= seekRange.start || dvrEnd <= dvrStart) return;
      const clamped = Math.max(dvrStart, Math.min(dvrEnd, targetStreamTime));
      const behind = dvrEnd - clamped;
      const targetVideoTime = Math.max(seekRange.start, Math.min(seekRange.end - 0.3, seekRange.end - behind));
      video.currentTime = targetVideoTime;
      setVideoTime(targetVideoTime);
    },
    [dvrStart, dvrEnd, seekRange],
  );

  const jumpToLive = useCallback(() => {
    const video = videoRef.current;
    const hls = hlsRef.current;
    if (!video) return;
    if (hls && hls.liveSyncPosition) {
      video.currentTime = hls.liveSyncPosition;
    } else if (seekRange.end > 0) {
      video.currentTime = Math.max(seekRange.start, seekRange.end - 1.0);
    }
    void video.play();
  }, [seekRange]);

  const triggerFlashClip = useCallback(
    async (dur: number) => {
      if (!session || clippingBusy) return;
      setClippingBusy(true);
      try {
        const anchor = isAtLiveEdge ? null : playheadStreamTime;
        const task = await api.clipLive(session.id, { mode: 'last', duration: dur, anchor_stream_time: anchor });
        setPendingLocal((prev) => ({ ...prev, [task.task_id]: task }));
        toast.info(`Clipping last ${dur}s…`, 'Auto-framing 9:16 & generating captions locally.');
      } catch (e) {
        toast.error('Could not capture live clip', errMsg(e));
      } finally {
        setClippingBusy(false);
      }
    },
    [session, clippingBusy, isAtLiveEdge, playheadStreamTime],
  );

  const triggerMarkerClip = useCallback(async () => {
    if (!session || clippingBusy || inMark === null) return;
    const endT = outMark !== null ? outMark : isAtLiveEdge ? dvrEnd : playheadStreamTime;
    if (endT <= inMark + 2.0) {
      toast.warning('Clip range too short', 'Set the Out marker (or wait a few seconds) so the clip is at least 3 seconds long.');
      return;
    }
    setClippingBusy(true);
    try {
      const task = await api.clipLive(session.id, { mode: 'range', start_time: inMark, end_time: endT });
      setPendingLocal((prev) => ({ ...prev, [task.task_id]: task }));
      setInMark(null);
      setOutMark(null);
      toast.info(`Clipping ${fmtClock(inMark)}–${fmtClock(endT)}…`, 'Auto-editing locally.');
    } catch (e) {
      toast.error('Could not capture marker clip', errMsg(e));
    } finally {
      setClippingBusy(false);
    }
  }, [session, clippingBusy, inMark, outMark, isAtLiveEdge, dvrEnd, playheadStreamTime]);

  // Studio keyboard hotkeys (1/2/3/4 flash clip, I/O/C markers, Space play/pause, L jump to live)
  useEffect(() => {
    if (!session || !session.playlist_ready) return;
    const onKey = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement | null;
      if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.tagName === 'SELECT' || tgt.isContentEditable)) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === '1') {
        e.preventDefault();
        void triggerFlashClip(30);
      } else if (k === '2') {
        e.preventDefault();
        void triggerFlashClip(45);
      } else if (k === '3') {
        e.preventDefault();
        void triggerFlashClip(60);
      } else if (k === '4') {
        e.preventDefault();
        void triggerFlashClip(90);
      } else if (k === 'i') {
        e.preventDefault();
        setInMark(playheadStreamTime);
        toast.info(`In marker set at ${fmtClock(playheadStreamTime)}`);
      } else if (k === 'o') {
        e.preventDefault();
        setOutMark(playheadStreamTime);
        toast.info(`Out marker set at ${fmtClock(playheadStreamTime)}`);
      } else if (k === 'c' && inMark !== null) {
        e.preventDefault();
        void triggerMarkerClip();
      } else if (e.key === 'Escape') {
        setInMark(null);
        setOutMark(null);
      } else if (k === 'l') {
        e.preventDefault();
        jumpToLive();
      } else if (e.code === 'Space') {
        e.preventDefault();
        const v = videoRef.current;
        if (v) {
          if (v.paused) void v.play();
          else v.pause();
        }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [session, playheadStreamTime, inMark, triggerFlashClip, triggerMarkerClip, jumpToLive]);

  const submitConnect = async (e: React.FormEvent) => {
    e.preventDefault();
    const uErr = validateYtInput(url);
    const rErr = confirmRights ? null : 'Confirm that you own or have permission to capture and clip this stream.';
    setUrlTouched(true);
    setUrlErr(uErr);
    setRightsErr(rErr);
    if (uErr) {
      urlInputRef.current?.focus();
      return;
    }
    if (rErr) {
      rightsInputRef.current?.focus();
      return;
    }
    setConnecting(true);
    try {
      const created = await api.createLiveSession({
        url: url.trim(),
        confirm_rights: true,
        language,
        preset_id: presetId,
        aspect,
        auto_highlight: autoHighlight,
        dvr_minutes: dvrMinutes,
        target_duration: targetDuration,
      });
      setSession(created);
      setSelectedId(created.id);
      setShowNewForm(false);
      setUrl('');
      setUrlTouched(false);
      void sessionsQ.reload(true);
      toast.success('Connected to stream', created.title);
    } catch (err) {
      toast.error('Could not connect to livestream', errMsg(err));
    } finally {
      setConnecting(false);
    }
  };

  const updateLiveOpt = async (patch: Partial<{ language: string; preset_id: string; aspect: Aspect; auto_highlight: boolean; target_duration: number }>) => {
    if (!session) return;
    try {
      const updated = await api.updateLiveSession(session.id, patch);
      setSession(updated);
    } catch (e) {
      toast.error('Could not update live setting', errMsg(e));
    }
  };

  const stopStream = async () => {
    if (!session) return;
    try {
      const updated = await api.stopLiveSession(session.id);
      setSession(updated);
      void sessionsQ.reload(true);
      toast.info('Live capture stopped', 'Captured clips remain saved in your library.');
    } catch (e) {
      toast.error('Stop failed', errMsg(e));
    }
  };

  const removeSession = async (id: string) => {
    try {
      await api.deleteLiveSession(id);
      void sessionsQ.reload(true);
      if (selectedId === id) {
        setSelectedId(null);
        setSession(null);
      }
      toast.success('Removed DVR buffer', 'All captured clips & exports were kept.');
    } catch (e) {
      toast.error('Could not remove session', errMsg(e));
    }
  };

  const quickExport = async (clip: Clip) => {
    try {
      const r = await api.exportClip(clip.id, DEFAULT_EXPORT);
      setExportingIds((prev) => ({ ...prev, [clip.id]: r.export_id }));
      toast.success('Rendering 1080p MP4', clip.title);
      void exportsQ.reload(true);
    } catch (e) {
      toast.error('Export failed to start', errMsg(e));
    }
  };

  const exportByClip = useMemo(() => {
    const map: Record<string, ExportItem> = {};
    for (const ex of exportsQ.data ?? []) {
      if (!map[ex.clip_id]) map[ex.clip_id] = ex;
    }
    return map;
  }, [exportsQ.data]);

  const allPending = useMemo(() => {
    const merged: Record<string, LivePendingClip> = { ...pendingLocal };
    for (const p of session?.pending_clips ?? []) merged[p.task_id] = p;
    return Object.values(merged).sort((a, b) => b.created_at - a.created_at);
  }, [pendingLocal, session?.pending_clips]);

  const showLauncher = !session || showNewForm;

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Live Stream Clipper"
        subtitle="Watch an ongoing YouTube livestream with a rolling 30-minute local DVR, clip moments in real time, and export Shorts while the stream is still live."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {(sessionsQ.data ?? []).length > 0 && (
              <Select
                aria-label="Switch live session"
                className="w-60"
                value={selectedId ?? ''}
                onChange={(v) => {
                  setShowNewForm(false);
                  setSelectedId(v || null);
                }}
                options={[
                  ...(selectedId ? [] : [{ value: '', label: 'Select a live session…' }]),
                  ...(sessionsQ.data ?? []).map((s) => ({
                    value: s.id,
                    label: `${s.status === 'live' ? '🔴 LIVE · ' : ''}${s.title.slice(0, 38)} (${s.clip_count} clips)`,
                  })),
                ]}
              />
            )}
            {session && !showNewForm && (
              <Button variant="secondary" size="sm" icon={<Radio className="h-3.5 w-3.5" aria-hidden="true" />} onClick={() => setShowNewForm(true)}>
                Connect New Stream
              </Button>
            )}
            {showNewForm && session && (
              <Button variant="ghost" size="sm" onClick={() => setShowNewForm(false)}>
                Back to Active Stream
              </Button>
            )}
          </div>
        }
      />

      <div className="flex flex-col gap-4 p-6">
        {showLauncher && (
          <Panel
            title={
              <span id={formHeadingId} className="flex items-center gap-2">
                <Radio className="h-4 w-4 text-red-400" aria-hidden="true" /> Connect to YouTube Live Stream
              </span>
            }
          >
            <form method="post" action="/api/live/sessions" aria-labelledby={formHeadingId} noValidate onSubmit={submitConnect} className="flex flex-col gap-4">
              <Field
                label="YouTube Live URL *"
                htmlFor={urlId}
                hintId={urlErrId}
                error={urlErr}
                hint={!urlErr ? 'Supports youtube.com/live/<id>, youtube.com/watch?v=<id>, youtu.be/<id>, and youtube.com/@Channel/live.' : undefined}
              >
                <input
                  ref={urlInputRef}
                  id={urlId}
                  name="url"
                  type="url"
                  required
                  autoComplete="off"
                  autoCorrect="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  enterKeyHint="go"
                  placeholder="https://www.youtube.com/live/... or https://www.youtube.com/@Channel/live"
                  aria-invalid={urlErr ? true : undefined}
                  aria-describedby={urlErrId}
                  className={inputCls}
                  value={url}
                  onChange={(e) => {
                    setUrl(e.target.value);
                    if (urlErr && !validateYtInput(e.target.value)) setUrlErr(null);
                  }}
                  onBlur={(e) => {
                    if (url.trim() || urlTouched) {
                      setUrlTouched(true);
                      setUrlErr(validateYtInput(e.target.value));
                    }
                  }}
                />
              </Field>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
                <Field label="Live caption language" htmlFor={langId} hint="Used for instant clips & live AI radar.">
                  <Select id={langId} name="language" value={language} onChange={setLanguage} options={SPOKEN_LANGUAGE_OPTIONS} />
                </Field>
                <Field label="Editing preset" htmlFor={presetIdAttr}>
                  <Select
                    id={presetIdAttr}
                    name="preset_id"
                    value={presetId}
                    onChange={setPresetId}
                    options={(presetsQ.data ?? [{ id: presetId, name: presetId } as Preset]).map((p) => ({
                      value: p.id,
                      label: p.name + (p.builtin ? '' : ' (custom)'),
                    }))}
                  />
                </Field>
                <Field label="Short aspect ratio">
                  <Segmented value={aspect} onChange={setAspect} options={ASPECTS.map((a) => ({ value: a, label: a }))} />
                </Field>
                <Field label="Rolling DVR buffer" htmlFor={dvrMinId} hint="Older unclipped chunks auto-delete.">
                  <Select
                    id={dvrMinId}
                    name="dvr_minutes"
                    value={String(dvrMinutes)}
                    onChange={(v) => setDvrMinutes(Number(v))}
                    options={[
                      { value: '15', label: '15 minutes' },
                      { value: '30', label: '30 minutes (Recommended)' },
                      { value: '60', label: '60 minutes' },
                      { value: '90', label: '90 minutes' },
                    ]}
                  />
                </Field>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-4 rounded-md border border-ink-600 bg-ink-850 p-3">
                <Toggle
                  checked={autoHighlight}
                  onChange={setAutoHighlight}
                  label="Auto Live AI Highlight Radar (rolling Whisper + hook & excitement detection)"
                  hint="Automatically transcribes rolling live audio locally and drops high-scoring moments into your Live Clips tray while you watch."
                />
                <div className="flex items-center gap-2 text-xs text-ink-200">
                  <span>AI target length:</span>
                  <Segmented
                    value={String(targetDuration)}
                    onChange={(v) => setTargetDuration(Number(v))}
                    options={FLASH_DURATIONS.map((d) => ({ value: String(d), label: `${d}s` }))}
                  />
                </div>
              </div>

              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2">
                  <input
                    ref={rightsInputRef}
                    id={rightsId}
                    name="confirm_rights"
                    type="checkbox"
                    required
                    checked={confirmRights}
                    aria-invalid={rightsErr ? true : undefined}
                    aria-describedby={rightsErr ? rightsErrId : undefined}
                    onChange={(e) => {
                      setConfirmRights(e.target.checked);
                      if (e.target.checked) setRightsErr(null);
                    }}
                    className="h-4 w-4 rounded border-ink-500 accent-amber-500"
                  />
                  <label htmlFor={rightsId} className="cursor-pointer text-xs text-ink-100">
                    I confirm I own or am authorized to capture and create clips from this YouTube stream. *
                  </label>
                </div>
                {rightsErr && (
                  <p id={rightsErrId} role="alert" className="text-2xs text-red-300">
                    {rightsErr}
                  </p>
                )}
              </div>

              <div className="flex items-center justify-end gap-2">
                <Button type="submit" variant="primary" size="md" loading={connecting} icon={<Radio className="h-4 w-4" aria-hidden="true" />}>
                  {connecting ? 'Connecting to YouTube Live…' : 'Start Watching & Clipping Live'}
                </Button>
              </div>
            </form>
          </Panel>
        )}

        {session && !showNewForm && (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_430px]">
            {/* Left: Live Monitor + DVR Scrub + Instant Flash Clip Controls */}
            <div className="flex min-w-0 flex-col gap-4">
              <div className="overflow-hidden rounded-lg border border-ink-600 bg-ink-850">
                {/* Stream header bar */}
                <div className="flex flex-wrap items-center gap-2 border-b border-ink-600 px-3.5 py-2.5">
                  {session.status === 'live' ? (
                    <span className="inline-flex items-center gap-1.5 rounded bg-red-500/20 px-2 py-0.5 text-2xs font-bold uppercase tracking-wider text-red-300">
                      <span className="h-2 w-2 animate-pulse rounded-full bg-red-400" aria-hidden="true" />
                      {session.is_live_broadcast ? 'LIVE' : 'LIVE DVR'}
                    </span>
                  ) : session.status === 'connecting' ? (
                    <Badge tone="amber">
                      <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> Buffering stream…
                    </Badge>
                  ) : session.status === 'error' ? (
                    <Badge tone="red">Stream error</Badge>
                  ) : (
                    <Badge>{session.status}</Badge>
                  )}

                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs font-semibold text-ink-50">{session.title}</div>
                    <div className="truncate text-[11px] text-ink-300">
                      {session.channel} · Buffered {fmtDur(session.buffered_seconds)} / {session.dvr_minutes}m rolling DVR
                    </div>
                  </div>

                  {session.ai_scanning && (
                    <Badge tone="amber">
                      <Sparkles className="h-3 w-3 animate-pulse" aria-hidden="true" /> AI scanning live audio…
                    </Badge>
                  )}

                  {(session.status === 'live' || session.status === 'connecting') && (
                    <Button type="button" size="xs" variant="danger" icon={<Square className="h-3 w-3" aria-hidden="true" />} onClick={stopStream}>
                      Stop Capture
                    </Button>
                  )}
                  {(session.status === 'stopped' || session.status === 'ended' || session.status === 'error') && (
                    <Button type="button" size="xs" variant="ghost" icon={<Trash2 className="h-3 w-3" aria-hidden="true" />} onClick={() => removeSession(session.id)}>
                      Clean DVR Buffer
                    </Button>
                  )}
                </div>

                {/* Video Player */}
                <div className="relative flex aspect-video w-full items-center justify-center bg-black">
                  {session.playlist_ready ? (
                    <video ref={videoRef} className="h-full w-full object-contain" playsInline muted={muted} />
                  ) : session.status === 'error' ? (
                    <div className="max-w-md px-6 text-center text-xs text-red-300">
                      <p className="font-semibold">Stream capture failed</p>
                      <p className="mt-1 text-ink-300">{session.error ?? 'Could not read HLS segments from YouTube.'}</p>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center gap-2 text-xs text-ink-200">
                      <Loader2 className="h-6 w-6 animate-spin text-amber-400" aria-hidden="true" />
                      <span>Buffering initial 2-second live DVR segments from YouTube…</span>
                    </div>
                  )}

                  {/* Active In/Out overlay pill */}
                  {(inMark !== null || outMark !== null) && (
                    <div className="pointer-events-none absolute left-3 top-3 flex items-center gap-2 rounded-md border border-amber-400/60 bg-black/80 px-2.5 py-1 text-2xs font-mono text-amber-300">
                      <span>IN: {inMark !== null ? fmtClock(inMark) : '—'}</span>
                      <span>→</span>
                      <span>OUT: {outMark !== null ? fmtClock(outMark) : 'LIVE'}</span>
                    </div>
                  )}
                </div>

                {/* DVR Transport & Scrub Bar */}
                <div className="flex flex-col gap-2 border-t border-ink-600 bg-ink-900 px-3.5 py-2.5">
                  <div className="flex items-center gap-2">
                    <label htmlFor={dvrSliderId} className="sr-only">
                      Live DVR timeline position
                    </label>
                    <input
                      ref={sliderRef}
                      id={dvrSliderId}
                      type="range"
                      className="cf-dvr-slider"
                      min={dvrStart}
                      max={Math.max(dvrStart + 1, dvrEnd)}
                      step={0.5}
                      value={playheadStreamTime}
                      disabled={!session.playlist_ready}
                      aria-valuetext={isAtLiveEdge ? `Live edge (${fmtClock(dvrEnd)})` : `${Math.round(secondsBehindLive)} seconds behind live (${fmtClock(playheadStreamTime)})`}
                      onChange={(e) => {
                        const v = Number(e.target.value);
                        syncSliderVars(e.currentTarget, dvrStart, Math.max(dvrStart + 1, dvrEnd), v);
                        seekToStreamTime(v);
                      }}
                    />
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                    <div className="flex items-center gap-2">
                      <IconButton
                        title={playing ? 'Pause (Space)' : 'Play (Space)'}
                        onClick={() => {
                          const v = videoRef.current;
                          if (!v) return;
                          if (v.paused) void v.play();
                          else v.pause();
                        }}
                      >
                        {playing ? <Pause className="h-4 w-4" aria-hidden="true" /> : <Play className="h-4 w-4" aria-hidden="true" />}
                      </IconButton>
                      <IconButton
                        title={muted ? 'Unmute' : 'Mute'}
                        onClick={() => {
                          setMuted((m) => !m);
                          if (videoRef.current) videoRef.current.muted = !muted;
                        }}
                      >
                        {muted ? <VolumeX className="h-4 w-4" aria-hidden="true" /> : <Volume2 className="h-4 w-4" aria-hidden="true" />}
                      </IconButton>
                      <span className="font-mono text-2xs text-ink-200">
                        {fmtClock(playheadStreamTime)} <span className="text-ink-400">/ {fmtClock(dvrEnd)}</span>
                      </span>
                    </div>

                    <div className="flex items-center gap-2">
                      {isAtLiveEdge ? (
                        <span className="inline-flex items-center gap-1 rounded bg-emerald-500/15 px-2 py-0.5 text-2xs font-semibold text-emerald-300">
                          ● At Live Edge
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={jumpToLive}
                          className="inline-flex min-h-7 items-center gap-1.5 rounded-md border border-red-500/50 bg-red-500/15 px-2.5 py-1 text-2xs font-semibold text-red-200 hover:bg-red-500/25"
                        >
                          <RotateCcw className="h-3 w-3" aria-hidden="true" />
                          -{fmtClock(secondsBehindLive)} behind · Jump to LIVE (L)
                        </button>
                      )}
                    </div>
                  </div>
                </div>

                {/* Flash Clip Deck + In/Out Markers */}
                <div className="flex flex-col gap-3 border-t border-ink-600 bg-ink-850 p-3.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-2xs font-semibold uppercase tracking-wider text-amber-300">
                      ⚡ Instant Flash Clip {isAtLiveEdge ? '(from live edge)' : `(ending at ${fmtClock(playheadStreamTime)})`}
                    </span>
                    <span className="text-[11px] text-ink-300">Hotkeys: 1–4 Flash Clip · I / O / C Markers · L Live</span>
                  </div>

                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {FLASH_DURATIONS.map((dur, idx) => (
                      <button
                        key={dur}
                        type="button"
                        disabled={!session.playlist_ready || clippingBusy}
                        onClick={() => triggerFlashClip(dur)}
                        className="flex min-h-11 items-center justify-center gap-1.5 rounded-md border border-amber-500/50 bg-amber-500/15 px-3 py-2 text-xs font-semibold text-amber-200 transition-colors hover:bg-amber-500/25 disabled:opacity-50"
                      >
                        <Zap className="h-3.5 w-3.5 text-amber-400" aria-hidden="true" />
                        <span>Clip Last {dur}s</span>
                        <kbd className="ml-1 rounded bg-black/40 px-1.5 py-0.5 font-mono text-[10px] text-ink-200">{idx + 1}</kbd>
                      </button>
                    ))}
                  </div>

                  <div className="flex flex-wrap items-center gap-2 border-t border-ink-700 pt-2.5">
                    <Button
                      type="button"
                      size="sm"
                      variant="subtle"
                      disabled={!session.playlist_ready}
                      icon={<Flag className="h-3.5 w-3.5" aria-hidden="true" />}
                      onClick={() => setInMark(playheadStreamTime)}
                    >
                      {inMark !== null ? `In: ${fmtClock(inMark)} (I)` : 'Mark In (I)'}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="subtle"
                      disabled={!session.playlist_ready}
                      icon={<Flag className="h-3.5 w-3.5" aria-hidden="true" />}
                      onClick={() => setOutMark(playheadStreamTime)}
                    >
                      {outMark !== null ? `Out: ${fmtClock(outMark)} (O)` : 'Mark Out (O)'}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="primary"
                      disabled={!session.playlist_ready || inMark === null || clippingBusy}
                      icon={<Scissors className="h-3.5 w-3.5" aria-hidden="true" />}
                      onClick={triggerMarkerClip}
                    >
                      {outMark !== null ? `Cut ${fmtClock(inMark ?? 0)} → ${fmtClock(outMark)} (C)` : 'Cut In → Now (C)'}
                    </Button>
                    {(inMark !== null || outMark !== null) && (
                      <Button
                        type="button"
                        size="xs"
                        variant="ghost"
                        onClick={() => {
                          setInMark(null);
                          setOutMark(null);
                        }}
                      >
                        Clear
                      </Button>
                    )}
                  </div>
                </div>
              </div>

              {/* Live Session On-the-Fly Settings */}
              <Panel title="Live auto-edit & AI radar settings (updates immediately)">
                <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                  <div>
                    <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-ink-300">Caption language</div>
                    <div className="grid grid-cols-3 gap-1">
                      {[
                        { v: 'hinglish', label: 'Hinglish' },
                        { v: 'hi', label: 'हिन्दी', lang: 'hi' },
                        { v: 'en', label: 'English' },
                      ].map((opt) => (
                        <button
                          key={opt.v}
                          type="button"
                          aria-pressed={session.language === opt.v}
                          onClick={() => updateLiveOpt({ language: opt.v })}
                          className={cx(
                            'flex min-h-8 items-center justify-center gap-1 rounded border px-2 py-1 text-xs font-medium transition-colors',
                            session.language === opt.v
                              ? 'border-amber-500/80 bg-amber-500/15 text-ink-50'
                              : 'border-ink-600 bg-ink-900 text-ink-200 hover:border-ink-400',
                          )}
                        >
                          <Languages className="h-3 w-3 text-amber-400" aria-hidden="true" />
                          <span lang={opt.lang}>{opt.label}</span>
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-ink-300">Editing preset</div>
                    <Select
                      aria-label="Live editing preset"
                      value={session.preset_id}
                      onChange={(v) => updateLiveOpt({ preset_id: v })}
                      options={(presetsQ.data ?? [{ id: session.preset_id, name: session.preset_id } as Preset]).map((p) => ({
                        value: p.id,
                        label: p.name,
                      }))}
                    />
                  </div>

                  <div>
                    <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-ink-300">Aspect ratio</div>
                    <Segmented value={session.aspect} onChange={(v) => updateLiveOpt({ aspect: v })} options={ASPECTS.map((a) => ({ value: a, label: a }))} />
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-ink-600 pt-3">
                  <Toggle
                    checked={session.auto_highlight}
                    onChange={(v) => updateLiveOpt({ auto_highlight: v })}
                    label="Auto Live AI Highlight Radar"
                    hint="Automatically transcribes new 30s live chunks & captures standout hooks/laughter."
                  />
                  <div className="flex items-center gap-2 text-2xs text-ink-300">
                    <span>AI target:</span>
                    <Segmented
                      value={String(Math.round(session.target_duration))}
                      onChange={(v) => updateLiveOpt({ target_duration: Number(v) })}
                      options={FLASH_DURATIONS.map((d) => ({ value: String(d), label: `${d}s` }))}
                    />
                  </div>
                </div>
              </Panel>
            </div>

            {/* Right: Live Clips Tray + Live Scrolling Transcript */}
            <div className="flex min-h-[540px] flex-col overflow-hidden rounded-lg border border-ink-600 bg-ink-850">
              <div className="flex items-center gap-1 border-b border-ink-600 px-3 py-2">
                <button
                  type="button"
                  onClick={() => setRightTab('clips')}
                  className={cx(
                    'flex min-h-8 items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-colors',
                    rightTab === 'clips' ? 'bg-ink-700 text-ink-50' : 'text-ink-200 hover:text-ink-50',
                  )}
                >
                  <Flame className="h-3.5 w-3.5 text-amber-400" aria-hidden="true" />
                  Live Clips Tray ({session.clips.length})
                </button>
                <button
                  type="button"
                  onClick={() => setRightTab('transcript')}
                  className={cx(
                    'flex min-h-8 items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-colors',
                    rightTab === 'transcript' ? 'bg-ink-700 text-ink-50' : 'text-ink-200 hover:text-ink-50',
                  )}
                >
                  <Tv className="h-3.5 w-3.5 text-sky-400" aria-hidden="true" />
                  Live Transcript ({session.transcript_tail.length})
                </button>
              </div>

              {rightTab === 'clips' ? (
                <div className="flex flex-1 flex-col gap-2.5 overflow-y-auto p-3">
                  {allPending.map((p) => (
                    <div key={p.task_id} className="rounded-md border border-amber-500/50 bg-amber-500/10 p-2.5">
                      <div className="flex items-center gap-2 text-xs font-semibold text-amber-200">
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-400" aria-hidden="true" />
                        <span>{p.source === 'auto_ai' ? '🤖 Auto AI Highlight' : '⚡ Flash Clip'} ({fmtClock(p.start_time)}–{fmtClock(p.end_time)})</span>
                      </div>
                      <div className="mt-1 text-2xs text-ink-200">{p.message ?? 'Auto-editing clip…'}</div>
                    </div>
                  ))}

                  {session.clips.length === 0 && allPending.length === 0 && (
                    <EmptyState icon={<Zap className="h-7 w-7" />} title="No live clips captured yet">
                      Press <b>Clip Last 30s / 60s</b> (or keys <b>1–4</b>) whenever something viral happens — or let the <b>Auto Live AI Radar</b> catch highlights automatically!
                    </EmptyState>
                  )}

                  {session.clips.map((clip) => {
                    const isAi = clip.analysis_source === 'live_ai' || clip.tags.includes('live_ai');
                    const streamTag = clip.tags.find((t) => t.startsWith('stream:'))?.slice(7);
                    const ex = exportByClip[clip.id];
                    const activeExportId = exportingIds[clip.id] ?? ex?.id;
                    const renderJob = activeExportId
                      ? Object.values(jobs).find((j) => j.kind === 'render' && j.params.export_id === activeExportId)
                      : undefined;
                    const isRendering = renderJob && (renderJob.status === 'queued' || renderJob.status === 'running');
                    const isDone = ex?.status === 'completed';

                    return (
                      <div key={clip.id} className="flex flex-col rounded-md border border-ink-600 bg-ink-900 p-2.5">
                        <div className="flex gap-2.5">
                          <div className="relative h-20 w-14 shrink-0 overflow-hidden rounded border border-ink-600 bg-black">
                            <Thumb
                              src={clip.has_thumbnail ? `/api/clips/${clip.id}/thumbnail?v=${encodeURIComponent(clip.updated_at)}` : null}
                              alt={clip.title}
                              className="h-full w-full"
                            />
                            <span className="absolute bottom-0.5 right-0.5 rounded bg-black/80 px-1 font-mono text-[9px] text-ink-50">
                              {fmtDur(clip.duration)}
                            </span>
                          </div>

                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <Badge tone={isAi ? 'blue' : 'amber'}>{isAi ? '🤖 Auto AI' : '⚡ Manual'}</Badge>
                              {streamTag && <span className="font-mono text-[10px] text-ink-300">{streamTag}</span>}
                              <span className={cx('ml-auto font-mono text-xs font-bold', scoreColor(clip.score))}>{Math.round(clip.score)}</span>
                            </div>
                            <div className="mt-1 truncate text-xs font-semibold text-ink-50" title={clip.title}>
                              {clip.title}
                            </div>
                            {clip.transcript && (
                              <p
                                lang={/[\u0900-\u097F]/.test(clip.transcript) ? 'hi' : undefined}
                                className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-ink-300"
                              >
                                “{clip.transcript}”
                              </p>
                            )}
                          </div>
                        </div>

                        {isRendering && (
                          <div className="mt-2">
                            <ProgressBar value={renderJob.progress} indeterminate={renderJob.status === 'queued'} />
                            <div className="mt-0.5 flex justify-between text-[10px] text-ink-300">
                              <span>{renderJob.message ?? 'Rendering MP4…'}</span>
                              <span className="font-mono">{Math.round(renderJob.progress * 100)}%</span>
                            </div>
                          </div>
                        )}

                        <div className="mt-2.5 flex flex-wrap items-center gap-1.5 border-t border-ink-700 pt-2">
                          {isDone && ex ? (
                            <>
                              <Button
                                type="button"
                                size="xs"
                                variant="primary"
                                icon={<FolderOpen className="h-3 w-3" aria-hidden="true" />}
                                onClick={() => api.revealExport(ex.id)}
                              >
                                Reveal MP4
                              </Button>
                              <a
                                href={apiUrl(`/api/exports/${ex.id}/file?download=true`)}
                                className="inline-flex min-h-6 items-center gap-1 rounded border border-ink-600 px-2 py-0.5 text-2xs text-ink-200 hover:text-ink-50"
                              >
                                <CheckCircle2 className="h-3 w-3 text-emerald-400" aria-hidden="true" /> Download
                              </a>
                            </>
                          ) : (
                            <Button
                              type="button"
                              size="xs"
                              variant="primary"
                              loading={!!isRendering}
                              icon={<Download className="h-3 w-3" aria-hidden="true" />}
                              onClick={() => quickExport(clip)}
                            >
                              1-Click Export
                            </Button>
                          )}

                          <Link to={`/editor/${clip.id}?live=${session.id}`}>
                            <Button type="button" size="xs" variant="subtle" icon={<Pencil className="h-3 w-3" aria-hidden="true" />}>
                              Open in Editor
                            </Button>
                          </Link>

                          <Button type="button" size="xs" variant="ghost" icon={<Play className="h-3 w-3" aria-hidden="true" />} onClick={() => setPreviewClip(clip)}>
                            Preview
                          </Button>

                          <div className="flex-1" />
                          <IconButton
                            title="Delete clip"
                            onClick={async () => {
                              await api.deleteClip(clip.id);
                              void loadDetail(session.id);
                            }}
                          >
                            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                          </IconButton>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="flex flex-1 flex-col gap-1.5 overflow-y-auto p-3">
                  {session.transcript_tail.length === 0 ? (
                    <EmptyState icon={<Tv className="h-7 w-7" />} title="Waiting for rolling live transcript…">
                      {session.auto_highlight
                        ? 'Rolling AI transcription updates every ~30 seconds of buffered live audio.'
                        : 'Enable Auto Live AI Highlight Radar on the left to transcribe the stream in real time.'}
                    </EmptyState>
                  ) : (
                    session.transcript_tail.map((line, i) => (
                      <div key={`${line.s}-${i}`} className="group flex items-start gap-2 rounded-md border border-ink-700 bg-ink-900 p-2 text-xs">
                        <button
                          type="button"
                          onClick={() => seekToStreamTime(line.s)}
                          className="shrink-0 rounded bg-ink-800 px-1.5 py-0.5 font-mono text-[10px] text-amber-300 hover:bg-ink-700"
                          title="Seek DVR player to this line"
                        >
                          {fmtClock(line.s)}
                        </button>
                        <p
                          lang={/[\u0900-\u097F]/.test(line.text) ? 'hi' : undefined}
                          className="min-w-0 flex-1 leading-relaxed text-ink-100"
                        >
                          {line.text}
                        </p>
                        <button
                          type="button"
                          onClick={async () => {
                            try {
                              const sT = Math.max(dvrStart, line.s - 4);
                              const eT = Math.min(dvrEnd, sT + session.target_duration);
                              const task = await api.clipLive(session.id, { mode: 'range', start_time: sT, end_time: eT });
                              setPendingLocal((prev) => ({ ...prev, [task.task_id]: task }));
                              toast.info(`Clipping ${Math.round(eT - sT)}s from ${fmtClock(sT)}…`);
                            } catch (err) {
                              toast.error('Clip failed', errMsg(err));
                            }
                          }}
                          className="shrink-0 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-200 hover:bg-amber-500/20"
                        >
                          Clip {Math.round(session.target_duration)}s
                        </button>
                      </div>
                    ))
                  )}
                </div>
              )}

              <div className="flex items-center justify-between border-t border-ink-600 bg-ink-900 px-3 py-2 text-[11px] text-ink-300">
                <span>Stream stays recording while you edit clips.</span>
                <a href={session.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-ink-200 hover:text-amber-300">
                  YouTube <ExternalLink className="h-3 w-3" aria-hidden="true" />
                </a>
              </div>
            </div>
          </div>
        )}
      </div>

      <ClipPreviewModal clip={previewClip} onClose={() => setPreviewClip(null)} />
    </div>
  );
}
