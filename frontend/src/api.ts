// Thin typed client around the ClipForge REST API. All URLs are relative so it works behind the Vite proxy and in production.
import type {
  Analysis, Aspect, AudioAsset, Captions, CaptionStyle, Clip, Dependencies, EditorState, ExportItem, ExportSettings, Job, JobRef,
  LivePendingClip, LiveSessionDetail, LiveSessionSummary, ModelsStatus, PrivacySummary, Project, Provider, ProviderKind, Preset,
  PresetConfig, Settings, SystemStatus, TimelineData, Transcript,
} from './types';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function detailToMessage(detail: unknown, fallback: string): string {
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors
    return detail
      .map((d) => {
        if (d && typeof d === 'object') {
          const o = d as { loc?: unknown[]; msg?: string };
          const loc = Array.isArray(o.loc) ? o.loc.filter((x) => x !== 'body').join('.') : '';
          return loc ? `${loc}: ${o.msg ?? ''}` : (o.msg ?? '');
        }
        return String(d);
      })
      .join('; ');
  }
  if (typeof detail === 'object') return JSON.stringify(detail);
  return String(detail);
}

const BACKEND_STORAGE_KEY = 'clipforge_backend_url';

export function isRemoteHost(): boolean {
  if (typeof window === 'undefined') return false;
  const h = window.location.hostname;
  return h !== '127.0.0.1' && h !== 'localhost' && h !== '[::1]';
}

export function getBackendOrigin(): string {
  if (typeof window === 'undefined') return '';
  const saved = window.localStorage.getItem(BACKEND_STORAGE_KEY);
  if (saved !== null && saved.trim() !== '') {
    return saved.trim().replace(/\/+$/, '');
  }
  const envBase = (import.meta as unknown as { env?: Record<string, string | undefined> }).env?.VITE_API_BASE?.trim();
  if (envBase) return envBase.replace(/\/+$/, '');
  return isRemoteHost() ? 'http://127.0.0.1:8765' : '';
}

export function setBackendOrigin(url: string): void {
  if (typeof window === 'undefined') return;
  const clean = url.trim().replace(/\/+$/, '');
  if (!clean) window.localStorage.removeItem(BACKEND_STORAGE_KEY);
  else window.localStorage.setItem(BACKEND_STORAGE_KEY, clean);
}

export function apiUrl(path: string | null | undefined): string {
  if (!path) return '';
  if (/^https?:\/\//i.test(path)) return path;
  const base = getBackendOrigin();
  return base ? `${base}${path.startsWith('/') ? path : `/${path}`}` : path;
}

export function wsUrl(): string {
  const base = getBackendOrigin();
  if (base) {
    const u = new URL(base);
    const proto = u.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${u.host}/ws`;
  }
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/ws`;
}

async function request<T>(method: string, url: string, body?: unknown, init?: RequestInit): Promise<T> {
  let res: Response;
  const targetUrl = apiUrl(url);
  try {
    res = await fetch(targetUrl, {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      ...init,
    });
  } catch {
    const originHint = getBackendOrigin() || '127.0.0.1:8765';
    throw new ApiError(0, `Cannot reach the ClipForge backend (${originHint}). Start ClipForge locally with start.bat or configure your Engine URL in the top bar.`);
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const detail = data && typeof data === 'object' && 'detail' in data ? (data as { detail: unknown }).detail : data;
    throw new ApiError(res.status, detailToMessage(detail, `${res.status} ${res.statusText}`));
  }
  return data as T;
}

const get = <T>(url: string) => request<T>('GET', url);
const post = <T>(url: string, body?: unknown) => request<T>('POST', url, body ?? {});
const put = <T>(url: string, body?: unknown) => request<T>('PUT', url, body ?? {});
const patch = <T>(url: string, body?: unknown) => request<T>('PATCH', url, body ?? {});
const del = <T>(url: string) => request<T>('DELETE', url);

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : '';
}

export interface AnalyzeParams {
  force?: boolean;
  whisper_model?: string;
  language?: string;
  analysis_quality?: 'fast' | 'balanced' | 'high';
  duration_targets?: number[];
  duration_tolerance?: number;
  score_weights?: Record<string, number>;
  max_clips_per_target?: number;
  preferences?: Record<string, unknown>;
  preset_id?: string;
  aspect?: string;
  use_ai_provider?: boolean;
}

export interface UploadHandle {
  promise: Promise<JobRef>;
  abort: () => void;
}

/** Stream a File to the backend as the raw request body (never read into JS memory). */
export function uploadRaw<T = JobRef>(url: string, file: File, onProgress: (loaded: number, total: number) => void): { promise: Promise<T>; abort: () => void } {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<T>((resolve, reject) => {
    xhr.open('POST', apiUrl(url));
    xhr.setRequestHeader('X-Filename', encodeURIComponent(file.name));
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded, e.total);
    };
    xhr.onload = () => {
      let data: unknown = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        data = xhr.responseText;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as T);
      else {
        const detail = data && typeof data === 'object' && 'detail' in data ? (data as { detail: unknown }).detail : data;
        reject(new ApiError(xhr.status, detailToMessage(detail, `Upload failed (${xhr.status})`)));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, 'Upload failed: network error'));
    xhr.onabort = () => reject(new ApiError(0, 'Upload cancelled'));
    xhr.send(file);
  });
  return { promise, abort: () => xhr.abort() };
}

