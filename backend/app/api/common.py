"""Shared API helpers / serializers."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..jobs import job_to_dict
from ..models import CandidateClip, ExportJob, Job, Project, SourceMedia, Timeline


def not_found(what: str = "Resource") -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found")


def get_or_404(db: Session, model, id_: str, what: str):
    obj = db.get(model, id_)
    if obj is None:
        raise not_found(what)
    return obj


def media_out(m: SourceMedia | None) -> dict[str, Any] | None:
    if m is None:
        return None
    return {
        "id": m.id, "original_name": m.original_name, "is_reference": m.is_reference, "source_url": m.source_url,
        "size_bytes": m.size_bytes, "duration": m.duration, "width": m.width, "height": m.height, "fps": m.fps,
        "video_codec": m.video_codec, "audio_codec": m.audio_codec, "has_audio": m.has_audio, "has_video": m.has_video,
        "proxy_ready": bool(m.proxy_path), "created_at": m.created_at,
    }


def latest_media(db: Session, project_id: str) -> SourceMedia | None:
    return db.query(SourceMedia).filter(SourceMedia.project_id == project_id).order_by(SourceMedia.created_at.desc()).first()


def project_out(db: Session, p: Project) -> dict[str, Any]:
    clips = db.query(CandidateClip.status).filter(CandidateClip.project_id == p.id).all()
    return {
        "id": p.id, "name": p.name, "status": p.status, "options": p.options or {}, "analysis_summary": p.analysis_summary or {},
        "created_at": p.created_at, "updated_at": p.updated_at, "has_thumbnail": bool(p.thumbnail),
        "media": media_out(latest_media(db, p.id)), "clip_count": len(clips),
        "accepted_count": sum(1 for (s,) in clips if s == "accepted"),
        "export_count": db.query(ExportJob).filter(ExportJob.project_id == p.id, ExportJob.status == "completed").count(),
    }


def clip_out(db: Session, c: CandidateClip, project_name: str | None = None) -> dict[str, Any]:
    tl = db.query(Timeline.version, Timeline.data).filter(Timeline.clip_id == c.id).first()
    ex = db.query(ExportJob.status).filter(ExportJob.clip_id == c.id).order_by(ExportJob.created_at.desc()).first()
    start, end = c.start, c.end
    if tl and tl[1]:
        start, end = tl[1].get("start", start), tl[1].get("end", end)
    return {
        "id": c.id, "project_id": c.project_id, "parent_id": c.parent_id, "target_duration": c.target_duration,
        "start": start, "end": end, "duration": round(end - start, 2), "score": c.score, "scores": c.scores or {},
        "explanations": c.explanations or {}, "title": c.title, "category": c.category, "hook": c.hook, "description": c.description,
        "reason": c.reason, "transcript": c.transcript, "speakers": c.speakers or [], "tags": c.tags or [], "status": c.status,
        "fits_duration": c.fits_duration, "analysis_source": c.analysis_source, "has_thumbnail": bool(c.thumbnail), "rank": c.rank,
        "edited": bool(tl and tl[0] > 1), "export_status": ex[0] if ex else None, "project_name": project_name,
        "created_at": c.created_at, "updated_at": c.updated_at,
    }


def export_out(db: Session, e: ExportJob) -> dict[str, Any]:
    prog = 0.0
    if e.job_id:
        j = db.get(Job, e.job_id)
        if j:
            prog = j.progress
    return {
        "id": e.id, "project_id": e.project_id, "clip_id": e.clip_id, "job_id": e.job_id, "status": e.status, "settings": e.settings or {},
        "output_path": e.output_path, "probe": e.probe or {}, "error": e.error, "clip_title": e.clip_title,
        "progress": 1.0 if e.status == "completed" else prog, "created_at": e.created_at, "finished_at": e.finished_at,
    }


def job_out(j: Job) -> dict[str, Any]:
    return job_to_dict(j)
