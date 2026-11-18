import { Minus, Music, Pause, Play, Plus, Redo2, Repeat, Scissors, SkipBack, SkipForward, Trash2, Undo2, ArchiveRestore, Maximize, Check, Loader2, AlertCircle } from 'lucide-react';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api';
import { IconButton, Kbd } from '../components/ui';
import { cx, fmtTime } from '../lib/format';
import type { TimelineData, Word } from '../types';
import { cutAt, keepSegments, mergeCuts, outputDuration, round3, segmentsForSelection, sourceToOutputLoose } from './geometry';
import { player } from './player';
import { useEditor } from './store';

const RULER_H = 22;
const TRACKS = { video: 38, wave: 44, caps: 30, music: 22, sfx: 24 };
let dragSeq = 0;

function snapWord(words: Word[], t: number, kind: 's' | 'e' | 'both', maxDist = 0.35): number {
  let best = t;
  let bd = maxDist;
  for (const w of words) {
    if (kind !== 'e') {
      const d = Math.abs(w.s - t);
      if (d < bd) {
        bd = d;
        best = w.s;
      }
    }
    if (kind !== 's') {
      const d = Math.abs(w.e - t);
      if (d < bd) {
        bd = d;
        best = w.e;
      }
    }
  }
  return best;
}

export function splitAtPlayhead() {
  const st = useEditor.getState();
  const tl = st.timeline;
  if (!tl) return;
  const t = round3(st.time);
  if (t <= tl.start + 0.05 || t >= tl.end - 0.05 || cutAt(tl.cuts, t)) return;
  if ((tl.splits ?? []).some((s) => Math.abs(s - t) < 0.05)) return;
  st.commit((s) => {
    s.timeline.splits = [...(s.timeline.splits ?? []), t].sort((a, b) => a - b);
    return s;
  });
  const seg = segmentsForSelection({ ...tl, splits: [...(tl.splits ?? []), t] }).find((g) => g.s <= t && t < g.e);
  st.set({ selSegment: seg ?? null, selCut: null });
}

export function deleteSelectedSegment(): string | null {
  const st = useEditor.getState();
  const tl = st.timeline;
  const seg = st.selSegment;
  if (!tl || !seg) return null;
  const next = mergeCuts([...tl.cuts, { s: seg.s, e: seg.e }]);
  if (!keepSegments(tl.start, tl.end, next).length) return 'Cannot remove the entire clip';
  st.commit((s) => {
    s.timeline.cuts = next;
    return s;
  });
  st.set({ selSegment: null, selCut: next.findIndex((c) => c.s <= seg.s && c.e >= seg.e) });
  return null;
}

export function restoreSelectedCut() {
  const st = useEditor.getState();
  if (!st.timeline || st.selCut === null) return;
  const idx = st.selCut;
  st.commit((s) => {
    s.timeline.cuts = s.timeline.cuts.filter((_, i) => i !== idx);
    return s;
  });
  st.set({ selCut: null });
}

export function clearAllCuts() {
  const st = useEditor.getState();
  if (!st.timeline || !st.timeline.cuts.length) return;
  st.commit((s) => {
    s.timeline.cuts = [];
    return s;
  });
  st.set({ selCut: null });
}

function useRange(tl: TimelineData | null, duration: number) {
  const [range, setRange] = useState<{ s: number; e: number } | null>(null);
  const clipId = useEditor((s) => s.clipId);
  useEffect(() => {
    setRange(null);
  }, [clipId]);
  useEffect(() => {
    if (!tl) return;
    setRange((r) => {
      const want = { s: Math.max(0, tl.start - 10), e: Math.min(duration || tl.end + 10, tl.end + 10) };
      if (!r) return want;
      if (tl.start < r.s + 0.5 || tl.end > r.e - 0.5) return { s: Math.min(r.s, want.s), e: Math.max(r.e, want.e) };
      return r;
    });
  }, [tl, duration]);
  return range;
}

