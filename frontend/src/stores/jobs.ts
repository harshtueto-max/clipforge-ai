import { create } from 'zustand';
import { api, wsUrl } from '../api';
import type { Job, WsMessage } from '../types';

type Listener = (msg: WsMessage) => void;

interface JobsState {
  jobs: Record<string, Job>;
  connected: boolean;
  backendDown: boolean;
  upsert: (j: Job) => void;
  remove: (id: string) => void;
  refresh: () => Promise<void>;
  start: () => void;
  subscribe: (fn: Listener) => () => void;
}

const listeners = new Set<Listener>();
let ws: WebSocket | null = null;
let pollTimer: number | null = null;
let reconnectTimer: number | null = null;
let started = false;

export const ACTIVE = new Set(['queued', 'running']);

export const useJobs = create<JobsState>((set, get) => ({
  jobs: {},
  connected: false,
  backendDown: false,
  upsert: (j) => set({ jobs: { ...get().jobs, [j.id]: j } }),
  remove: (id) => {
    const next = { ...get().jobs };
    delete next[id];
    set({ jobs: next });
  },
  refresh: async () => {
    try {
      const [recent, active] = await Promise.all([api.jobs({ limit: 60 }), api.jobs({ active: true })]);
      const map: Record<string, Job> = {};
      for (const j of [...recent, ...active]) map[j.id] = j;
      const prev = get().jobs;
      // notify listeners for jobs whose state changed while polling (fallback mode)
      for (const j of Object.values(map)) {
        const p = prev[j.id];
        if (!p || p.status !== j.status || p.progress !== j.progress) listeners.forEach((fn) => fn({ type: 'job', data: j }));
      }
      set({ jobs: map, backendDown: false });
    } catch {
      set({ backendDown: true });
    }
  },
  start: () => {
    if (started) return;
    started = true;
    void get().refresh();
    connect();
    pollTimer = window.setInterval(() => {
      const hasActive = Object.values(get().jobs).some((j) => ACTIVE.has(j.status));
      if (!get().connected || hasActive) void get().refresh();
    }, 3000);
  },
  subscribe: (fn) => {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
}));

function connect() {
  try {
    ws = new WebSocket(wsUrl());
  } catch {
    scheduleReconnect();
    return;
  }
  ws.onopen = () => {
    useJobs.setState({ connected: true, backendDown: false });
    void useJobs.getState().refresh();
  };
  ws.onmessage = (ev) => {
    let msg: WsMessage;
    try {
      msg = JSON.parse(String(ev.data)) as WsMessage;
    } catch {
      return;
    }
    if (msg.type === 'job') useJobs.getState().upsert(msg.data);
    listeners.forEach((fn) => fn(msg));
  };
  ws.onclose = () => {
    useJobs.setState({ connected: false });
    ws = null;
    scheduleReconnect();
  };
  ws.onerror = () => {
    try {
      ws?.close();
    } catch {
      /* ignore */
    }
  };
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, 2500);
}

export function stopJobs() {
  if (pollTimer) window.clearInterval(pollTimer);
  ws?.close();
}

export const KIND_LABELS: Record<string, string> = {
  analysis: 'Analysis',
  rediscover: 'Re-discover',
  render: 'Render',
  import: 'Import',
  download: 'YouTube download',
  proxy: 'Preview proxy',
  model_download: 'Model download',
};

export const STAGE_LABELS: Record<string, string> = {
  probe: 'Probing media',
  copy: 'Copying',
  thumbnail: 'Thumbnail',
  audio: 'Audio extraction',
  waveform: 'Waveform',
  proxy: 'Preview proxy',
  download: 'Downloading',
  transcribe: 'Transcription',
  audio_analysis: 'Audio analysis',
  diarization: 'Speakers',
  vision: 'Vision & faces',
  semantic: 'Topics',
  discovery: 'Clip discovery',
  autoedit: 'Auto-edit',
  render: 'Rendering',
  validate: 'Validating',
};
