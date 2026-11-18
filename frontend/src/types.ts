// Types mirroring backend/app/schemas.py and service JSON structures.

export type Aspect = '9:16' | '16:9' | '1:1' | '4:5';
export const ASPECTS: Aspect[] = ['9:16', '16:9', '1:1', '4:5'];

export interface Media {
  id: string;
  original_name: string;
  is_reference: boolean;
  source_url: string | null;
  size_bytes: number;
  duration: number;
  width: number;
  height: number;
  fps: number;
  video_codec: string | null;
  audio_codec: string | null;
  has_audio: boolean;
  has_video: boolean;
  proxy_ready: boolean;
  created_at: string;
}

export interface StageTranscribe {
  model: string;
  device?: string;
  language: string;
  words: number;
  sentences: number;
  elapsed_s?: number;
}

export interface DiscoveryResult {
  candidates: number;
  targets: number[];
  tolerance: number;
  source: string;
  llm: string | null;
  unfit_targets: number[];
}

export interface AnalysisSummary {
  stages?: {
    audio?: string;
    transcribe?: StageTranscribe;
    audio_analysis?: { speech_ratio: number; laughter_events: number; excitement_peaks: number; long_pauses: number };
    diarization?: { speakers: number; method: string; note?: string | null };
    vision?: { scenes: number; samples: number; face_tracks: number; face_visible_ratio: number; detector?: string | null };
    semantic?: { topics: number; keywords: string[] };
    discovery?: DiscoveryResult;
  };
  elapsed_s?: number;
}

export interface Project {
  id: string;
  name: string;
  status: string;
  options: Record<string, unknown>;
  analysis_summary: AnalysisSummary;
  created_at: string;
  updated_at: string;
  has_thumbnail: boolean;
  media: Media | null;
  clip_count: number;
  accepted_count: number;
  export_count: number;
}

