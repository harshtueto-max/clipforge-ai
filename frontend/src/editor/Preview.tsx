import { Captions as CaptionsIcon, Frame, Grid3x3, Maximize2 } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { apiUrl } from '../api';
import { IconButton } from '../components/ui';
import type { Keyframe, TimelineData } from '../types';
import { CaptionOverlay } from './CaptionOverlay';
import { ASPECT_RATIO, cropRectAt, layoutAt, positionAt, round3, splitCrop } from './geometry';
import { player } from './player';
import { useEditor } from './store';

type Rect = { x: number; y: number; w: number; h: number };

function videoStyle(r: Rect, boxW: number, boxH: number): React.CSSProperties {
  const vw = boxW / r.w;
  const vh = boxH / r.h;
  return { position: 'absolute', width: vw, height: vh, left: -r.x * vw, top: -r.y * vh, maxWidth: 'none', objectFit: 'fill' };
}

export function Preview() {
  const data = useEditor((s) => s.data);
  const timeline = useEditor((s) => s.timeline);
  const time = useEditor((s) => s.time);
  const commit = useEditor((s) => s.commit);
  const setStore = useEditor((s) => s.set);
  const [fullFrame, setFullFrame] = useState(false);
  const [safe, setSafe] = useState(false);
  const [showCaps, setShowCaps] = useState(true);
  const [box, setBox] = useState({ w: 0, h: 0 });
  const area = useRef<HTMLDivElement>(null);
  const mainRef = useRef<HTMLVideoElement>(null);
  const followRef = useRef<HTMLVideoElement>(null);
  const drag = useRef<{ x: number; y: number; ox: number; oy: number; kx: number; ky: number; vw: number; vh: number; full: boolean } | null>(null);

  useLayoutEffect(() => {
    const el = area.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setBox({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    player.attach(mainRef.current);
    player.startLoop();
    return () => {
      player.stopLoop();
      player.attach(null);
    };
  }, [data?.clip.id]);

  useEffect(() => {
    const f = followRef.current;
    if (!f) return;
    player.followers.add(f);
    return () => {
      player.followers.delete(f);
    };
  });

  if (!data || !timeline) return null;
  const m = data.media;
  const srcW = m?.width || 1920;
  const srcH = m?.height || 1080;
  const src = apiUrl(`/api/projects/${data.clip.project_id}/media/stream`);
  const aspect = timeline.aspect;
  const frameAr = fullFrame ? srcW / srcH : ASPECT_RATIO[aspect];
  const pad = 24;
  const availW = Math.max(50, box.w - pad * 2);
  const availH = Math.max(50, box.h - pad * 2);
  let fw = availW;
  let fh = fw / frameAr;
  if (fh > availH) {
    fh = availH;
    fw = fh * frameAr;
  }
  const layout = layoutAt(timeline.reframe?.layouts ?? [], time);
  const single = cropRectAt(timeline, srcW, srcH, time);
  const outAr = ASPECT_RATIO[aspect];
  const topRect = layout ? splitCrop(srcW, srcH, layout.top.x, layout.top.y, outAr) : null;
  const botRect = layout ? splitCrop(srcW, srcH, layout.bottom.x, layout.bottom.y, outAr) : null;
  const halfH = Math.floor(fh / 2);

  const onPointerDown = (e: React.PointerEvent) => {
    if (layout || !m?.has_video) return;
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    const off = timeline.reframe?.offset ?? { x: 0, y: 0 };
    const [kx, ky] = positionAt(timeline.reframe?.keyframes ?? [], time);
    drag.current = { x: e.clientX, y: e.clientY, ox: off.x, oy: off.y, kx, ky, vw: fullFrame ? -fw : fw / single.w, vh: fullFrame ? -fh : fh / single.h, full: fullFrame };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = -(e.clientX - d.x) / d.vw;
    const dy = -(e.clientY - d.y) / d.vh;
    const manual = timeline.reframe?.mode === 'manual';
    const t = time;
    commit((s) => {
      const rf = s.timeline.reframe;
      if (manual) {
        const kfs: Keyframe[] = [...(rf.keyframes ?? [])];
        const nx = Math.min(1, Math.max(0, d.kx + dx));
        const ny = Math.min(1, Math.max(0, d.ky + dy));
        const idx = kfs.findIndex((k) => Math.abs(k.t - t) < 0.25);
        if (idx >= 0) kfs[idx] = { ...kfs[idx], x: round3(nx), y: round3(ny) };
        else {
          kfs.push({ t: round3(t), x: round3(nx), y: round3(ny), cut: false });
          kfs.sort((a, b) => a.t - b.t);
        }
        rf.keyframes = kfs;
      } else {
        rf.offset = { x: round3(Math.max(-0.5, Math.min(0.5, d.ox + dx))), y: round3(Math.max(-0.5, Math.min(0.5, d.oy + dy))) };
      }
      return s;
    }, 'reframe-drag');
  };
  const onPointerUp = () => {
    drag.current = null;
  };

  const video = (ref: React.Ref<HTMLVideoElement>, style: React.CSSProperties, muted: boolean, key: string) => (
    <video
      key={key}
      ref={ref}
      src={src}
      style={style}
      muted={muted}
      playsInline
      preload="auto"
      onPlay={() => !muted && setStore({ playing: true })}
      onPause={() => !muted && setStore({ playing: false })}
      onLoadedMetadata={(e) => {
        if (!muted) {
          const st = useEditor.getState();
          e.currentTarget.currentTime = st.time || timeline.start;
        }
      }}
      onError={() => undefined}
      draggable={false}
    />
  );

  return (
    <div className="relative flex h-full min-h-0 flex-col bg-ink-950">
      <div className="absolute right-2 top-2 z-20 flex gap-1 rounded-md border border-ink-600 bg-ink-850/90 p-0.5 backdrop-blur">
        <IconButton title={fullFrame ? 'Show output crop' : 'Show full frame with crop overlay'} active={fullFrame} onClick={() => setFullFrame((v) => !v)}>
          {fullFrame ? <Frame className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
        </IconButton>
        <IconButton title="Safe-area guides" active={safe} onClick={() => setSafe((v) => !v)}>
          <Grid3x3 className="h-3.5 w-3.5" />
        </IconButton>
        <IconButton title="Caption overlay" active={showCaps} onClick={() => setShowCaps((v) => !v)}>
          <CaptionsIcon className="h-3.5 w-3.5" />
        </IconButton>
      </div>
      <div className="absolute left-2 top-2 z-20 rounded border border-ink-600 bg-ink-850/90 px-1.5 py-0.5 font-mono text-2xs text-ink-200">
        {aspect} · {timeline.reframe?.mode ?? 'auto'}
        {layout ? ' · split' : ''}
        {single.w < cropRectAt({ ...timeline, zooms: [] } as TimelineData, srcW, srcH, time).w - 1e-4 ? ' · zoom' : ''}
      </div>
      <div ref={area} className="checker relative min-h-0 flex-1 overflow-hidden">
        <div
          className="absolute overflow-hidden bg-black shadow-pop"
          style={{ width: fw, height: fh, left: (box.w - fw) / 2, top: (box.h - fh) / 2, cursor: layout || !m?.has_video ? 'default' : 'grab', touchAction: 'none' }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onDoubleClick={() => player.toggle()}
          title={layout ? 'Split-screen layout' : 'Drag to reposition the crop · double-click to play/pause'}
        >
          {/* the main <video> always stays at the same tree position so layout switches never reload it */}
          <div className="absolute left-0 top-0 overflow-hidden" style={{ width: fw, height: !fullFrame && layout ? halfH : fh }}>
            {video(
              mainRef,
              fullFrame
                ? { position: 'absolute', inset: 0, width: '100%', height: '100%' }
                : layout && topRect
                  ? videoStyle(topRect, fw, halfH)
                  : videoStyle(single, fw, fh),
              false,
              'main',
            )}
          </div>
          {!fullFrame && layout && botRect && (
            <>
              <div className="absolute bottom-0 left-0 overflow-hidden" style={{ width: fw, height: fh - halfH }}>
                {video(followRef, videoStyle(botRect, fw, fh - halfH), true, 'follow')}
              </div>
              <div className="pointer-events-none absolute left-0 right-0 h-px bg-black" style={{ top: halfH }} />
            </>
          )}
          {fullFrame && (
            <>
              {(layout ? [topRect!, botRect!] : [single]).map((r, i) => (
                <div
                  key={i}
                  className="pointer-events-none absolute border-2 border-amber-400"
                  style={{ left: r.x * fw, top: r.y * fh, width: r.w * fw, height: r.h * fh, boxShadow: i === 0 ? '0 0 0 9999px rgba(0,0,0,0.55)' : undefined }}
                >
                  <span className="absolute left-0 top-0 bg-amber-400 px-1 text-[9px] font-semibold text-ink-950">{layout ? (i === 0 ? 'TOP' : 'BOTTOM') : aspect}</span>
                </div>
              ))}
            </>
          )}
          {showCaps && !fullFrame && <CaptionOverlay frameW={fw} frameH={fh} />}
          {safe && !fullFrame && (
            <div className="pointer-events-none absolute inset-0">
              <div className="absolute border border-dashed border-sky-300/70" style={{ left: '6%', right: '6%', top: '9%', bottom: '18%' }} />
              <div className="absolute left-1/2 top-0 h-full w-px bg-sky-300/25" />
              <div className="absolute left-0 top-1/2 h-px w-full bg-sky-300/25" />
              <span className="absolute bottom-[18%] left-[6%] translate-y-full text-[9px] text-sky-300/80">platform UI zone</span>
            </div>
          )}
        </div>
        {!m?.has_video && <div className="absolute inset-0 flex items-center justify-center text-xs text-ink-300">Audio-only source</div>}
      </div>
    </div>
  );
}
