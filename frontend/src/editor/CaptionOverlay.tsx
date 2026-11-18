import { useMemo } from 'react';
import type { CaptionItem, CaptionStyle, CaptionWord } from '../types';
import { useEditor } from './store';

function retimeWords(item: CaptionItem): CaptionWord[] {
  const toks = item.text.replace(/\n/g, ' \n ').split(' ').filter((t) => t !== '');
  const real = toks.filter((t) => t !== '\n');
  const ws = item.words ?? [];
  if (ws.length === real.length && ws.every((w) => w.s !== undefined)) return real.map((t, k) => ({ w: t, s: ws[k].s, e: ws[k].e }));
  const n = Math.max(1, real.length);
  const d = (item.end - item.start) / n;
  return real.map((t, k) => ({ w: t, s: item.start + k * d, e: item.start + (k + 1) * d }));
}

function strokeShadow(px: number, color: string): string[] {
  if (px <= 0) return [];
  const out: string[] = [];
  const steps = 16;
  for (let i = 0; i < steps; i++) {
    const a = (i / steps) * Math.PI * 2;
    out.push(`${(Math.cos(a) * px).toFixed(2)}px ${(Math.sin(a) * px).toFixed(2)}px 0 ${color}`);
  }
  return out;
}

function hexA(hex: string, alpha: number): string {
  let c = (hex || '#000000').replace('#', '');
  if (c.length === 3) c = c.split('').map((x) => x + x).join('');
  const n = parseInt(c, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

/** HTML approximation of the libass caption render (see backend captions.build_ass). */
export function CaptionOverlay({ frameH }: { frameW?: number; frameH: number }) {
  const captions = useEditor((s) => s.captions);
  const time = useEditor((s) => s.time);
  const timeline = useEditor((s) => s.timeline);
  const selCaption = useEditor((s) => s.selCaption);
  const keywords = useMemo(() => new Set(((timeline?.keywords as string[] | undefined) ?? []).map((k) => k.toLowerCase())), [timeline?.keywords]);
  if (!captions || !captions.items.length || frameH <= 0) return null;
  const item = captions.items.find((it) => it.start <= time && time < it.end);
  if (!item) return null;
  const st: CaptionStyle = { ...captions.style, ...Object.fromEntries(Object.entries(item.style ?? {}).filter(([, v]) => v !== undefined && v !== null)) } as CaptionStyle;
  const fs = Math.max(6, st.size * frameH);
  const outline = (Number(st.stroke) || 0) * (frameH / 1920) * 1.6;
  const shadow = (Number(st.shadow) || 0) * (frameH / 1920) * 1.6;
  const words = retimeWords(item);
  const toks = item.text.replace(/\n/g, ' \n ').split(' ').filter((t) => t !== '');
  const anim = st.animation;
  let activeK = -1;
  if (anim === 'highlight') {
    for (let k = 0; k < words.length; k++) {
      const nextS = k + 1 < words.length ? words[k + 1].s : item.end;
      if ((k === 0 ? item.start : words[k].s) <= time && time < nextS) activeK = k;
    }
  }
  const shadows = st.box ? [] : [...strokeShadow(outline, st.stroke_color), ...(shadow > 0 ? [`${shadow}px ${shadow}px 0 ${hexA(st.shadow_color ?? '#000000', 0.7)}`] : [])];
  const pos = st.position;
  const margin = Number(st.margin ?? 0.16) * frameH;
  const hasPos = item.style?.pos_x !== undefined && item.style?.pos_y !== undefined && item.style.pos_x !== null;
  const hasDevanagari = /[\u0900-\u097F]/.test(item.text);
  const style: React.CSSProperties = {
    position: 'absolute',
    left: hasPos ? `${Number(item.style.pos_x) * 100}%` : '8%',
    right: hasPos ? undefined : '8%',
    textAlign: 'center',
    fontFamily: `"${st.font}", "Nirmala UI", "Segoe UI", sans-serif`,
    fontSize: fs,
    fontWeight: st.bold ? 800 : 500,
    lineHeight: (hasDevanagari ? 1.25 : 1.15) * Number(st.line_spacing ?? 1),
    color: st.color,
    textShadow: shadows.join(','),
    textTransform: st.uppercase && !hasDevanagari ? 'uppercase' : undefined,
    whiteSpace: 'pre-wrap',
    pointerEvents: 'none',
    transform: hasPos ? 'translate(-50%, -50%)' : pos === 'center' ? 'translateY(-50%)' : undefined,
  };
  if (hasPos) style.top = `${Number(item.style.pos_y) * 100}%`;
  else if (pos === 'top') style.top = margin;
  else if (pos === 'center') style.top = '50%';
  else style.bottom = margin;

  let wi = 0;
  const parts = toks.map((t, idx) => {
    if (t === '\n') return <br key={`br${idx}`} />;
    const k = wi++;
    const w = words[k];
    const base = t.toLowerCase().replace(/[^\p{L}\p{M}\p{N}'%-]/gu, '');
    const isKw = st.highlight_keywords && (keywords.has(base) || /^\d+(\.\d+)?%?$/.test(base));
    let color: string | undefined;
    let scale = 1;
    if (anim === 'highlight' && k === activeK) {
      color = st.highlight_color;
      scale = 1.08;
    } else if (anim === 'karaoke' && w && time >= w.s) color = st.highlight_color;
    else if (isKw) color = st.highlight_color;
    return (
      <span key={idx}>
        <span style={{ color, display: 'inline-block', transform: scale !== 1 ? `scale(${scale})` : undefined, transition: 'transform 60ms' }}>{t}</span>{' '}
      </span>
    );
  });
  const animCls = anim === 'pop' ? 'cf-cap-pop' : anim === 'fade' ? 'cf-cap-fade' : '';
  return (
    <div style={style} key={item.id} lang={hasDevanagari ? 'hi' : undefined} className={`cf-mixed-caption ${animCls}`.trim()}>
      <span
        style={
          st.box
            ? { background: hexA(st.box_color, Number(st.box_opacity ?? 0.5)), padding: `${fs * 0.12}px ${fs * 0.3}px`, borderRadius: 2, boxDecorationBreak: 'clone', WebkitBoxDecorationBreak: 'clone' }
            : undefined
        }
        className={selCaption === item.id ? 'outline outline-1 outline-dashed outline-amber-400/70' : ''}
      >
        {parts}
      </span>
    </div>
  );
}
