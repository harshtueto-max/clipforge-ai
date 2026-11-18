"""ORM models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class UTCDateTime(TypeDecorator):
    """Stores UTC datetimes; always returns timezone-aware values (SQLite drops tzinfo)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    folder: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="new")  # new|importing|ready|analyzing|analyzed|error
    thumbnail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    analysis_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    media: Mapped[list["SourceMedia"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    clips: Mapped[list["CandidateClip"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class SourceMedia(Base):
    __tablename__ = "source_media"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    original_name: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    is_reference: Mapped[bool] = mapped_column(Boolean, default=False)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    proxy_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    fps: Mapped[float] = mapped_column(Float, default=0.0)
    video_codec: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    audio_codec: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    has_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    has_video: Mapped[bool] = mapped_column(Boolean, default=True)
    probe: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    thumbnail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    waveform: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="media")


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32))  # import|download|analysis|render|model_download|proxy
    status: Mapped[str] = mapped_column(String(32), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    stage: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)


class Transcript(Base):
    __tablename__ = "transcripts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    language: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    language_probability: Mapped[float] = mapped_column(Float, default=0.0)
    model: Mapped[str] = mapped_column(String(64))
    device: Mapped[str] = mapped_column(String(32), default="cpu")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    sentence_count: Mapped[int] = mapped_column(Integer, default=0)
    path: Mapped[str] = mapped_column(Text)  # JSON file with words/sentences
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Speaker(Base):
    __tablename__ = "speakers"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(64))
    speaking_time: Mapped[float] = mapped_column(Float, default=0.0)
    turns: Mapped[int] = mapped_column(Integer, default=0)
    method: Mapped[str] = mapped_column(String(64), default="mfcc-clustering")


class Scene(Base):
    __tablename__ = "scenes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    start: Mapped[float] = mapped_column(Float)
    end: Mapped[float] = mapped_column(Float)
    face_count: Mapped[float] = mapped_column(Float, default=0.0)


class CandidateClip(Base):
    __tablename__ = "clips"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    target_duration: Mapped[float] = mapped_column(Float)
    start: Mapped[float] = mapped_column(Float)
    end: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    scores: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    explanations: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    title: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(64), default="general")
    hook: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    transcript: Mapped[str] = mapped_column(Text, default="")
    speakers: Mapped[list[Any]] = mapped_column(JSON, default=list)
    tags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="suggested")  # suggested|accepted|rejected
    fits_duration: Mapped[bool] = mapped_column(Boolean, default=True)
    analysis_source: Mapped[str] = mapped_column(String(32), default="local")
    thumbnail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    project: Mapped[Project] = relationship(back_populates="clips")


class Timeline(Base):
    __tablename__ = "timelines"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    clip_id: Mapped[str] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), unique=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class CaptionTrack(Base):
    __tablename__ = "captions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    clip_id: Mapped[str] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), unique=True)
    style: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    items: Mapped[list[Any]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class AudioAsset(Base):
    __tablename__ = "audio_assets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(16))  # music|sfx
    category: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    moods: Mapped[list[Any]] = mapped_column(JSON, default=list)
    bpm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    license: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String(16), default="builtin")  # builtin|user
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ExportJob(Base):
    __tablename__ = "exports"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    clip_id: Mapped[str] = mapped_column(String(32), index=True)
    job_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    probe: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    clip_title: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)


class AIProvider(Base):
    __tablename__ = "ai_providers"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(32))  # ollama|openai|openai_compatible|anthropic|gemini
    base_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(200), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_local: Mapped[bool] = mapped_column(Boolean, default=False)
    has_key: Mapped[bool] = mapped_column(Boolean, default=False)
    send_frames: Mapped[bool] = mapped_column(Boolean, default=False)
    privacy_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_test: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Preset(Base):
    __tablename__ = "presets"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
