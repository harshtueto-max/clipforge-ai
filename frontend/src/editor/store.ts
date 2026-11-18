import { create } from 'zustand';
import { api, errMsg } from '../api';
import { deepClone } from '../lib/format';
import { toast } from '../stores/toast';
import type { Captions, Clip, EditorState, TimelineData } from '../types';

export interface Snapshot {
  timeline: TimelineData;
  captions: Captions;
}

type SaveState = 'saved' | 'dirty' | 'saving' | 'error';

interface EditorStore {
  clipId: string | null;
  data: EditorState | null;
  loading: boolean;
  error: string | null;
  timeline: TimelineData | null;
  captions: Captions | null;
  version: number;
  past: Snapshot[];
  future: Snapshot[];
  saveState: SaveState;
  saveError: string | null;
  tlDirty: boolean;
  capDirty: boolean;
  // playback / selection (not persisted)
  time: number;
  playing: boolean;
  loop: boolean;
  selCaption: string | null;
  selSegment: { s: number; e: number } | null;
  selCut: number | null;
  selSfx: string | null;

  load: (clipId: string) => Promise<void>;
  replaceState: (s: EditorState) => void;
  setClip: (c: Clip) => void;
  commit: (fn: (s: Snapshot) => Snapshot, mergeKey?: string) => void;
  /** Apply server-provided timeline without creating history noise (e.g. reframe results). */
  applyServerTimeline: (tl: TimelineData, version: number) => void;
  applyServerCaptions: (c: Captions) => void;
  undo: () => void;
  redo: () => void;
  flush: () => Promise<boolean>;
  set: (p: Partial<EditorStore>) => void;
}

let saveTimer: number | null = null;
let saving: Promise<boolean> | null = null;
let lastMerge: { key: string; at: number } | null = null;
const HISTORY = 200;

export function sanitizeCaptions(c: Captions): Captions {
  const minDur = 0.12;
  const items = c.items
    .filter((it) => it.text.trim().length > 0)
    .map((it) => {
      const s = Math.max(0, Math.round(Number(it.start) * 1000) / 1000);
      const e = Math.max(s + minDur, Math.round(Number(it.end) * 1000) / 1000);
      return { ...it, start: s, end: Math.round(e * 1000) / 1000 };
    })
    .sort((a, b) => a.start - b.start || a.end - b.end);
  for (let i = 0; i < items.length - 1; i++) {
    const a = items[i];
    const b = items[i + 1];
    if (b.start < a.end) {
      if (b.end >= a.start + 2 * minDur) {
        const mid = Math.round(Math.max(a.start + minDur, Math.min(b.end - minDur, b.start)) * 1000) / 1000;
        a.end = mid;
        b.start = mid;
      } else {
        b.start = a.end;
      }
      if (b.end < b.start + minDur) {
        b.end = Math.round((b.start + minDur) * 1000) / 1000;
      }
    }
  }
  return { ...c, items };
}

