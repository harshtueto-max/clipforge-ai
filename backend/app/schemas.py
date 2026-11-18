"""Pydantic request/response models for the REST API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

Aspect = Literal["9:16", "16:9", "1:1", "4:5"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- projects
class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    options: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    options: Optional[dict[str, Any]] = None


class MediaOut(ORM):
    id: str
    original_name: str
    is_reference: bool
    source_url: Optional[str] = None
    size_bytes: int
    duration: float
    width: int
    height: int
    fps: float
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    has_audio: bool
    has_video: bool
    proxy_ready: bool = False
    created_at: datetime


class ProjectOut(ORM):
    id: str
    name: str
    status: str
    options: dict[str, Any]
    analysis_summary: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    has_thumbnail: bool = False
    media: Optional[MediaOut] = None
    clip_count: int = 0
    accepted_count: int = 0
    export_count: int = 0


class ImportPath(BaseModel):
    path: str = Field(min_length=3, max_length=1000)
    copy_file: bool = True
    auto_analyze: bool = False
    analysis_params: dict[str, Any] = Field(default_factory=dict)


class ImportYouTube(BaseModel):
    url: str = Field(min_length=10, max_length=500)
    confirm_rights: bool = False
    auto_analyze: bool = False
    analysis_params: dict[str, Any] = Field(default_factory=dict)


class AnalyzeRequest(BaseModel):
    force: bool = False
    whisper_model: Optional[str] = None
    language: Optional[str] = None
    analysis_quality: Optional[Literal["fast", "balanced", "high"]] = None
    duration_targets: Optional[list[float]] = None
    duration_tolerance: Optional[float] = Field(default=None, ge=0.05, le=0.6)
    score_weights: Optional[dict[str, float]] = None
    max_clips_per_target: Optional[int] = Field(default=None, ge=1, le=30)
    preferences: Optional[dict[str, Any]] = None
    preset_id: Optional[str] = None
    aspect: Optional[Aspect] = None
    use_ai_provider: bool = True

    @field_validator("duration_targets")
    @classmethod
    def _targets(cls, v):
        if v is None:
            return v
        v = [float(x) for x in v if x]
        if not v or any(x < 5 or x > 900 for x in v):
            raise ValueError("Duration targets must be between 5 and 900 seconds")
        return sorted(set(v))


# ---------------------------------------------------------------- jobs
class JobOut(BaseModel):
    id: str
    project_id: Optional[str]
    kind: str
    status: str
    progress: float
    stage: Optional[str]
    message: Optional[str]
    error: Optional[str]
    params: dict[str, Any]
    result: dict[str, Any]
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]


class JobRef(BaseModel):
    job_id: str


# ---------------------------------------------------------------- clips
class ClipOut(ORM):
    id: str
    project_id: str
    parent_id: Optional[str] = None
    target_duration: float
    start: float
    end: float
    duration: float = 0
    score: float
    scores: dict[str, Any]
    explanations: dict[str, Any]
    title: str
    category: str
    hook: str
    description: str
    reason: str
    transcript: str
    speakers: list[Any]
    tags: list[Any]
    status: str
    fits_duration: bool
    analysis_source: str
    has_thumbnail: bool = False
    rank: int
    edited: bool = False
    export_status: Optional[str] = None
    project_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ClipUpdate(BaseModel):
    status: Optional[Literal["suggested", "accepted", "rejected"]] = None
    title: Optional[str] = Field(default=None, max_length=200)
    category: Optional[str] = None
    fits_duration: Optional[bool] = None
    description: Optional[str] = Field(default=None, max_length=2000)


class BatchAction(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    action: Literal["accept", "reject", "reset", "delete", "export"]
    export_settings: dict[str, Any] = Field(default_factory=dict)


class TimelineUpdate(BaseModel):
    data: dict[str, Any]
    base_version: Optional[int] = None

    @field_validator("data")
    @classmethod
    def _validate(cls, d):
        if "start" not in d or "end" not in d:
            raise ValueError("Timeline requires start and end")
        if float(d["end"]) - float(d["start"]) < 1.0:
            raise ValueError("Clip must be at least 1 second long")
        for c in d.get("cuts", []):
            if float(c["e"]) <= float(c["s"]):
                raise ValueError("Invalid cut range")
        if d.get("aspect") not in (None, "9:16", "16:9", "1:1", "4:5"):
            raise ValueError("Unsupported aspect ratio")
        mv = (d.get("music") or {}).get("volume", 0.1)
        if not 0 <= float(mv) <= 1:
            raise ValueError("Music volume must be 0..1")
        return d


class CaptionsUpdate(BaseModel):
    style: dict[str, Any]
    items: list[dict[str, Any]]

    @field_validator("items")
    @classmethod
    def _items(cls, items):
        for it in items:
            s = float(it["start"])
            e = float(it["end"])
            if s < 0:
                raise ValueError("Caption start cannot be negative")
            if e <= s:
                if s - e <= 1.0:
                    it["end"] = round(s + 0.12, 3)
                else:
                    raise ValueError("Caption end must be after start")
            if len(str(it.get("text", ""))) > 500:
                raise ValueError("Caption text too long")
        return items


class CaptionsRebuild(BaseModel):
    style_id: Optional[str] = None
    words_per_caption: Optional[int] = Field(default=None, ge=1, le=15)


class CaptionsLanguageRequest(BaseModel):
    mode: Literal["hinglish", "hi", "en"]
    words_per_caption: Optional[int] = Field(default=None, ge=1, le=15)


class ApplyPreset(BaseModel):
    preset_id: str
    aspect: Optional[Aspect] = None


class ReframeRequest(BaseModel):
    mode: Literal["auto", "center", "split", "single", "manual"] = "auto"
    aspect: Optional[Aspect] = None
    smoothness: float = Field(default=0.75, ge=0, le=1)


class ExportSettings(BaseModel):
    resolution: Literal["720p", "1080p", "4k"] = "1080p"
    fps: Literal[24, 25, 30, 50, 60] = 30
    codec: Literal["h264", "h265"] = "h264"
    quality: Literal["high", "balanced", "small"] = "high"
    bitrate_kbps: Optional[int] = Field(default=None, ge=500, le=200000)
    audio_bitrate_kbps: int = Field(default=192, ge=64, le=512)
    output_dir: Optional[str] = None
    captions: bool = True


class ExportOut(ORM):
    id: str
    project_id: str
    clip_id: str
    job_id: Optional[str]
    status: str
    settings: dict[str, Any]
    output_path: Optional[str]
    probe: dict[str, Any]
    error: Optional[str]
    clip_title: str
    progress: float = 0
    created_at: datetime
    finished_at: Optional[datetime]


# ---------------------------------------------------------------- audio / presets
class AudioOut(BaseModel):
    id: str
    kind: str
    category: str
    name: str
    duration: float
    moods: list[Any]
    bpm: Optional[float]
    license: str
    origin: str
    url: str


class PresetIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    config: dict[str, Any]


# ---------------------------------------------------------------- AI providers
class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["ollama", "openai", "openai_compatible", "anthropic", "gemini"]
    base_url: Optional[str] = Field(default=None, max_length=300)
    model: str = Field(default="", max_length=200)
    enabled: bool = False
    send_frames: bool = False
    api_key: Optional[str] = Field(default=None, max_length=500)

    @field_validator("base_url")
    @classmethod
    def _url(cls, v):
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("Base URL must start with http:// or https://")
        return v


class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    enabled: Optional[bool] = None
    send_frames: Optional[bool] = None
    api_key: Optional[str] = Field(default=None, max_length=500)
    clear_key: bool = False


class ProviderOut(BaseModel):
    id: str
    name: str
    kind: str
    base_url: Optional[str]
    model: str
    enabled: bool
    is_local: bool
    has_key: bool
    send_frames: bool
    privacy_acknowledged: bool
    usage: dict[str, Any]
    last_test: dict[str, Any]


class ModelDownload(BaseModel):
    kind: Literal["whisper", "vision", "ollama"]
    name: str = Field(min_length=1, max_length=100)


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projects_dir: Optional[str] = None
    exports_dir: Optional[str] = None
    offline_mode: Optional[bool] = None
    whisper_model: Optional[str] = None
    whisper_device: Optional[Literal["auto", "cuda", "cpu"]] = None
    whisper_compute_type: Optional[str] = None
    transcription_language: Optional[str] = None
    analysis_quality: Optional[Literal["fast", "balanced", "high"]] = None
    enable_diarization: Optional[bool] = None
    max_speakers: Optional[int] = Field(default=None, ge=1, le=8)
    analysis_concurrency: Optional[int] = Field(default=None, ge=1, le=4)
    render_concurrency: Optional[int] = Field(default=None, ge=1, le=4)
    hardware_encoding: Optional[Literal["auto", "off"]] = None
    proxy_mode: Optional[Literal["auto", "always", "never"]] = None
    copy_imports: Optional[bool] = None
    duration_targets: Optional[list[float]] = None
    duration_tolerance: Optional[float] = Field(default=None, ge=0.05, le=0.6)
    max_clips_per_target: Optional[int] = Field(default=None, ge=1, le=30)
    score_weights: Optional[dict[str, float]] = None
    discovery_preferences: Optional[dict[str, Any]] = None
    default_preset: Optional[str] = None
    default_aspect: Optional[Aspect] = None


# ---------------------------------------------------------------- live clipping
class LiveSessionCreate(BaseModel):
    url: str = Field(min_length=10, max_length=500)
    confirm_rights: bool = False
    language: str = Field(default="hinglish", max_length=32)
    preset_id: Optional[str] = None
    aspect: Aspect = "9:16"
    auto_highlight: bool = True
    dvr_minutes: int = Field(default=30, ge=5, le=120)
    target_duration: float = Field(default=45.0, ge=15.0, le=120.0)


class LiveSessionUpdate(BaseModel):
    language: Optional[str] = Field(default=None, max_length=32)
    preset_id: Optional[str] = None
    aspect: Optional[Aspect] = None
    auto_highlight: Optional[bool] = None
    target_duration: Optional[float] = Field(default=None, ge=15.0, le=120.0)


class LiveClipRequest(BaseModel):
    mode: Literal["last", "range"] = "last"
    duration: float = Field(default=45.0, ge=5.0, le=180.0)
    anchor_stream_time: Optional[float] = Field(default=None, ge=0.0)
    start_time: Optional[float] = Field(default=None, ge=0.0)
    end_time: Optional[float] = Field(default=None, ge=0.0)
    title: Optional[str] = Field(default=None, max_length=160)