export function Timeline({ onOpenTab }: { onOpenTab: (t: string) => void }) {
  const data = useEditor((s) => s.data);
  const tl = useEditor((s) => s.timeline);
  const captions = useEditor((s) => s.captions);
  const time = useEditor((s) => s.time);
  const selSegment = useEditor((s) => s.selSegment);
  const selCut = useEditor((s) => s.selCut);
  const selCaption = useEditor((s) => s.selCaption);
  const selSfx = useEditor((s) => s.selSfx);
  const commit = useEditor((s) => s.commit);
  const setStore = useEditor((s) => s.set);
  const duration = data?.media?.duration ?? 0;
  const range = useRange(tl, duration);
  const scroller = useRef<HTMLDivElement>(null);
  const [viewW, setViewW] = useState(800);
  const [pps, setPps] = useState<number | null>(null);
  const [peaks, setPeaks] = useState<number[] | null>(null);
  const [waveErr, setWaveErr] = useState(false);
  const canvas = useRef<HTMLCanvasElement>(null);

  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setViewW(el.clientWidth));
    ro.observe(el);
    setViewW(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const span = range ? range.e - range.s : 1;
  const fitPps = Math.max(2, (viewW - 4) / span);
  const scale = Math.min(Math.max(pps ?? fitPps, fitPps * 0.5, 2), Math.min(400, 30000 / span));
  const width = span * scale;
  const vs = range?.s ?? 0;
  const X = useCallback((t: number) => (t - vs) * scale, [vs, scale]);

  // waveform for the visible range
  const pid = data?.clip.project_id;
  useEffect(() => {
    if (!pid || !range) return;
    const points = Math.max(50, Math.min(4000, Math.round(width / 2)));
    const h = window.setTimeout(() => {
      api
        .waveform(pid, range.s, range.e, points)
        .then((r) => {
          setPeaks(r.peaks);
          setWaveErr(false);
        })
        .catch(() => setWaveErr(true));
    }, 200);
    return () => window.clearTimeout(h);
  }, [pid, range, width]);

  useEffect(() => {
    const c = canvas.current;
    if (!c || !peaks || !tl) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = Math.max(1, Math.floor(width * dpr));
    c.height = Math.floor(TRACKS.wave * dpr);
    const g = c.getContext('2d');
    if (!g) return;
    g.scale(dpr, dpr);
    g.clearRect(0, 0, width, TRACKS.wave);
    const n = peaks.length;
    const bw = width / n;
    const mid = TRACKS.wave / 2;
    for (let i = 0; i < n; i++) {
      const t = vs + (i + 0.5) * (span / n);
      const inClip = t >= tl.start && t <= tl.end && !cutAt(tl.cuts, t);
      g.fillStyle = inClip ? '#5eb8ff' : '#3a3f4a';
      const h = Math.max(1, peaks[i] * (TRACKS.wave - 6));
      g.fillRect(i * bw, mid - h / 2, Math.max(1, bw - 0.4), h);
    }
  }, [peaks, width, tl, vs, span]);

  // ctrl+wheel zoom around the cursor
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const cursorX = e.clientX - rect.left + el.scrollLeft;
      const tAt = vs + cursorX / scale;
      const next = Math.min(Math.min(400, 30000 / span), Math.max(fitPps * 0.5, scale * (e.deltaY < 0 ? 1.2 : 1 / 1.2)));
      setPps(next);
      requestAnimationFrame(() => {
        el.scrollLeft = (tAt - vs) * next - (e.clientX - rect.left);
      });
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [vs, scale, span, fitPps]);

  // keep the playhead visible while playing
  const playing = useEditor((s) => s.playing);
  useEffect(() => {
    const el = scroller.current;
    if (!el || !playing) return;
    const x = X(time);
    if (x < el.scrollLeft || x > el.scrollLeft + el.clientWidth - 30) el.scrollLeft = x - 60;
  }, [time, playing, X]);

  const segs = useMemo(() => (tl ? segmentsForSelection(tl) : []), [tl]);
  if (!tl || !data || !range || !captions) return <div className="h-48 border-t border-ink-600 bg-ink-850" />;
  const words = data.words;
  const assets = Object.fromEntries(data.assets.map((a) => [a.id, a]));

  const timeFromEvent = (clientX: number) => {
    const el = scroller.current!;
    const rect = el.getBoundingClientRect();
    return vs + (clientX - rect.left + el.scrollLeft) / scale;
  };

  const beginDrag = (e: React.PointerEvent, onMove: (dt: number, ev: PointerEvent) => void, onEnd?: () => void) => {
    e.preventDefault();
    e.stopPropagation();
    const x0 = e.clientX;
    const move = (ev: PointerEvent) => onMove((ev.clientX - x0) / scale, ev);
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      onEnd?.();
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const seekDrag = (e: React.PointerEvent) => {
    player.pause();
    player.seek(timeFromEvent(e.clientX));
    beginDrag(e, (_dt, ev) => player.seek(timeFromEvent(ev.clientX)));
  };

  const trim = (which: 'start' | 'end') => (e: React.PointerEvent) => {
    const orig = which === 'start' ? tl.start : tl.end;
    const key = `trim-${which}-${++dragSeq}`;
    beginDrag(e, (dt, ev) => {
      let t = orig + dt;
      if (!ev.altKey && !ev.shiftKey) t = snapWord(words, t, which === 'start' ? 's' : 'e');
      commit((s) => {
        if (which === 'start') s.timeline.start = round3(Math.max(0, Math.min(t, s.timeline.end - 1)));
        else s.timeline.end = round3(Math.min(duration || Infinity, Math.max(t, s.timeline.start + 1)));
        return s;
      }, key);
      player.seek(which === 'start' ? Math.max(0, Math.min(t, tl.end - 1)) : Math.max(t, tl.start + 1));
    });
  };

  const cutEdge = (idx: number, edge: 's' | 'e') => (e: React.PointerEvent) => {
    const orig = tl.cuts[idx][edge];
    const key = `cut-${idx}-${edge}-${++dragSeq}`;
    setStore({ selCut: idx, selSegment: null });
    beginDrag(
      e,
      (dt, ev) => {
        let t = orig + dt;
        if (!ev.altKey && !ev.shiftKey) t = snapWord(words, t, edge === 's' ? 'e' : 's', 0.25);
        commit((s) => {
          const c = s.timeline.cuts[idx];
          if (!c) return s;
          if (edge === 's') c.s = round3(Math.max(s.timeline.start, Math.min(t, c.e - 0.05)));
          else c.e = round3(Math.min(s.timeline.end, Math.max(t, c.s + 0.05)));
          delete c.auto;
          return s;
        }, key);
      },
      () =>
        commit((s) => {
          s.timeline.cuts = mergeCuts(s.timeline.cuts);
          return s;
        }, key),
    );
  };

  const capEdge = (id: string, edge: 'start' | 'end') => (e: React.PointerEvent) => {
    const items = captions.items;
    const i = items.findIndex((x) => x.id === id);
    if (i < 0) return;
    const orig = items[i][edge];
    const lo = edge === 'start' ? (items[i - 1]?.end ?? 0) : items[i].start + 0.12;
    const hi = edge === 'start' ? items[i].end - 0.12 : (items[i + 1]?.start ?? Infinity);
    if (hi < lo) return;
    const key = `cap-${id}-${edge}-${++dragSeq}`;
    setStore({ selCaption: id });
    beginDrag(e, (dt, ev) => {
      let t = orig + dt;
      if (!ev.altKey && !ev.shiftKey) t = snapWord(words, t, edge === 'start' ? 's' : 'e', 0.15);
      t = round3(Math.min(hi, Math.max(lo, t)));
      commit((s) => {
        const it = s.captions.items.find((x) => x.id === id);
        if (it) {
          it[edge] = t;
          if (it.end < it.start + 0.12) it.end = round3(it.start + 0.12);
        }
        return s;
      }, key);
    });
  };

  const sfxDrag = (id: string) => (e: React.PointerEvent) => {
    const it = tl.sfx.find((x) => x.id === id);
    if (!it) return;
    const orig = it.t;
    const key = `sfx-${id}-${++dragSeq}`;
    setStore({ selSfx: id });
    beginDrag(e, (dt) => {
      commit((s) => {
        const x = s.timeline.sfx.find((y) => y.id === id);
        if (x) x.t = round3(Math.max(s.timeline.start, Math.min(s.timeline.end, orig + dt)));
        return s;
      }, key);
    });
  };

  const onVideoTrackDown = (e: React.PointerEvent) => {
    const t = timeFromEvent(e.clientX);
    const ci = tl.cuts.findIndex((c) => c.s <= t && t < c.e && t >= tl.start && t <= tl.end);
    if (ci >= 0) setStore({ selCut: ci, selSegment: null });
    else {
      const seg = segs.find((g) => g.s <= t && t < g.e) ?? null;
      setStore({ selSegment: seg, selCut: null });
    }
    player.pause();
    player.seek(t);
  };

  // ruler ticks
  const step = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300].find((s) => s * scale >= 70) ?? 600;
  const ticks: number[] = [];
  for (let t = Math.ceil(vs / step) * step; t <= range.e; t += step) ticks.push(t);
  const totalH = RULER_H + TRACKS.video + TRACKS.wave + TRACKS.caps + TRACKS.music + TRACKS.sfx;
  const music = tl.music?.asset_id ? assets[tl.music.asset_id] : null;
  const scenes = data.scenes;

  return (
    <div className="flex h-full min-h-0 flex-col border-t border-ink-600 bg-ink-850">
      <TimelineToolbar
        onZoom={(f) => setPps(Math.min(Math.min(400, 30000 / span), Math.max(fitPps * 0.5, scale * f)))}
        onFit={() => {
          setPps(null);
          if (scroller.current) scroller.current.scrollLeft = 0;
        }}
      />
      <div className="flex min-h-0 flex-1">
        <div className="w-[76px] shrink-0 border-r border-ink-600 bg-ink-800 text-2xs text-ink-300">
          <div style={{ height: RULER_H }} />
          <TrackLabel h={TRACKS.video}>Video</TrackLabel>
          <TrackLabel h={TRACKS.wave}>Audio</TrackLabel>
          <TrackLabel h={TRACKS.caps}>Captions</TrackLabel>
          <TrackLabel h={TRACKS.music}>Music</TrackLabel>
          <TrackLabel h={TRACKS.sfx}>SFX</TrackLabel>
        </div>
        <div ref={scroller} className="relative min-w-0 flex-1 overflow-x-auto overflow-y-hidden">
          <div className="relative select-none" style={{ width, height: totalH }}>
            {/* ruler */}
            <div className="absolute left-0 right-0 top-0 cursor-pointer border-b border-ink-600 bg-ink-800" style={{ height: RULER_H }} onPointerDown={seekDrag}>
              {ticks.map((t) => (
                <div key={t} className="absolute top-0 h-full border-l border-ink-500" style={{ left: X(t) }}>
                  <span className="absolute left-1 top-0.5 font-mono text-[9px] text-ink-300">{fmtTime(t)}</span>
                </div>
              ))}
            </div>
            {/* video track */}
            <div className="absolute left-0 right-0" style={{ top: RULER_H, height: TRACKS.video }} onPointerDown={onVideoTrackDown}>
              <div className="absolute inset-y-1 rounded-sm bg-ink-700/40" style={{ left: 0, width }} />
              {segs.map((g, i) => (
                <div
                  key={i}
                  className={cx('absolute inset-y-1 rounded-sm border', selSegment && Math.abs(selSegment.s - g.s) < 0.002 && Math.abs(selSegment.e - g.e) < 0.002 ? 'border-amber-300 bg-amber-500/45' : 'border-amber-500/40 bg-amber-500/20')}
                  style={{ left: X(g.s), width: Math.max(1, X(g.e) - X(g.s)) }}
                />
              ))}
              {tl.cuts.map((c, i) =>
                c.e <= tl.start || c.s >= tl.end ? null : (
                  <div
                    key={i}
                    className={cx('hatch absolute inset-y-1 rounded-sm border', selCut === i ? 'border-red-300' : 'border-red-500/40')}
                    style={{ left: X(Math.max(c.s, tl.start)), width: Math.max(2, X(Math.min(c.e, tl.end)) - X(Math.max(c.s, tl.start))) }}
                    title={`Removed ${fmtTime(c.s, true)} – ${fmtTime(c.e, true)}${c.auto ? ' (auto silence cut)' : ''}`}
                  >
                    <div className="absolute inset-y-0 -left-1 w-2 cursor-ew-resize" onPointerDown={cutEdge(i, 's')} />
                    <div className="absolute inset-y-0 -right-1 w-2 cursor-ew-resize" onPointerDown={cutEdge(i, 'e')} />
                  </div>
                ),
              )}
              {scenes.map((sc, i) => (
                <div key={i} className="pointer-events-none absolute inset-y-0 w-px bg-violet-400/60" style={{ left: X(sc.s) }} title="Scene change" />
              ))}
              {(tl.splits ?? []).map((s) => (
                <div key={s} className="pointer-events-none absolute inset-y-0 w-px border-l border-dashed border-amber-200/80" style={{ left: X(s) }} />
              ))}
            </div>
            {/* waveform */}
            <div className="absolute left-0 right-0 border-t border-ink-650" style={{ top: RULER_H + TRACKS.video, height: TRACKS.wave }} onPointerDown={seekDrag}>
              {waveErr ? <div className="px-2 py-3 text-2xs text-ink-400">Waveform not available</div> : <canvas ref={canvas} style={{ width, height: TRACKS.wave }} />}
            </div>
            {/* captions */}
            <div className="absolute left-0 right-0 border-t border-ink-650" style={{ top: RULER_H + TRACKS.video + TRACKS.wave, height: TRACKS.caps }}>
              {captions.items.map((it) => (
                <div
                  key={it.id}
                  onPointerDown={(e) => {
                    e.stopPropagation();
                    setStore({ selCaption: it.id });
                    onOpenTab('captions');
                    player.pause();
                    player.seek(it.start);
                  }}
                  className={cx('absolute inset-y-1 cursor-pointer overflow-hidden rounded-sm border px-1 text-[10px] leading-[20px] text-ink-50', selCaption === it.id ? 'border-sky-300 bg-sky-500/45' : 'border-sky-500/40 bg-sky-500/20 hover:bg-sky-500/30')}
                  style={{ left: X(it.start), width: Math.max(3, X(it.end) - X(it.start)) }}
                  title={it.text}
                >
                  <span className="pointer-events-none whitespace-nowrap">{it.text.replace(/\n/g, ' / ')}</span>
                  <div className="absolute inset-y-0 left-0 w-1.5 cursor-ew-resize hover:bg-sky-200/50" onPointerDown={capEdge(it.id, 'start')} />
                  <div className="absolute inset-y-0 right-0 w-1.5 cursor-ew-resize hover:bg-sky-200/50" onPointerDown={capEdge(it.id, 'end')} />
                </div>
              ))}
            </div>
            {/* music */}
            <div className="absolute left-0 right-0 border-t border-ink-650" style={{ top: RULER_H + TRACKS.video + TRACKS.wave + TRACKS.caps, height: TRACKS.music }}>
              {music ? (
                <div
                  className="absolute inset-y-0.5 flex cursor-pointer items-center gap-1 overflow-hidden rounded-sm border border-emerald-500/40 bg-emerald-500/20 px-1.5 text-[10px] text-emerald-100"
                  style={{ left: X(tl.start), width: X(tl.end) - X(tl.start) }}
                  onClick={() => onOpenTab('audio')}
                  title="Background music (click to edit)"
                >
                  <Music className="h-3 w-3 shrink-0" />
                  <span className="truncate">
                    {music.name} · vol {Math.round(tl.music.volume * 100)}%{tl.music.ducking ? ' · ducking' : ''}
                  </span>
                </div>
              ) : (
                <button className="absolute inset-y-0 left-1 text-[10px] text-ink-400 hover:text-ink-100" style={{ left: X(tl.start) }} onClick={() => onOpenTab('audio')}>
                  + add music
                </button>
              )}
            </div>
            {/* sfx */}
            <div className="absolute left-0 right-0 border-t border-ink-650" style={{ top: RULER_H + TRACKS.video + TRACKS.wave + TRACKS.caps + TRACKS.music, height: TRACKS.sfx }}>
              {tl.sfx.map((fx) => (
                <div
                  key={fx.id}
                  onPointerDown={sfxDrag(fx.id)}
                  onClick={() => onOpenTab('audio')}
                  className={cx('absolute top-0.5 flex h-5 -translate-x-1/2 cursor-grab items-center rounded-sm border px-1 text-[9px]', selSfx === fx.id ? 'border-fuchsia-300 bg-fuchsia-500/50' : 'border-fuchsia-500/50 bg-fuchsia-500/25 text-fuchsia-100')}
                  style={{ left: X(fx.t) }}
                  title={`${assets[fx.asset_id]?.name ?? 'SFX'} @ ${fmtTime(fx.t, true)} — drag to move`}
                >
                  {(assets[fx.asset_id]?.name ?? 'sfx').slice(0, 10)}
                </div>
              ))}
            </div>
            {/* out-of-clip shading + trim handles */}
            <div className="pointer-events-none absolute bg-black/45" style={{ left: 0, width: Math.max(0, X(tl.start)), top: RULER_H, height: totalH - RULER_H }} />
            <div className="pointer-events-none absolute bg-black/45" style={{ left: X(tl.end), right: 0, top: RULER_H, height: totalH - RULER_H }} />
            <div className="absolute z-10 w-2.5 -translate-x-full cursor-ew-resize rounded-l bg-amber-500 hover:bg-amber-300" style={{ left: X(tl.start), top: RULER_H, height: TRACKS.video }} onPointerDown={trim('start')} title="Drag to trim start (snaps to words; hold Alt for free trim)" />
            <div className="absolute z-10 w-2.5 cursor-ew-resize rounded-r bg-amber-500 hover:bg-amber-300" style={{ left: X(tl.end), top: RULER_H, height: TRACKS.video }} onPointerDown={trim('end')} title="Drag to trim end (snaps to words; hold Alt for free trim)" />
            {/* playhead */}
            <div className="absolute top-0 z-20" style={{ left: X(time), height: totalH }}>
              <div className="absolute -left-[5px] top-0 h-3 w-[11px] cursor-ew-resize rounded-b-sm bg-white" onPointerDown={seekDrag} />
              <div className="pointer-events-none absolute left-0 top-0 h-full w-px bg-white" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function TrackLabel({ h, children }: { h: number; children: React.ReactNode }) {
  return (
    <div className="flex items-center border-t border-ink-650 px-2 font-medium uppercase tracking-wider" style={{ height: h }}>
      {children}
    </div>
  );
}

function TimelineToolbar({ onZoom, onFit }: { onZoom: (f: number) => void; onFit: () => void }) {
  const tl = useEditor((s) => s.timeline);
  const data = useEditor((s) => s.data);
  const time = useEditor((s) => s.time);
  const playing = useEditor((s) => s.playing);
  const loop = useEditor((s) => s.loop);
  const past = useEditor((s) => s.past.length);
  const future = useEditor((s) => s.future.length);
  const selSegment = useEditor((s) => s.selSegment);
  const selCut = useEditor((s) => s.selCut);
  const saveState = useEditor((s) => s.saveState);
  const saveError = useEditor((s) => s.saveError);
  const { undo, redo, set } = useEditor.getState();
  if (!tl) return null;
  const fps = data?.media?.fps || 30;
  const segs = keepSegments(tl.start, tl.end, tl.cuts);
  const outDur = outputDuration(segs);
  const outT = sourceToOutputLoose(time, segs);
  return (
    <div className="flex h-10 shrink-0 items-center gap-1 border-b border-ink-600 px-2">
      <IconButton title="Previous frame (←) · Shift = 1s" onClick={() => player.step(-1 / fps)}>
        <SkipBack className="h-3.5 w-3.5" />
      </IconButton>
      <button
        title="Play / pause (Space)"
        onClick={() => player.toggle()}
        className="flex h-7 w-9 items-center justify-center rounded-md bg-amber-500 text-ink-950 hover:bg-amber-400"
      >
        {playing ? <Pause className="h-4 w-4" fill="currentColor" /> : <Play className="h-4 w-4" fill="currentColor" />}
      </button>
      <IconButton title="Next frame (→) · Shift = 1s" onClick={() => player.step(1 / fps)}>
        <SkipForward className="h-3.5 w-3.5" />
      </IconButton>
      <IconButton title="Loop clip" active={loop} onClick={() => set({ loop: !loop })}>
        <Repeat className="h-3.5 w-3.5" />
      </IconButton>
      <div className="ml-1 flex flex-col leading-tight">
        <span className="font-mono text-xs text-ink-50">
          {fmtTime(outT, true)} <span className="text-ink-400">/ {fmtTime(outDur, true)}</span>
        </span>
        <span className="font-mono text-[9px] text-ink-400">src {fmtTime(time, true)}</span>
      </div>
      <div className="mx-2 h-5 w-px bg-ink-600" />
      <IconButton title="Split at playhead (S)" onClick={splitAtPlayhead}>
        <Scissors className="h-3.5 w-3.5" />
      </IconButton>
      <IconButton title="Delete selected segment (Del) — adds a cut" disabled={!selSegment} onClick={() => deleteSelectedSegment()}>
        <Trash2 className="h-3.5 w-3.5" />
      </IconButton>
      <IconButton title="Restore selected cut" disabled={selCut === null} onClick={restoreSelectedCut}>
        <ArchiveRestore className="h-3.5 w-3.5" aria-hidden="true" />
      </IconButton>
      {tl.cuts.some((c) => c.e > tl.start && c.s < tl.end) && (
        <button
          type="button"
          title="Remove all jump cuts in this clip (keep continuous uncut speech)"
          onClick={clearAllCuts}
          className="h-6 rounded border border-ink-600 bg-ink-800 px-1.5 text-[10px] font-medium text-ink-200 hover:bg-ink-700 hover:text-ink-50"
        >
          Clear cuts
        </button>
      )}
      <div className="mx-2 h-5 w-px bg-ink-600" />
      <IconButton title="Undo (Ctrl+Z)" disabled={!past} onClick={undo}>
        <Undo2 className="h-3.5 w-3.5" />
      </IconButton>
      <IconButton title="Redo (Ctrl+Shift+Z / Ctrl+Y)" disabled={!future} onClick={redo}>
        <Redo2 className="h-3.5 w-3.5" />
      </IconButton>
      <div className="flex-1" />
      <span className="hidden items-center gap-1 text-[10px] text-ink-400 2xl:flex">
        <Kbd>Space</Kbd> play <Kbd>S</Kbd> split <Kbd>Del</Kbd> cut <Kbd>Ctrl</Kbd>+wheel zoom
      </span>
      <span className="mx-2 text-2xs text-ink-300">
        Output <b className="font-mono text-ink-50">{outDur.toFixed(1)}s</b> · {tl.cuts.filter((c) => c.e > tl.start && c.s < tl.end).length} cuts
      </span>
      <SaveIndicator state={saveState} error={saveError} />
      <div className="mx-1 h-5 w-px bg-ink-600" />
      <IconButton title="Zoom out" onClick={() => onZoom(1 / 1.5)}>
        <Minus className="h-3.5 w-3.5" />
      </IconButton>
      <IconButton title="Zoom in" onClick={() => onZoom(1.5)}>
        <Plus className="h-3.5 w-3.5" />
      </IconButton>
      <IconButton title="Fit" onClick={onFit}>
        <Maximize className="h-3.5 w-3.5" />
      </IconButton>
    </div>
  );
}

export function SaveIndicator({ state, error }: { state: string; error: string | null }) {
  if (state === 'saving' || state === 'dirty')
    return (
      <span className="flex items-center gap-1 text-2xs text-ink-300">
        <Loader2 className="h-3 w-3 animate-spin" /> {state === 'saving' ? 'Saving…' : 'Unsaved'}
      </span>
    );
  if (state === 'error')
    return (
      <span className="flex items-center gap-1 text-2xs text-red-300" title={error ?? ''}>
        <AlertCircle className="h-3 w-3" /> Save failed
      </span>
    );
  return (
    <span className="flex items-center gap-1 text-2xs text-emerald-400">
      <Check className="h-3 w-3" /> Saved
    </span>
  );
}