export const useEditor = create<EditorStore>((set, get) => {
  const scheduleSave = () => {
    if (saveTimer) window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => {
      saveTimer = null;
      void get().flush();
    }, 700);
  };

  const doSave = async (): Promise<boolean> => {
    const st = get();
    if (!st.clipId || !st.timeline || !st.captions) return true;
    const clipId = st.clipId;
    const wantTl = st.tlDirty;
    const wantCap = st.capDirty;
    if (!wantTl && !wantCap) return true;
    const tl = st.timeline;
    const cap = st.captions;
    set({ saveState: 'saving', tlDirty: false, capDirty: false });
    try {
      let version = st.version;
      if (wantTl) {
        const r = await api.saveTimeline(clipId, tl, version);
        version = r.version;
      }
      if (wantCap) {
        const cleanCap = sanitizeCaptions(cap);
        await api.saveCaptions(clipId, cleanCap);
        version += 1;
      }
      if (get().clipId !== clipId) return true;
      set({ version, saveError: null, saveState: get().tlDirty || get().capDirty ? 'dirty' : 'saved' });
      return true;
    } catch (e) {
      if (get().clipId === clipId) {
        set({ saveState: 'error', saveError: errMsg(e), tlDirty: get().tlDirty || wantTl, capDirty: get().capDirty || wantCap });
        toast.error('Could not save edit', errMsg(e));
      }
      return false;
    }
  };

  return {
    clipId: null,
    data: null,
    loading: false,
    error: null,
    timeline: null,
    captions: null,
    version: 0,
    past: [],
    future: [],
    saveState: 'saved',
    saveError: null,
    tlDirty: false,
    capDirty: false,
    time: 0,
    playing: false,
    loop: false,
    selCaption: null,
    selSegment: null,
    selCut: null,
    selSfx: null,

    set: (p) => set(p),

    load: async (clipId) => {
      if (get().clipId && get().clipId !== clipId) await get().flush();
      set({ clipId, loading: true, error: null, data: null, timeline: null, captions: null, past: [], future: [], selCaption: null, selSegment: null, selCut: null, selSfx: null, playing: false });
      try {
        const d = await api.editor(clipId);
        if (get().clipId !== clipId) return;
        get().replaceState(d);
        set({ loading: false, time: d.timeline.start });
      } catch (e) {
        if (get().clipId === clipId) set({ loading: false, error: errMsg(e) });
      }
    },

    replaceState: (d) => {
      const tl = d.timeline;
      tl.cuts ??= [];
      tl.zooms ??= [];
      tl.sfx ??= [];
      tl.splits ??= [];
      set({
        data: d,
        timeline: tl,
        captions: sanitizeCaptions(d.captions),
        version: d.timeline_version,
        past: [],
        future: [],
        tlDirty: false,
        capDirty: false,
        saveState: 'saved',
        saveError: null,
      });
    },

    setClip: (c) => {
      const d = get().data;
      if (d) set({ data: { ...d, clip: { ...d.clip, ...c } } });
    },

    commit: (fn, mergeKey) => {
      const { timeline, captions, past } = get();
      if (!timeline || !captions) return;
      const before: Snapshot = { timeline, captions };
      const after = fn({ timeline: deepClone(timeline), captions: deepClone(captions) });
      const tlChanged = JSON.stringify(after.timeline) !== JSON.stringify(timeline);
      const capChanged = JSON.stringify(after.captions) !== JSON.stringify(captions);
      if (!tlChanged && !capChanged) return;
      const now = Date.now();
      const merge = mergeKey && lastMerge && lastMerge.key === mergeKey && now - lastMerge.at < 1200;
      lastMerge = mergeKey ? { key: mergeKey, at: now } : null;
      set({
        timeline: after.timeline,
        captions: after.captions,
        past: merge ? past : [...past.slice(-HISTORY), before],
        future: [],
        tlDirty: get().tlDirty || tlChanged,
        capDirty: get().capDirty || capChanged,
        saveState: 'dirty',
      });
      scheduleSave();
    },

    applyServerTimeline: (tl, version) => {
      const { timeline, captions, past } = get();
      tl.cuts ??= [];
      tl.zooms ??= [];
      tl.sfx ??= [];
      tl.splits ??= timeline?.splits ?? [];
      set({ timeline: tl, version, past: timeline && captions ? [...past.slice(-HISTORY), { timeline, captions }] : past, future: [] });
    },

    applyServerCaptions: (c) => {
      const { timeline, captions, past } = get();
      set({ captions: sanitizeCaptions(c), past: timeline && captions ? [...past.slice(-HISTORY), { timeline, captions }] : past, future: [], version: get().version + 1 });
    },

    undo: () => {
      const { past, future, timeline, captions } = get();
      if (!past.length || !timeline || !captions) return;
      const prev = past[past.length - 1];
      lastMerge = null;
      set({ past: past.slice(0, -1), future: [{ timeline, captions }, ...future].slice(0, HISTORY), timeline: prev.timeline, captions: prev.captions, tlDirty: true, capDirty: true, saveState: 'dirty' });
      scheduleSave();
    },

    redo: () => {
      const { past, future, timeline, captions } = get();
      if (!future.length || !timeline || !captions) return;
      const next = future[0];
      lastMerge = null;
      set({ future: future.slice(1), past: [...past, { timeline, captions }], timeline: next.timeline, captions: next.captions, tlDirty: true, capDirty: true, saveState: 'dirty' });
      scheduleSave();
    },

    flush: async () => {
      if (saveTimer) {
        window.clearTimeout(saveTimer);
        saveTimer = null;
      }
      if (saving) await saving;
      if (!get().tlDirty && !get().capDirty) return get().saveState !== 'error';
      saving = doSave();
      const ok = await saving;
      saving = null;
      return ok;
    },
  };
});