export interface Job {
  id: string;
  project_id: string | null;
  kind: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted' | string;
  progress: number;
  stage: string | null;
  message: string | null;
  error: string | null;
  params: Record<string, unknown>;
  result: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface JobRef {
  job_id: string;
}

export type ClipStatus = 'suggested' | 'accepted' | 'rejected';

export const SCORE_DIMENSIONS = ['hook', 'story', 'engagement', 'emotion', 'information', 'standalone', 'av_quality'] as const;
export type ScoreDim = (typeof SCORE_DIMENSIONS)[number];
export const DIM_LABELS: Record<string, string> = {
  hook: 'Hook strength',
  story: 'Story completeness',
  engagement: 'Engagement',
  emotion: 'Emotional impact',
  information: 'Information value',
  standalone: 'Standalone clarity',
  av_quality: 'A/V quality',
};

export const CATEGORIES = ['insight', 'story', 'educational', 'advice', 'funny', 'emotional', 'opinion', 'qa'] as const;

export const TAG_LABELS: Record<string, string> = {
  best_overall: 'Best overall',
  highest_hook: 'Highest hook',
  best_story: 'Best story',
  most_informative: 'Most informative',
  funniest: 'Funniest',
  most_emotional: 'Most emotional',
  best_standalone: 'Best standalone',
};

export interface Clip {
  id: string;
  project_id: string;
  parent_id: string | null;
  target_duration: number;
  start: number;
  end: number;
  duration: number;
  score: number;
  scores: Record<string, number>;
  explanations: Record<string, unknown>;
  title: string;
  category: string;
  hook: string;
  description: string;
  reason: string;
  transcript: string;
  speakers: number[];
  tags: string[];
  status: ClipStatus | string;
  fits_duration: boolean;
  analysis_source: string;
  has_thumbnail: boolean;
  rank: number;
  edited: boolean;
  export_status: string | null;
  project_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface ExportSettings {
  resolution: '720p' | '1080p' | '4k';
  fps: 24 | 25 | 30 | 50 | 60;
  codec: 'h264' | 'h265';
  quality: 'high' | 'balanced' | 'small';
  bitrate_kbps: number | null;
  audio_bitrate_kbps: number;
  output_dir: string | null;
  captions: boolean;
}

export const DEFAULT_EXPORT: ExportSettings = {
  resolution: '1080p',
  fps: 30,
  codec: 'h264',
  quality: 'high',
  bitrate_kbps: null,
  audio_bitrate_kbps: 192,
  output_dir: null,
  captions: true,
};

export interface ExportProbe {
  width?: number;
  height?: number;
  duration?: number;
  video_codec?: string;
  audio_codec?: string;
  size_bytes?: number;
  fps?: number;
  validated?: boolean;
  encoder?: string;
  [k: string]: unknown;
}

export interface ExportItem {
  id: string;
  project_id: string;
  clip_id: string;
  job_id: string | null;
  status: string;
  settings: Partial<ExportSettings> & Record<string, unknown>;
  output_path: string | null;
  probe: ExportProbe;
  error: string | null;
  clip_title: string;
  progress: number;
  created_at: string;
  finished_at: string | null;
}

// ---------------------------------------------------------------- timeline
export interface Cut {
  s: number;
  e: number;
  auto?: boolean;
}
export interface Keyframe {
  t: number;
  x: number;
  y: number;
  cut?: boolean;
}
export interface Point {
  x: number;
  y: number;
}
export interface Layout {
  s: number;
  e: number;
  layout: 'split' | string;
  top: Point;
  bottom: Point;
}
export type ReframeMode = 'auto' | 'center' | 'split' | 'single' | 'manual';
export interface Reframe {
  mode: ReframeMode | string;
  aspect: Aspect;
  keyframes: Keyframe[];
  layouts: Layout[];
  offset: Point;
  smoothness?: number;
  prefer_split?: boolean;
}
export interface Zoom {
  s: number;
  e: number;
  scale: number;
}
export interface MusicBed {
  asset_id: string | null;
  recommended_id: string | null;
  volume: number;
  fade_in: number;
  fade_out: number;
  ducking: boolean;
  offset: number;
}
export interface SfxItem {
  id: string;
  asset_id: string;
  t: number;
  volume: number;
}
export interface AudioSettings {
  enhance_voice: boolean;
  denoise: boolean;
  loudness: number;
  voice_gain_db: number;
}
export interface TimelineData {
  version: number;
  preset_id: string;
  start: number;
  end: number;
  cuts: Cut[];
  cut_settings?: Record<string, unknown>;
  aspect: Aspect;
  reframe: Reframe;
  zooms: Zoom[];
  music: MusicBed;
  sfx: SfxItem[];
  sfx_recommended_id?: string | null;
  audio: AudioSettings;
  export: Partial<ExportSettings>;
  splits?: number[];
  [k: string]: unknown;
}

// ---------------------------------------------------------------- captions
export type CaptionPosition = 'top' | 'center' | 'center_low' | 'bottom';
export type CaptionAnimation = 'none' | 'fade' | 'pop' | 'highlight' | 'karaoke';
export interface CaptionStyle {
  id?: string;
  name?: string;
  font: string;
  size: number;
  bold: boolean;
  color: string;
  highlight_color: string;
  stroke_color: string;
  stroke: number;
  shadow: number;
  shadow_color: string;
  position: CaptionPosition;
  margin: number;
  animation: CaptionAnimation;
  uppercase: boolean;
  words_per_caption: number;
  line_spacing: number;
  box: boolean;
  box_color: string;
  box_opacity: number;
  highlight_keywords: boolean;
  [k: string]: unknown;
}
export interface CaptionWord {
  w: string;
  s: number;
  e: number;
}
export interface CaptionItemStyle {
  color?: string;
  size?: number;
  position?: CaptionPosition;
  pos_x?: number;
  pos_y?: number;
  font?: string;
  highlight_color?: string;
}
export interface CaptionItem {
  id: string;
  start: number;
  end: number;
  text: string;
  words: CaptionWord[];
  style: CaptionItemStyle;
}
export interface Captions {
  style: CaptionStyle;
  items: CaptionItem[];
}

// ---------------------------------------------------------------- transcript
export interface Word {
  w: string;
  s: number;
  e: number;
  p?: number;
  spk?: number;
  i: number;
}
export interface Sentence {
  i: number;
  s: number;
  e: number;
  text: string;
  w0: number;
  w1: number;
  speaker?: number;
}
export interface Scene {
  s: number;
  e: number;
}
export interface Transcript {
  language: string;
  model: string;
  device: string | null;
  words: Word[];
  sentences: Sentence[];
}

export interface AudioAsset {
  id: string;
  kind: 'music' | 'sfx' | string;
  category: string;
  name: string;
  duration: number;
  moods: string[];
  bpm: number | null;
  license: string;
  origin: string;
  url: string;
}

export interface EditorState {
  clip: Clip;
  timeline: TimelineData;
  timeline_version: number;
  captions: Captions;
  media: Media | null;
  words: Word[];
  sentences: Sentence[];
  scenes: Scene[];
  assets: AudioAsset[];
  caption_styles: Record<string, CaptionStyle>;
  output_sizes: Record<string, Record<string, [number, number]>>;
}

export interface Analysis {
  summary: AnalysisSummary;
  transcript: {
    language: string;
    language_probability: number;
    model: string;
    device: string | null;
    words: number;
    sentences: number;
    elapsed_s?: number;
  } | null;
  speakers: { label: string; speaking_time: number; turns: number; [k: string]: unknown }[];
  diarization_method: string | null;
  diarization_note: string | null;
  turns: unknown[];
  scenes: Scene[];
  laughter: { s?: number; e?: number; t?: number; [k: string]: unknown }[];
  excitement: { s?: number; e?: number; t?: number; [k: string]: unknown }[];
  long_pauses: unknown[];
  speech_ratio: number | null;
  topics: unknown[];
  keywords: (string | [string, number] | { [k: string]: unknown })[];
}

// ---------------------------------------------------------------- presets
export interface PresetConfig {
  caption_style: string;
  reframe: { mode: string; smoothness: number; prefer_split: boolean };
  zoom: { frequency: 'none' | 'low' | 'medium' | 'high' | string; scale: number };
  cuts: { remove_silence: boolean; min_silence: number; keep_pad: number };
  music: { enabled: boolean; moods: string[]; volume: number; ducking: boolean; fade_in: number; fade_out: number };
  sfx: { intensity: 'none' | 'low' | 'medium' | 'high' | string };
  audio: { enhance_voice: boolean; denoise: boolean; loudness: number };
  [k: string]: unknown;
}
export interface Preset {
  id: string;
  name: string;
  description: string;
  builtin: boolean;
  config: PresetConfig;
}

// ---------------------------------------------------------------- system
export interface GPU {
  name: string;
  vram_total_mb: number;
  vram_used_mb: number;
  utilization: number;
  driver?: string;
  vendor?: string;
}
export interface Hardware {
  os: string;
  python: string;
  cpu: string;
  cpu_cores: number;
  ram_gb: number;
  gpus: GPU[];
  all_gpus: string[];
  gpu_vram_gb: number;
}
export interface SystemStatus {
  live: {
    cpu_percent: number;
    ram_used_gb: number;
    ram_total_gb: number;
    ram_percent: number;
    disk_free_gb: number;
    disk_total_gb: number;
    gpus: GPU[];
  };
  hardware: Hardware;
  offline_mode: boolean;
  active_jobs: number;
  whisper_model: string;
  whisper_installed: boolean;
}
export interface DependencyCheck {
  name: string;
  ok: boolean;
  detail: string;
  required: boolean;
  fix: string | null;
}
export interface Dependencies {
  checks: DependencyCheck[];
  ready: boolean;
}

export interface Settings {
  projects_dir: string;
  exports_dir: string;
  offline_mode: boolean;
  whisper_model: string;
  whisper_device: 'auto' | 'cuda' | 'cpu';
  whisper_compute_type: string;
  transcription_language: string;
  analysis_quality: 'fast' | 'balanced' | 'high';
  enable_diarization: boolean;
  max_speakers: number;
  analysis_concurrency: number;
  render_concurrency: number;
  hardware_encoding: 'auto' | 'off';
  proxy_mode: 'auto' | 'always' | 'never';
  copy_imports: boolean;
  duration_targets: number[];
  duration_tolerance: number;
  max_clips_per_target: number;
  score_weights: Record<string, number>;
  discovery_preferences: { categories: string[]; min_score: number; allow_alternates: boolean; [k: string]: unknown };
  default_preset: string;
  default_aspect: Aspect;
  telemetry?: boolean;
}

export interface WhisperModel {
  name: string;
  repo: string;
  size_mb: number;
  ram_gb: number;
  vram_gb: number;
  speed: string;
  quality: string;
  installed: boolean;
  fits_ram: boolean;
  fits_gpu: boolean;
  disk_ok: boolean;
  active: boolean;
}
export interface ModelsStatus {
  engine: { available: boolean; engine: string; cuda_devices?: number; error: string | null };
  cuda: { usable: boolean; message: string };
  hardware: Hardware;
  disk_free_gb: number;
  whisper: WhisperModel[];
  vision: { name: string; label: string; size_mb: number; installed: boolean; fallback: string }[];
  ollama: { models: string[]; error: string | null; suggested: { name: string; size_gb: number; ram_gb: number }[] };
  recommended_whisper: string;
}

export interface ProviderKind {
  label: string;
  local: boolean;
  default_url: string;
  needs_key: boolean;
  default_model: string;
}
export interface Provider {
  id: string;
  name: string;
  kind: 'ollama' | 'openai' | 'openai_compatible' | 'anthropic' | 'gemini';
  base_url: string | null;
  model: string;
  enabled: boolean;
  is_local: boolean;
  has_key: boolean;
  send_frames: boolean;
  privacy_acknowledged: boolean;
  usage: { input_tokens?: number; output_tokens?: number; requests?: number; [k: string]: unknown };
  last_test: { ok?: boolean; error?: string; latency_ms?: number; at?: string; [k: string]: unknown };
  models?: string[];
}
export interface PrivacySummary {
  sent: string[];
  never_sent: string[];
  notes: string[];
}

export interface LivePendingClip {
  task_id: string;
  start_time: number;
  end_time: number;
  source: 'manual' | 'auto_ai' | string;
  title?: string | null;
  status: 'processing' | 'failed' | string;
  message?: string;
  error?: string;
  created_at: number;
}

export interface LiveTranscriptLine {
  s: number;
  e: number;
  text: string;
}

export interface LiveSessionSummary {
  id: string;
  video_id: string;
  source_url: string;
  title: string;
  channel: string;
  is_live_broadcast: boolean;
  thumbnail_url: string | null;
  status: 'connecting' | 'live' | 'ended' | 'stopped' | 'error' | string;
  error: string | null;
  created_at: number;
  dvr_start: number;
  dvr_end: number;
  buffered_seconds: number;
  dvr_minutes: number;
  segment_count: number;
  playlist_ready: boolean;
  hls_url: string;
  language: string;
  preset_id: string;
  aspect: Aspect;
  auto_highlight: boolean;
  target_duration: number;
  ai_scanning: boolean;
  last_ai_scan_at: number | null;
  clip_count: number;
  pending_clips: LivePendingClip[];
}

export interface LiveSessionDetail extends LiveSessionSummary {
  transcript_tail: LiveTranscriptLine[];
  clip_ids: string[];
  clips: Clip[];
}

export type WsMessage =
  | { type: 'job'; data: Job }
  | { type: 'project'; data: { id: string; status: string } }
  | { type: 'clips'; data: { project_id: string } }
  | { type: 'export'; data: { id: string; status: string } }
  | { type: 'live_session'; data: LiveSessionSummary }
  | { type: 'live_clip_status'; data: LivePendingClip & { session_id: string } }
  | { type: 'live_clip_ready'; data: { session_id: string; clip_id: string; source: string; title: string } };
