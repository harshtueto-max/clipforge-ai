"""Export history, render queue and job endpoints."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..jobs import manager
from ..models import ExportJob, Job
from ..schemas import JobOut
from .common import export_out, get_or_404, job_out

router = APIRouter(tags=["exports & jobs"])


@router.get("/api/exports")
def list_exports(project_id: Optional[str] = None, status: Optional[str] = None, limit: int = 200, db: Session = Depends(get_db)):
    q = db.query(ExportJob)
    if project_id:
        q = q.filter(ExportJob.project_id == project_id)
    if status:
        q = q.filter(ExportJob.status.in_(status.split(",")))
    return [export_out(db, e) for e in q.order_by(ExportJob.created_at.desc()).limit(min(1000, limit)).all()]


@router.get("/api/exports/{export_id}")
def get_export(export_id: str, db: Session = Depends(get_db)):
    return export_out(db, get_or_404(db, ExportJob, export_id, "Export"))


@router.post("/api/exports/{export_id}/retry")
def retry_export(export_id: str, db: Session = Depends(get_db)):
    e = get_or_404(db, ExportJob, export_id, "Export")
    if e.status in ("queued", "running"):
        raise HTTPException(409, "Export is still active")
    e.status = "queued"
    e.error = None
    db.commit()
    if e.job_id and db.get(Job, e.job_id):
        manager.retry(e.job_id)
    else:
        e.job_id = manager.submit("render", e.project_id, {"export_id": e.id, "clip_id": e.clip_id})
        db.commit()
    return export_out(db, e)


@router.post("/api/exports/{export_id}/cancel")
def cancel_export(export_id: str, db: Session = Depends(get_db)):
    e = get_or_404(db, ExportJob, export_id, "Export")
    ok = manager.cancel(e.job_id) if e.job_id else False
    return {"cancelled": ok}


@router.delete("/api/exports/{export_id}")
def delete_export(export_id: str, delete_file: bool = False, db: Session = Depends(get_db)):
    e = get_or_404(db, ExportJob, export_id, "Export")
    if e.status in ("queued", "running") and e.job_id:
        manager.cancel(e.job_id)
    if delete_file and e.output_path:
        Path(e.output_path).unlink(missing_ok=True)
    db.delete(e)
    return {"deleted": True}


@router.get("/api/exports/{export_id}/file")
def export_file(export_id: str, download: bool = False, db: Session = Depends(get_db)):
    e = get_or_404(db, ExportJob, export_id, "Export")
    if e.status != "completed" or not e.output_path or not Path(e.output_path).exists():
        raise HTTPException(404, "Export file not available")
    return FileResponse(e.output_path, media_type="video/mp4", filename=Path(e.output_path).name if download else None)


@router.post("/api/exports/{export_id}/reveal")
def reveal_export(export_id: str, db: Session = Depends(get_db)):
    e = get_or_404(db, ExportJob, export_id, "Export")
    if not e.output_path or not Path(e.output_path).exists():
        raise HTTPException(404, "File not found")
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", str(Path(e.output_path))])
    return {"ok": True}


# ---------------------------------------------------------------- jobs
@router.get("/api/jobs", response_model=list[JobOut])
def list_jobs(active: bool = False, project_id: Optional[str] = None, kind: Optional[str] = None, limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(Job)
    if active:
        q = q.filter(Job.status.in_(["queued", "running"]))
    if project_id:
        q = q.filter(Job.project_id == project_id)
    if kind:
        q = q.filter(Job.kind.in_(kind.split(",")))
    return [job_out(j) for j in q.order_by(Job.created_at.desc()).limit(min(500, limit)).all()]


@router.get("/api/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    return job_out(get_or_404(db, Job, job_id, "Job"))


@router.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str, db: Session = Depends(get_db)):
    get_or_404(db, Job, job_id, "Job")
    return {"cancelled": manager.cancel(job_id)}


@router.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str, db: Session = Depends(get_db)):
    j = get_or_404(db, Job, job_id, "Job")
    if j.status in ("queued", "running"):
        raise HTTPException(409, "Job is still active")
    if j.kind == "render" and j.params.get("export_id"):
        e = db.get(ExportJob, j.params["export_id"])
        if e:
            e.status = "queued"
            e.error = None
    db.commit()
    return {"job_id": manager.retry(job_id)}


@router.delete("/api/jobs/{job_id}")
def delete_job(job_id: str, db: Session = Depends(get_db)):
    j = get_or_404(db, Job, job_id, "Job")
    if j.status in ("queued", "running"):
        raise HTTPException(409, "Cancel the job first")
    db.delete(j)
    return {"deleted": True}
