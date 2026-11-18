"""Projects, media import, streaming, transcript and analysis endpoints."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..jobs import manager
from ..models import CandidateClip, ExportJob, Job, Project, SourceMedia
from ..schemas import AnalyzeRequest, ImportPath, ImportYouTube, JobRef, ProjectCreate, ProjectOut, ProjectUpdate
from ..security import MEDIA_EXTENSIONS, AUDIO_EXTENSIONS, SecurityError, sanitize_filename, validate_media_file, validate_youtube_url
from ..services import media, storage
from .common import clip_out, get_or_404, latest_media, project_out

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _active_job(db: Session, project_id: str, kinds: tuple[str, ...]) -> Job | None:
    return db.query(Job).filter(Job.project_id == project_id, Job.kind.in_(kinds), Job.status.in_(["queued", "running"])).first()


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return [project_out(db, p) for p in db.query(Project).order_by(Project.updated_at.desc()).all()]


@router.post("", response_model=ProjectOut)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    p = Project(name=body.name.strip(), folder="", options=body.options)
    db.add(p)
    db.flush()
    folder = storage.project_folder(p.id)
    storage.ensure_layout(folder)
    p.folder = str(folder)
    db.flush()
    return project_out(db, p)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)):
    return project_out(db, get_or_404(db, Project, project_id, "Project"))


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, body: ProjectUpdate, db: Session = Depends(get_db)):
    p = get_or_404(db, Project, project_id, "Project")
    if body.name is not None:
        p.name = body.name.strip()
    if body.options is not None:
        p.options = {**(p.options or {}), **body.options}
    db.flush()
    return project_out(db, p)


@router.delete("/{project_id}")
def delete_project(project_id: str, delete_exports: bool = False, db: Session = Depends(get_db)):
    p = get_or_404(db, Project, project_id, "Project")
    for j in db.query(Job).filter(Job.project_id == project_id, Job.status.in_(["queued", "running"])).all():
        manager.cancel(j.id)
    exports = db.query(ExportJob).filter(ExportJob.project_id == project_id).all()
    if delete_exports:
        for e in exports:
            if e.output_path and Path(e.output_path).exists():
                Path(e.output_path).unlink(missing_ok=True)
    for e in exports:
        db.delete(e)
    folder = storage.project_folder(project_id)
    db.delete(p)
    db.flush()
    shutil.rmtree(folder, ignore_errors=True)
    return {"deleted": True}


@router.get("/{project_id}/thumbnail")
def project_thumbnail(project_id: str, db: Session = Depends(get_db)):
    p = get_or_404(db, Project, project_id, "Project")
    if not p.thumbnail or not Path(p.thumbnail).exists():
        raise HTTPException(404, "No thumbnail")
    return FileResponse(p.thumbnail, media_type="image/jpeg", headers={"Cache-Control": "max-age=60"})


# ---------------------------------------------------------------- import
def _check_import_allowed(db: Session, project_id: str):
    if _active_job(db, project_id, ("import", "download", "analysis")):
        raise HTTPException(409, "Another import or analysis is already running for this project")


@router.post("/{project_id}/upload", response_model=JobRef)
async def upload_media(project_id: str, request: Request, auto_analyze: bool = False, db: Session = Depends(get_db)):
    """Streaming upload: the browser sends the raw file body (never fully buffered in memory)."""
    get_or_404(db, Project, project_id, "Project")
    _check_import_allowed(db, project_id)
    raw_name = request.headers.get("x-filename", "upload.mp4")
    from urllib.parse import unquote

    name = sanitize_filename(unquote(raw_name), default="upload.mp4")
    if Path(name).suffix.lower() not in MEDIA_EXTENSIONS | AUDIO_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{Path(name).suffix}'")
    folder = storage.project_folder(project_id)
    storage.ensure_layout(folder)
    size = int(request.headers.get("content-length") or 0)
    free = shutil.disk_usage(folder).free
    if size and free < size * 1.1 + 300e6:
        raise HTTPException(507, f"Insufficient disk space: need {size / 1e9:.1f} GB plus working space, have {free / 1e9:.1f} GB")
    dst = folder / "media" / name
    tmp = dst.with_suffix(dst.suffix + ".part")
    written = 0
    try:
        with open(tmp, "wb") as f:
            async for chunk in request.stream():
                f.write(chunk)
                written += len(chunk)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "Upload interrupted")
    if written == 0:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "Empty upload")
    tmp.replace(dst)
    job_id = manager.submit("import", project_id, {"path": str(dst), "mode": "uploaded", "original_name": unquote(raw_name),
                                                   "auto_analyze": auto_analyze})
    return {"job_id": job_id}


@router.post("/{project_id}/upload-chunk")
async def upload_media_chunk(
    project_id: str,
    request: Request,
    upload_id: str,
    offset: int = 0,
    final: bool = False,
    auto_analyze: bool = False,
    db: Session = Depends(get_db),
):
    """Chunked upload (<4.5 MB per request) so large videos upload cleanly through serverless gateways."""
    get_or_404(db, Project, project_id, "Project")
    if offset == 0:
        _check_import_allowed(db, project_id)
    from urllib.parse import unquote

    raw_name = request.headers.get("x-filename", "upload.mp4")
    name = sanitize_filename(unquote(raw_name), default="upload.mp4")
    if Path(name).suffix.lower() not in MEDIA_EXTENSIONS | AUDIO_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{Path(name).suffix}'")
    safe_uid = "".join(c for c in upload_id if c.isalnum() or c in "-_")[:32] or "up"
    folder = storage.project_folder(project_id)
    storage.ensure_layout(folder)
    dst = folder / "media" / name
    tmp = folder / "media" / f".{safe_uid}_{name}.part"
    if offset < 0 or (offset > 0 and not tmp.exists()):
        raise HTTPException(400, "Upload session expired or invalid chunk offset; please retry upload.")
    written = 0
    try:
        mode = "wb" if offset == 0 else "r+b"
        with open(tmp, mode) as f:
            if offset > 0:
                f.seek(offset)
            async for chunk in request.stream():
                f.write(chunk)
                written += len(chunk)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "Chunk upload interrupted")
    new_offset = offset + written
    if not final:
        return {"received": written, "offset": new_offset, "job_id": ""}
    if new_offset == 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "Empty upload")
    tmp.replace(dst)
    job_id = manager.submit(
        "import",
        project_id,
        {"path": str(dst), "mode": "uploaded", "original_name": unquote(raw_name), "auto_analyze": auto_analyze},
    )
    return {"job_id": job_id}


@router.post("/{project_id}/import-path", response_model=JobRef)
def import_path(project_id: str, body: ImportPath, db: Session = Depends(get_db)):
    if config.PUBLIC_CLOUD:
        raise HTTPException(403, "Local server path import is disabled on the public cloud — upload your video file or paste a YouTube URL instead.")
    get_or_404(db, Project, project_id, "Project")
    _check_import_allowed(db, project_id)
    try:
        p = validate_media_file(body.path)
    except SecurityError as exc:
        raise HTTPException(400, str(exc))
    job_id = manager.submit("import", project_id, {"path": str(p), "mode": "copy" if body.copy_file else "reference",
                                                   "original_name": p.name, "auto_analyze": body.auto_analyze,
                                                   "analysis_params": body.analysis_params})
    return {"job_id": job_id}


@router.post("/{project_id}/import-youtube", response_model=JobRef)
def import_youtube(project_id: str, body: ImportYouTube, db: Session = Depends(get_db)):
    get_or_404(db, Project, project_id, "Project")
    _check_import_allowed(db, project_id)
    if config.get_settings().get("offline_mode"):
        raise HTTPException(400, "Offline mode is enabled - YouTube import is disabled. Import a local file instead.")
    if not body.confirm_rights:
        raise HTTPException(400, "Please confirm that you own this content or are authorized to download it")
    try:
        url = validate_youtube_url(body.url)
    except SecurityError as exc:
        raise HTTPException(400, str(exc))
    job_id = manager.submit("download", project_id, {"url": url, "auto_analyze": body.auto_analyze, "analysis_params": body.analysis_params})
    return {"job_id": job_id}


# ---------------------------------------------------------------- media
@router.get("/{project_id}/media/stream")
def stream_media(project_id: str, source: bool = False, db: Session = Depends(get_db)):
    m = latest_media(db, project_id)
    if m is None:
        raise HTTPException(404, "No media")
    path = m.proxy_path if (m.proxy_path and not source and Path(m.proxy_path).exists()) else m.path
    if not Path(path).exists():
        raise HTTPException(404, "Media file missing on disk")
    ext = Path(path).suffix.lower()
    mt = {".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska",
          ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4"}.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=mt)


@router.get("/{project_id}/waveform")
def waveform(project_id: str, start: float = 0.0, end: Optional[float] = None, points: int = Query(800, ge=10, le=4000),
             db: Session = Depends(get_db)):
    m = latest_media(db, project_id)
    if m is None or not m.waveform or not Path(m.waveform).exists():
        raise HTTPException(404, "Waveform not available")
    end = m.duration if end is None else min(end, m.duration)
    return {"start": start, "end": end, "peaks": media.read_peaks(m.waveform, start, end, points)}


@router.get("/{project_id}/transcript")
def transcript(project_id: str, start: Optional[float] = None, end: Optional[float] = None, db: Session = Depends(get_db)):
    get_or_404(db, Project, project_id, "Project")
    art = storage.Artifacts(storage.project_folder(project_id))
    tr = storage.read_json(art.transcript)
    if not tr:
        raise HTTPException(404, "Transcript not available - run analysis first")
    words, sents = tr["words"], tr["sentences"]
    if start is not None or end is not None:
        a, b = start or 0.0, end if end is not None else 1e12
        words = [dict(w, i=k) for k, w in enumerate(words) if w["e"] >= a and w["s"] <= b]
        sents = [s for s in sents if s["e"] >= a and s["s"] <= b]
    else:
        words = [dict(w, i=k) for k, w in enumerate(words)]
    return {"language": tr["language"], "model": tr["model"], "device": tr.get("device"), "words": words, "sentences": sents}


@router.put("/{project_id}/transcript/words")
def correct_words(project_id: str, corrections: list[dict[str, Any]], db: Session = Depends(get_db)):
    """Transcript correction: [{"i": word_index, "w": "corrected text"}]. Timing is preserved."""
    get_or_404(db, Project, project_id, "Project")
    art = storage.Artifacts(storage.project_folder(project_id))
    tr = storage.read_json(art.transcript)
    if not tr:
        raise HTTPException(404, "Transcript not available")
    from ..services import segmentation

    n = 0
    for c in corrections[:5000]:
        i = int(c.get("i", -1))
        w = str(c.get("w", "")).strip()
        if 0 <= i < len(tr["words"]) and w and len(w) < 60:
            tr["words"][i]["w"] = w
            n += 1
    speakers = {s["w0"]: s.get("speaker") for s in tr["sentences"]}
    tr["sentences"] = segmentation.build_sentences(tr["words"])
    for s in tr["sentences"]:
        labs = [tr["words"][k].get("spk", 0) for k in range(s["w0"], s["w1"])]
        s["speaker"] = max(set(labs), key=labs.count) if labs else speakers.get(s["w0"], 0)
    tr["corrected"] = True
    storage.write_json(art.transcript, tr)
    return {"updated": n}


@router.get("/{project_id}/analysis")
def analysis(project_id: str, db: Session = Depends(get_db)):
    p = get_or_404(db, Project, project_id, "Project")
    art = storage.Artifacts(storage.project_folder(project_id))
    au = storage.read_json(art.audio, {}) or {}
    dia = storage.read_json(art.diarization, {}) or {}
    sem = storage.read_json(art.semantic, {}) or {}
    scenes = storage.read_json(art.scenes, []) or []
    tr = storage.read_json(art.transcript)
    tr_sum = None
    if tr:
        tr_sum = {"language": tr["language"], "language_probability": tr["language_probability"], "model": tr["model"],
                  "device": tr.get("device"), "words": len(tr["words"]), "sentences": len(tr["sentences"]), "elapsed_s": tr.get("elapsed_s")}
    return {
        "summary": p.analysis_summary or {}, "transcript": tr_sum,
        "speakers": dia.get("speakers", []), "diarization_method": dia.get("method"), "diarization_note": dia.get("note"),
        "turns": dia.get("turns", [])[:3000],
        "scenes": scenes, "laughter": au.get("laughter", []), "excitement": au.get("excitement", []),
        "long_pauses": au.get("long_pauses", []), "speech_ratio": au.get("speech_ratio"),
        "topics": sem.get("topic_bounds", []), "keywords": sem.get("keywords", []),
    }


@router.post("/{project_id}/analyze", response_model=JobRef)
def analyze(project_id: str, body: AnalyzeRequest, db: Session = Depends(get_db)):
    p = get_or_404(db, Project, project_id, "Project")
    if latest_media(db, project_id) is None:
        raise HTTPException(400, "Import a video first")
    if _active_job(db, project_id, ("analysis", "rediscover", "import", "download")):
        raise HTTPException(409, "Analysis is already running for this project")
    params = body.model_dump(exclude_none=True)
    opts = dict(p.options or {})
    for k in ("duration_targets", "duration_tolerance", "score_weights", "max_clips_per_target", "preferences", "preset_id", "aspect", "language", "whisper_model", "analysis_quality"):
        if k in params:
            opts[k] = params[k]
    p.options = opts
    return {"job_id": manager.submit("analysis", project_id, params)}


@router.post("/{project_id}/rediscover", response_model=JobRef)
def rediscover(project_id: str, body: AnalyzeRequest, db: Session = Depends(get_db)):
    p = get_or_404(db, Project, project_id, "Project")
    art = storage.Artifacts(storage.project_folder(project_id))
    if not art.transcript.exists():
        raise HTTPException(400, "Run the full analysis first")
    if _active_job(db, project_id, ("analysis", "rediscover")):
        raise HTTPException(409, "Analysis is already running for this project")
    params = body.model_dump(exclude_none=True)
    opts = dict(p.options or {})
    for k in ("duration_targets", "duration_tolerance", "score_weights", "max_clips_per_target", "preferences", "preset_id", "aspect", "language", "whisper_model", "analysis_quality"):
        if k in params:
            opts[k] = params[k]
    p.options = opts
    return {"job_id": manager.submit("rediscover", project_id, params)}


@router.get("/{project_id}/clips")
def project_clips(project_id: str, status: Optional[str] = None, category: Optional[str] = None, min_score: float = 0,
                  target: Optional[float] = None, speaker: Optional[int] = None, sort: str = "score", db: Session = Depends(get_db)):
    p = get_or_404(db, Project, project_id, "Project")
    q = db.query(CandidateClip).filter(CandidateClip.project_id == project_id)
    if status:
        q = q.filter(CandidateClip.status.in_(status.split(",")))
    if category:
        q = q.filter(CandidateClip.category.in_(category.split(",")))
    if target:
        q = q.filter(CandidateClip.target_duration == float(target))
    q = q.filter(CandidateClip.score >= min_score)
    rows = q.all()
    if speaker is not None:
        rows = [c for c in rows if speaker in (c.speakers or [])]
    keyf = {"score": lambda c: -c.score, "timeline": lambda c: c.start, "duration": lambda c: c.end - c.start,
            "hook": lambda c: -(c.scores or {}).get("hook", 0), "story": lambda c: -(c.scores or {}).get("story", 0),
            "information": lambda c: -(c.scores or {}).get("information", 0), "emotion": lambda c: -(c.scores or {}).get("emotion", 0),
            "standalone": lambda c: -(c.scores or {}).get("standalone", 0)}.get(sort, lambda c: -c.score)
    rows.sort(key=keyf)
    return [clip_out(db, c, p.name) for c in rows]