export const api = {
  // system
  health: () => get<{ ok: boolean; version: string }>('/api/health'),
  systemStatus: () => get<SystemStatus>('/api/system/status'),
  dependencies: () => get<Dependencies>('/api/system/dependencies'),
  settings: () => get<Settings>('/api/settings'),
  saveSettings: (s: Partial<Settings>) => put<Settings>('/api/settings', s),
  dialog: (kind: 'file' | 'folder' | 'audio', title = 'Select') => post<{ path: string | null }>('/api/system/dialog', { kind, title }),
  openFolder: (which: 'data' | 'logs' | 'exports' | 'projects') => post<{ ok: boolean }>(`/api/system/open-folder${qs({ which })}`),
  deleteAllData: (includeExports: boolean, includeModels: boolean) =>
    del<{ deleted: boolean }>(`/api/system/data${qs({ confirm: 'DELETE', include_exports: includeExports, include_models: includeModels })}`),

  // projects
  projects: () => get<Project[]>('/api/projects'),
  project: (id: string) => get<Project>(`/api/projects/${id}`),
  createProject: (name: string, options: Record<string, unknown> = {}) => post<Project>('/api/projects', { name, options }),
  updateProject: (id: string, body: { name?: string; options?: Record<string, unknown> }) => patch<Project>(`/api/projects/${id}`, body),
  deleteProject: (id: string, deleteExports: boolean) => del<{ deleted: boolean }>(`/api/projects/${id}${qs({ delete_exports: deleteExports })}`),
  uploadMedia: (id: string, file: File, autoAnalyze: boolean, onProgress: (l: number, t: number) => void) =>
    uploadRaw<JobRef>(`/api/projects/${id}/upload${qs({ auto_analyze: autoAnalyze })}`, file, onProgress),
  importPath: (id: string, body: { path: string; copy_file: boolean; auto_analyze: boolean; analysis_params: AnalyzeParams }) =>
    post<JobRef>(`/api/projects/${id}/import-path`, body),
  importYoutube: (id: string, body: { url: string; confirm_rights: boolean; auto_analyze: boolean; analysis_params: AnalyzeParams }) =>
    post<JobRef>(`/api/projects/${id}/import-youtube`, body),
  analyze: (id: string, body: AnalyzeParams) => post<JobRef>(`/api/projects/${id}/analyze`, body),
  rediscover: (id: string, body: AnalyzeParams) => post<JobRef>(`/api/projects/${id}/rediscover`, body),
  analysis: (id: string) => get<Analysis>(`/api/projects/${id}/analysis`),
  transcript: (id: string, start?: number, end?: number) => get<Transcript>(`/api/projects/${id}/transcript${qs({ start, end })}`),
  correctWords: (id: string, corrections: { i: number; w: string }[]) => put<{ updated: number }>(`/api/projects/${id}/transcript/words`, corrections),
  waveform: (id: string, start: number, end: number, points: number) =>
    get<{ start: number; end: number; peaks: number[] }>(`/api/projects/${id}/waveform${qs({ start, end, points })}`),
  projectClips: (id: string, params: { status?: string; category?: string; min_score?: number; target?: number; speaker?: number; sort?: string } = {}) =>
    get<Clip[]>(`/api/projects/${id}/clips${qs(params)}`),

  // clips
  clips: (params: { status?: string; category?: string; min_score?: number; q?: string; sort?: string; limit?: number } = {}) =>
    get<Clip[]>(`/api/clips${qs(params)}`),
  clip: (id: string) => get<Clip>(`/api/clips/${id}`),
  updateClip: (id: string, body: Partial<Pick<Clip, 'status' | 'title' | 'category' | 'fits_duration' | 'description'>>) => patch<Clip>(`/api/clips/${id}`, body),
  deleteClip: (id: string) => del<{ deleted: boolean }>(`/api/clips/${id}`),
  batch: (ids: string[], action: 'accept' | 'reject' | 'reset' | 'delete' | 'export', export_settings?: Partial<ExportSettings>) =>
    post<{ updated: number; jobs: { export_id: string; job_id: string }[] }>('/api/clips/batch', { ids, action, export_settings: export_settings ?? {} }),
  regenerate: (id: string) => post<Clip>(`/api/clips/${id}/regenerate`),
  duplicate: (id: string) => post<Clip>(`/api/clips/${id}/duplicate`),
  rescore: (id: string) => post<Clip>(`/api/clips/${id}/rescore`),
  editor: (id: string) => get<EditorState>(`/api/clips/${id}/editor`),
  saveTimeline: (id: string, data: TimelineData, base_version: number | null) =>
    put<{ version: number; output_duration: number }>(`/api/clips/${id}/timeline`, { data, base_version }),
  saveCaptions: (id: string, c: Captions) => put<{ count: number }>(`/api/clips/${id}/captions`, c),
  rebuildCaptions: (id: string, body: { style_id?: string; words_per_caption?: number }) =>
    post<{ style: CaptionStyle; items: Captions['items'] }>(`/api/clips/${id}/captions/rebuild`, body),
  captionLanguage: (id: string, body: { mode: 'hinglish' | 'hi' | 'en'; words_per_caption?: number }) =>
    post<{ style: CaptionStyle; items: Captions['items']; mode: string; model: string }>(`/api/clips/${id}/captions/language`, body),
  applyPreset: (id: string, preset_id: string, aspect?: string) => post<EditorState>(`/api/clips/${id}/apply-preset`, { preset_id, aspect }),
  reframe: (id: string, body: { mode: string; aspect?: string; smoothness: number }) =>
    post<{ timeline: TimelineData; version: number }>(`/api/clips/${id}/reframe`, body),
  exportClip: (id: string, settings: ExportSettings) => post<{ export_id: string; job_id: string }>(`/api/clips/${id}/export`, settings),
  clipExports: (id: string) => get<ExportItem[]>(`/api/clips/${id}/exports`),

  // exports & jobs
  exports: (params: { project_id?: string; status?: string; limit?: number } = {}) => get<ExportItem[]>(`/api/exports${qs(params)}`),
  retryExport: (id: string) => post<ExportItem>(`/api/exports/${id}/retry`),
  cancelExport: (id: string) => post<{ cancelled: boolean }>(`/api/exports/${id}/cancel`),
  deleteExport: (id: string, deleteFile: boolean) => del<{ deleted: boolean }>(`/api/exports/${id}${qs({ delete_file: deleteFile })}`),
  revealExport: (id: string) => post<{ ok: boolean }>(`/api/exports/${id}/reveal`),
  jobs: (params: { active?: boolean; project_id?: string; kind?: string; limit?: number } = {}) => get<Job[]>(`/api/jobs${qs(params)}`),
  job: (id: string) => get<Job>(`/api/jobs/${id}`),
  cancelJob: (id: string) => post<{ cancelled: boolean }>(`/api/jobs/${id}/cancel`),
  retryJob: (id: string) => post<{ job_id: string }>(`/api/jobs/${id}/retry`),
  deleteJob: (id: string) => del<{ deleted: boolean }>(`/api/jobs/${id}`),

  // library
  audio: (kind?: string) => get<AudioAsset[]>(`/api/audio${qs({ kind })}`),
  audioCategories: () => get<{ music: string[]; sfx: string[] }>('/api/audio/categories'),
  importAudio: (file: File, p: { kind: string; category: string; name?: string; license_note?: string }, onProgress: (l: number, t: number) => void) =>
    uploadRaw<AudioAsset>(`/api/audio/import${qs({ ...p, confirm_rights: true })}`, file, onProgress),
  deleteAudio: (id: string) => del<{ deleted: boolean }>(`/api/audio/${id}`),
  presets: () => get<Preset[]>('/api/presets'),
  createPreset: (body: { name: string; description: string; config: PresetConfig }) => post<Preset>('/api/presets', body),
  updatePreset: (id: string, body: { name: string; description: string; config: PresetConfig }) => put<Preset>(`/api/presets/${id}`, body),
  duplicatePreset: (id: string) => post<Preset>(`/api/presets/${id}/duplicate`),
  deletePreset: (id: string) => del<{ deleted: boolean }>(`/api/presets/${id}`),
  captionStyles: () => get<Record<string, CaptionStyle>>('/api/caption-styles'),
  fonts: () => get<string[]>('/api/fonts'),

  // AI
  providerKinds: () => get<Record<string, ProviderKind>>('/api/ai/provider-kinds'),
  privacySummary: () => get<PrivacySummary>('/api/ai/privacy-summary'),
  providers: () => get<Provider[]>('/api/ai/providers'),
  createProvider: (body: { name: string; kind: string; base_url?: string | null; model?: string; enabled?: boolean; send_frames?: boolean; api_key?: string | null }) =>
    post<Provider>('/api/ai/providers', body),
  updateProvider: (id: string, body: { name?: string; base_url?: string; model?: string; enabled?: boolean; send_frames?: boolean; api_key?: string; clear_key?: boolean }) =>
    put<Provider>(`/api/ai/providers/${id}`, body),
  acknowledgeProvider: (id: string) => post<Provider>(`/api/ai/providers/${id}/acknowledge`),
  deleteProvider: (id: string) => del<{ deleted: boolean }>(`/api/ai/providers/${id}`),
  testProvider: (id: string) => post<Provider>(`/api/ai/providers/${id}/test`),
  providerModels: (id: string) => get<{ models: string[] }>(`/api/ai/providers/${id}/models`),
  models: () => get<ModelsStatus>('/api/models'),
  downloadModel: (kind: 'whisper' | 'vision' | 'ollama', name: string) => post<JobRef>('/api/models/download', { kind, name }),
  deleteModel: (kind: string, name: string) => del<{ deleted: boolean }>(`/api/models/${kind}/${encodeURIComponent(name)}`),

  // Live stream clipping
  liveSessions: () => get<LiveSessionSummary[]>('/api/live/sessions'),
  createLiveSession: (body: {
    url: string;
    confirm_rights: boolean;
    language: string;
    preset_id?: string;
    aspect: Aspect;
    auto_highlight: boolean;
    dvr_minutes: number;
    target_duration: number;
  }) => post<LiveSessionDetail>('/api/live/sessions', body),
  liveSession: (id: string) => get<LiveSessionDetail>(`/api/live/sessions/${id}`),
  updateLiveSession: (id: string, body: Partial<{ language: string; preset_id: string; aspect: Aspect; auto_highlight: boolean; target_duration: number }>) =>
    patch<LiveSessionDetail>(`/api/live/sessions/${id}`, body),
  clipLive: (
    id: string,
    body: { mode: 'last' | 'range'; duration?: number; anchor_stream_time?: number | null; start_time?: number; end_time?: number; title?: string },
  ) => post<LivePendingClip>(`/api/live/sessions/${id}/clip`, body),
  stopLiveSession: (id: string) => post<LiveSessionDetail>(`/api/live/sessions/${id}/stop`),
  deleteLiveSession: (id: string) => del<{ deleted: boolean }>(`/api/live/sessions/${id}`),
};

export function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}
