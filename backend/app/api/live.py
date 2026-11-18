"""Live YouTube stream clipping endpoints (`/api/live`)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import CandidateClip, Project
from ..schemas import LiveClipRequest, LiveSessionCreate, LiveSessionUpdate
from ..security import SecurityError, safe_join
from ..services.live_stream import live_manager
from .common import clip_out

router = APIRouter(prefix="/api/live", tags=["live"])


def _serialize_session_clips(db: Session, clip_ids: list[str]) -> list[dict]:
    if not clip_ids:
        return []
    rows = db.query(CandidateClip).filter(CandidateClip.id.in_(clip_ids)).all()
    by_id = {c.id: c for c in rows}
    proj_ids = {c.project_id for c in rows}
    pnames = {p.id: p.name for p in db.query(Project).filter(Project.id.in_(proj_ids)).all()} if proj_ids else {}
    out = []
    for cid in clip_ids:
        c = by_id.get(cid)
        if c is not None:
            out.append(clip_out(db, c, pnames.get(c.project_id)))
    return out


@router.get("/sessions")
def list_sessions():
    return live_manager.list_all()


@router.post("/sessions")
def create_session(body: LiveSessionCreate, db: Session = Depends(get_db)):
    if not body.confirm_rights:
        raise HTTPException(
            400,
            "Please confirm that you own or are authorized to capture and clip this YouTube stream.",
        )
    try:
        sess = live_manager.create(
            url=body.url,
            language=body.language,
            preset_id=body.preset_id,
            aspect=body.aspect,
            auto_highlight=body.auto_highlight,
            dvr_minutes=body.dvr_minutes,
            target_duration=body.target_duration,
        )
    except SecurityError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    return sess.detail_dict(_serialize_session_clips(db, sess.clip_ids))


@router.get("/sessions/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db)):
    sess = live_manager.get(session_id)
    if sess is None:
        raise HTTPException(404, "Live session not found")
    sess.sync_playlist()
    return sess.detail_dict(_serialize_session_clips(db, sess.clip_ids))


@router.patch("/sessions/{session_id}")
def update_session(session_id: str, body: LiveSessionUpdate, db: Session = Depends(get_db)):
    sess = live_manager.get(session_id)
    if sess is None:
        raise HTTPException(404, "Live session not found")
    sess.update_options(**body.model_dump(exclude_none=True))
    return sess.detail_dict(_serialize_session_clips(db, sess.clip_ids))


@router.post("/sessions/{session_id}/clip")
def clip_from_live(
    session_id: str,
    body: LiveClipRequest,
    wait: bool = Query(default=False),
):
    sess = live_manager.get(session_id)
    if sess is None:
        raise HTTPException(404, "Live session not found")
    sess.sync_playlist()
    if body.mode == "range":
        if body.start_time is None or body.end_time is None or body.end_time <= body.start_time:
            raise HTTPException(400, "Out marker must be after In marker")
        s_t, e_t = float(body.start_time), float(body.end_time)
    else:
        anchor = float(body.anchor_stream_time) if body.anchor_stream_time is not None else sess.dvr_end
        e_t = min(sess.dvr_end, anchor)
        s_t = max(sess.dvr_start, e_t - float(body.duration))
    try:
        return sess.enqueue_clip(start_time=s_t, end_time=e_t, source="manual", title=body.title, wait=wait)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))


@router.post("/sessions/{session_id}/stop")
def stop_session(session_id: str, db: Session = Depends(get_db)):
    sess = live_manager.get(session_id)
    if sess is None:
        raise HTTPException(404, "Live session not found")
    sess.stop()
    return sess.detail_dict(_serialize_session_clips(db, sess.clip_ids))


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    if not live_manager.delete(session_id):
        raise HTTPException(404, "Live session not found")
    return {"deleted": True}


@router.get("/sessions/{session_id}/hls/{filename}")
def serve_hls(session_id: str, filename: str):
    sess = live_manager.get(session_id)
    if sess is None:
        raise HTTPException(404, "Live session not found")
    if "/" in filename or "\\" in filename or not filename.endswith((".m3u8", ".ts")):
        raise HTTPException(400, "Invalid HLS segment request")
    try:
        target = safe_join(sess.hls_dir, filename)
    except SecurityError:
        raise HTTPException(400, "Invalid path")
    if not target.is_file():
        raise HTTPException(404, "Segment not ready yet")
    if filename.endswith(".m3u8"):
        return FileResponse(
            target,
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )
    return FileResponse(
        target,
        media_type="video/mp2t",
        headers={"Cache-Control": "public, max-age=120"},
    )
