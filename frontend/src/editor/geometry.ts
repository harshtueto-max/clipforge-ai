// Client-side mirrors of backend timeline math (segmentation.py / reframe.py / renderer.py).
import type { Aspect, Cut, Keyframe, Layout, TimelineData, Zoom } from '../types';

export const ASPECT_RATIO: Record<Aspect, number> = { '9:16': 9 / 16, '16:9': 16 / 9, '1:1': 1, '4:5': 4 / 5 };

export function cropBox(srcW: number, srcH: number, aspect: Aspect, zoom = 1): [number, number] {
  const ar = ASPECT_RATIO[aspect] ?? 9 / 16;
  const srcAr = srcW / Math.max(1, srcH);
  let cw: number;
  let ch: number;
  if (srcAr >= ar) {
    ch = 1;
    cw = (srcH * ar) / srcW;
  } else {
    cw = 1;
    ch = srcW / ar / srcH;
  }
  const z = Math.max(1, zoom);
  return [cw / z, ch / z];
}

export function positionAt(kfs: Keyframe[], t: number): [number, number] {
  if (!kfs.length) return [0.5, 0.5];
  if (t <= kfs[0].t) return [kfs[0].x, kfs[0].y];
  for (let i = 0; i < kfs.length - 1; i++) {
    const a = kfs[i];
    const b = kfs[i + 1];
    if (a.t <= t && t <= b.t) {
      if (b.cut) return t < b.t ? [a.x, a.y] : [b.x, b.y];
      const r = (t - a.t) / Math.max(1e-6, b.t - a.t);
      return [a.x + (b.x - a.x) * r, a.y + (b.y - a.y) * r];
    }
  }
  const l = kfs[kfs.length - 1];
  return [l.x, l.y];
}

export function keepSegments(start: number, end: number, cuts: Cut[]): [number, number][] {
  const cs = cuts
    .filter((c) => c.e > start && c.s < end)
    .map((c) => [Math.max(start, c.s), Math.min(end, c.e)] as [number, number])
    .sort((a, b) => a[0] - b[0]);
  const segs: [number, number][] = [];
  let cur = start;
  for (const [s, e] of cs) {
    if (s > cur + 1e-3) segs.push([cur, s]);
    cur = Math.max(cur, e);
  }
  if (end > cur + 1e-3) segs.push([cur, end]);
  return segs.filter(([a, b]) => b - a >= 0.04);
}

export function outputDuration(segs: [number, number][]): number {
  return segs.reduce((acc, [a, b]) => acc + (b - a), 0);
}

export function sourceToOutput(t: number, segs: [number, number][]): number | null {
  let acc = 0;
  for (const [s, e] of segs) {
    if (s - 1e-6 <= t && t <= e + 1e-6) return acc + (Math.min(Math.max(t, s), e) - s);
    acc += e - s;
  }
  return null;
}

/** Output time for display: inside a cut maps to the next kept segment start. */
export function sourceToOutputLoose(t: number, segs: [number, number][]): number {
  let acc = 0;
  for (const [s, e] of segs) {
    if (t < s) return acc;
    if (t <= e) return acc + (t - s);
    acc += e - s;
  }
  return acc;
}

export function zoomAt(zooms: Zoom[], t: number): number {
  let z = 1;
  for (const zz of zooms) if (zz.s <= t && t < zz.e) z = zz.scale || 1;
  return z;
}

export function layoutAt(layouts: Layout[], t: number): Layout | null {
  let l: Layout | null = null;
  for (const x of layouts) if (x.s <= t && t < x.e && x.layout === 'split') l = x;
  return l;
}

export function cutAt(cuts: Cut[], t: number): Cut | null {
  for (const c of cuts) if (c.s <= t && t < c.e - 0.01) return c;
  return null;
}

/** Normalize, sort and merge overlapping cuts. */
export function mergeCuts(cuts: Cut[]): Cut[] {
  const sorted = cuts.filter((c) => c.e - c.s > 0.01).map((c) => ({ ...c })).sort((a, b) => a.s - b.s);
  const out: Cut[] = [];
  for (const c of sorted) {
    const last = out[out.length - 1];
    if (last && c.s <= last.e + 0.005) {
      last.e = Math.max(last.e, c.e);
      if (!c.auto) delete last.auto;
    } else out.push(c);
  }
  return out.map((c) => ({ ...c, s: round3(c.s), e: round3(c.e) }));
}

export function round3(v: number): number {
  return Math.round(v * 1000) / 1000;
}

/** Crop rectangle (normalized source coords) for the single-crop layout at time t. */
export function cropRectAt(tl: TimelineData, srcW: number, srcH: number, t: number): { x: number; y: number; w: number; h: number } {
  const zoom = zoomAt(tl.zooms ?? [], t);
  const [cw, ch] = cropBox(srcW, srcH, tl.aspect, zoom);
  const rf = tl.reframe;
  const kfs = rf?.mode === 'center' ? [{ t: tl.start, x: 0.5, y: 0.5 }] : rf?.keyframes?.length ? rf.keyframes : [{ t: tl.start, x: 0.5, y: 0.5 }];
  let [cx, cy] = positionAt(kfs, t);
  cx += Number(rf?.offset?.x ?? 0);
  cy += Number(rf?.offset?.y ?? 0);
  const x = Math.min(Math.max(cx - cw / 2, 0), 1 - cw);
  const y = Math.min(Math.max(cy - ch / 2, 0), 1 - ch);
  return { x, y, w: cw, h: ch };
}

/** Split-screen half crop (mirrors renderer._split_crop) for a face centre; frameAr = output W/H. */
export function splitCrop(srcW: number, srcH: number, cx: number, cy: number, frameAr: number): { x: number; y: number; w: number; h: number } {
  const halfAr = frameAr * 2;
  let ch = srcH * 0.82;
  let cw = ch * halfAr;
  if (cw > srcW * 0.5) {
    cw = srcW * 0.5;
    ch = cw / halfAr;
  }
  const x = Math.min(Math.max(cx * srcW - cw / 2, 0), srcW - cw);
  const y = Math.min(Math.max(cy * srcH - ch * 0.42, 0), srcH - ch);
  return { x: x / srcW, y: y / srcH, w: cw / srcW, h: ch / srcH };
}

/** Segment boundaries used for selection: clip edges, cut edges and user split points. */
export function segmentsForSelection(tl: TimelineData): { s: number; e: number }[] {
  const marks = new Set<number>([tl.start, tl.end]);
  for (const c of tl.cuts) {
    if (c.s > tl.start && c.s < tl.end) marks.add(round3(c.s));
    if (c.e > tl.start && c.e < tl.end) marks.add(round3(c.e));
  }
  for (const s of tl.splits ?? []) if (s > tl.start && s < tl.end) marks.add(round3(s));
  const pts = [...marks].sort((a, b) => a - b);
  const out: { s: number; e: number }[] = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i];
    const b = pts[i + 1];
    if (b - a < 0.02) continue;
    const mid = (a + b) / 2;
    if (!cutAt(tl.cuts, mid)) out.push({ s: a, e: b });
  }
  return out;
}
