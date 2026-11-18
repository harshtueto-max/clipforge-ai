"""Clip, editor, caption and export endpoints."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..jobs import manager
from ..models import AudioAsset, CandidateClip, CaptionTrack, ExportJob, Project, Timeline
from ..schemas import (ApplyPreset, BatchAction, CaptionsLanguageRequest, CaptionsRebuild, CaptionsUpdate, ClipUpdate, ExportSettings, JobRef, ReframeRequest,
                       TimelineUpdate)
from ..security import SecurityError, validate_output_dir
from ..services import captions, discovery, hinglish, pipeline, reframe, segmentation, storage, transcription
from ..services.audio_library import asset_to_dict
from .common import clip_out, export_out, get_or_404, latest_media, media_out

router = APIRouter(prefix="/api/clips", tags=["clips"])


@router.get("")
def clip_library(status: Optional[str] = None, category: Optional[str] = None, min_score: float = 0, q: Optional[str] = None,
                 sort: str = "score", limit: int = 500, db: Session = Depends(get_db)):
    query = db.query(CandidateClip)
    if status:
        query = query.filter(CandidateClip.status.in_(status.split(",")))
    if category:
        query = query.filter(CandidateClip.category.in_(category.split(",")))
    query = query.filter(CandidateClip.score >= min_score)
    if q:
        like = f"%{q}%"
        query = query.filter((CandidateClip.title.ilike(like)) | (CandidateClip.transcript.ilike(like)))
    order = {"score": CandidateClip.score.desc(), "recent": CandidateClip.created_at.desc()}.get(sort, CandidateClip.score.desc())
    rows = query.order_by(order).limit(min(2000, limit)).all()
    names = {p.id: p.name for p in db.query(Project).all()}
    return [clip_out(db, c, names.get(c.project_id)) for c in rows]


@router.get("/{clip_id}")
def get_clip(clip_id: str, db: Session = Depends(get_db)):
    c = get_or_404(db, CandidateClip, clip_id, "Clip")
    return clip_out(db, c)


@router.patch("/{clip_id}")
def update_clip(clip_id: str, body: ClipUpdate, db: Session = Depends(get_db)):
    c = get_or_404(db, CandidateClip, clip_id, "Clip")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(c, k, v)
    db.flush()
    return clip_out(db, c)


@router.delete("/{clip_id}")
def delete_clip(clip_id: str, db: Session = Depends(get_db)):
    c = get_or_404(db, CandidateClip, clip_id, "Clip")
    if c.thumbnail:
        Path(c.thumbnail).unlink(missing_ok=True)
    db.delete(c)
    return {"deleted": True}


@router.get("/{clip_id}/thumbnail")
def clip_thumb(clip_id: str, db: Session = Depends(get_db)):
    c = get_or_404(db, CandidateClip, clip_id, "Clip")
    if not c.thumbnail or not Path(c.thumbnail).exists():
        raise HTTPException(404, "No thumbnail")
    return FileResponse(c.thumbnail, media_type="image/jpeg", headers={"Cache-Control": "max-age=30"})


@router.post("/batch")
def batch(body: BatchAction, db: Session = Depends(get_db)):
    rows = db.query(CandidateClip).filter(CandidateClip.id.in_(body.ids)).all()
    out = {"updated": 0, "jobs": []}
    for c in rows:
        if body.action == "accept":
            c.status = "accepted"
        elif body.action == "reject":
            c.status = "rejected"
        elif body.action == "reset":
            c.status = "suggested"
        elif body.action == "delete":
            db.delete(c)
        elif body.action == "export":
            settings = ExportSettings(**body.export_settings)
            out["jobs"].append(_queue_export(db, c, settings))
        out["updated"] += 1
    return out


@router.post("/{clip_id}/regenerate")
def regenerate(clip_id: str, db: Session = Depends(get_db)):
    """Find alternative boundaries for the same moment, re-score and rebuild the automatic edit."""
    c = get_or_404(db, CandidateClip, clip_id, "Clip")
    proj = db.get(Project, c.project_id)
    bundle, vis, scenes, m, _ = pipeline.load_bundle(c.project_id)
    s = config.get_settings()
    opts = proj.options or {}
    tol = float(opts.get("duration_tolerance") or s["duration_tolerance"])
    weights = opts.get("score_weights") or s["score_weights"]
    hist = list((c.explanations or {}).get("_history", [])) + [[c.start, c.end]]
    alt = discovery.alternatives(bundle, c.start, c.end, c.target_duration, tol, weights, [tuple(x) for x in hist])
    if alt is None:
        raise HTTPException(409, "No meaningfully different boundaries were found for this moment")
    c.start, c.end, c.score, c.scores = alt["start"], alt["end"], alt["score"], alt["scores"]
    c.explanations = {**alt["explanations"], "_history": hist[-10:]}
    c.title, c.hook, c.description, c.reason = alt["title"], alt["hook"], alt["description"], alt["reason"]
    c.category, c.transcript, c.speakers, c.fits_duration = alt["category"], alt["transcript"], alt["speakers"], alt["fits_duration"]
    c.analysis_source = "local"
    db.commit()
    tl = db.query(Timeline).filter(Timeline.clip_id == c.id).first()
    preset_id = (tl.data or {}).get("preset_id") if tl else None
    aspect = (tl.data or {}).get("aspect") if tl else None
    pipeline.create_auto_edit(c.id, preset_id or s["default_preset"], aspect or s["default_aspect"], bundle, vis, scenes, m)
    db.expire_all()
    return clip_out(db, db.get(CandidateClip, clip_id))


@router.post("/{clip_id}/duplicate")
def duplicate(clip_id: str, db: Session = Depends(get_db)):
    c = get_or_404(db, CandidateClip, clip_id, "Clip")
    n = CandidateClip(project_id=c.project_id, parent_id=c.id, target_duration=c.target_duration, start=c.start, end=c.end, score=c.score,
                      scores=dict(c.scores or {}), explanations=dict(c.explanations or {}), title=f"{c.title} (alt)", category=c.category,
                      hook=c.hook, description=c.description, reason=c.reason, transcript=c.transcript, speakers=list(c.speakers or []),
                      tags=[], status="suggested", fits_duration=c.fits_duration, analysis_source=c.analysis_source, thumbnail=None, rank=c.rank)
    db.add(n)
    db.flush()
    tl = db.query(Timeline).filter(Timeline.clip_id == c.id).first()
    cap = db.query(CaptionTrack).filter(CaptionTrack.clip_id == c.id).first()
    if tl:
        db.add(Timeline(clip_id=n.id, data=copy.deepcopy(tl.data), version=2))
    if cap:
        db.add(CaptionTrack(clip_id=n.id, style=copy.deepcopy(cap.style), items=copy.deepcopy(cap.items)))
    if c.thumbnail and Path(c.thumbnail).exists():
        import shutil

        dst = Path(c.thumbnail).with_name(f"clip_{n.id}.jpg")
        shutil.copy2(c.thumbnail, dst)
        n.thumbnail = str(dst)
    db.flush()
    return clip_out(db, n)


# ---------------------------------------------------------------- editor
@router.get("/{clip_id}/editor")
def editor_state(clip_id: str, db: Session = Depends(get_db)):
    c = get_or_404(db, CandidateClip, clip_id, "Clip")
    tl = db.query(Timeline).filter(Timeline.clip_id == c.id).first()
    cap = db.query(CaptionTrack).filter(CaptionTrack.clip_id == c.id).first()
    if tl is None:
        s = config.get_settings()
        pipeline.create_auto_edit(c.id, s["default_preset"], s["default_aspect"])
        db.expire_all()
        tl = db.query(Timeline).filter(Timeline.clip_id == c.id).first()
        cap = db.query(CaptionTrack).filter(CaptionTrack.clip_id == c.id).first()
    m = latest_media(db, c.project_id)
    art = storage.Artifacts(storage.project_folder(c.project_id))
    tr = storage.read_json(art.transcript, {"words": [], "sentences": []})
    lo, hi = min(c.start, tl.data["start"]) - 60, max(c.end, tl.data["end"]) + 60
    words = [dict(w, i=k) for k, w in enumerate(tr["words"]) if w["e"] >= lo and w["s"] <= hi]
    sents = [s for s in tr["sentences"] if s["e"] >= lo and s["s"] <= hi]
    scenes = [s for s in (storage.read_json(art.scenes, []) or []) if s["e"] >= lo and s["s"] <= hi]
    assets = [asset_to_dict(a) for a in db.query(AudioAsset).order_by(AudioAsset.kind, AudioAsset.category).all()]
    cap_items = captions.sanitize_items(cap.items) if cap and cap.items else []
    if cap and cap_items != (cap.items or []):
        cap.items = cap_items
        db.flush()
    return {
        "clip": clip_out(db, c), "timeline": tl.data, "timeline_version": tl.version,
        "captions": {"style": cap.style if cap else captions.style_for("podcast_pro"), "items": cap_items},
        "media": media_out(m), "words": words, "sentences": sents, "scenes": scenes, "assets": assets,
        "caption_styles": captions.CAPTION_STYLES,
        "output_sizes": reframe.OUTPUT_SIZES,
    }


@router.put("/{clip_id}/timeline")
def save_timeline(clip_id: str, body: TimelineUpdate, db: Session = Depends(get_db)):
    c = get_or_404(db, CandidateClip, clip_id, "Clip")
    m = latest_media(db, c.project_id)
    d = body.data
    d["start"] = max(0.0, float(d["start"]))
    if m:
        d["end"] = min(float(d["end"]), m.duration)
    segs = segmentation.keep_segments(d["start"], d["end"], d.get("cuts", []))
    if not segs:
        raise HTTPException(400, "Cuts remove the entire clip")
    tl = db.query(Timeline).filter(Timeline.clip_id == c.id).first()
    if tl is None:
        tl = Timeline(clip_id=c.id, data=d, version=2)
        db.add(tl)
    else:
        if body.base_version is not None and body.base_version < tl.version - 50:
            raise HTTPException(409, "Timeline was modified elsewhere; reload the editor")
        tl.data = d
        tl.version = tl.version + 1
    db.flush()
    return {"version": tl.version, "output_duration": segmentation.output_duration(segs)}


@router.put("/{clip_id}/captions")
def save_captions(clip_id: str, body: CaptionsUpdate, db: Session = Depends(get_db)):
    c = get_or_404(db, CandidateClip, clip_id, "Clip")
    cap = db.query(CaptionTrack).filter(CaptionTrack.clip_id == c.id).first()
    items = sorted(body.items, key=lambda x: float(x["start"]))
    for it in items:
        it.setdefault("id", captions.short_id())
        it.setdefault("style", {})
        it["text"] = str(it.get("text", "")).strip()
    items = captions.sanitize_items(items)
    if cap is None:
        db.add(CaptionTrack(clip_id=c.id, style=body.style, items=items))
    else:
        cap.style, cap.items = body.style, items
    tl = db.query(Timeline).filter(Timeline.clip_id == c.id).first()
    if tl:
        tl.version += 1
    return {"count": len(items)}


@router.post("/{clip_id}/captions/rebuild")
def rebuild_captions(clip_id: str, body: CaptionsRebuild, db: Session = Depends(get_db)):
    c = get_or_404(db, CandidateClip, clip_id, "Clip")
    tl = db.query(Timeline).filter(Timeline.clip_id == c.id).first()
    cap = db.query(CaptionTrack).filter(CaptionTrack.clip_id == c.id).first()
    art = storage.Artifacts(storage.project_folder(c.project_id))
    tr = storage.read_json(art.transcript, {"words": []})
    style_id = body.style_id or (cap.style.get("id") if cap else "podcast_pro")
    st = captions.style_for(style_id)
    if cap and not body.style_id:
        st.update({k: v for k, v in cap.style.items() if k != "id"})
    wpc = body.words_per_caption or int(st.get("words_per_caption", 4))
    st["words_per_caption"] = wpc
    start, end = (tl.data["start"], tl.data["end"]) if tl else (c.start, c.end)
    items = captions.build_items(tr["words"], start, end, wpc)
    if cap is None:
        cap = CaptionTrack(clip_id=c.id, style=st, items=items)
        db.add(cap)
    else:
        cap.style, cap.items = st, items
    if tl:
        tl.version += 1
    return {"style": st, "items": items}


@router.post("/{clip_id}/captions/language")
def generate_captions_language(clip_id: str, body: CaptionsLanguageRequest, db: Session = Depends(get_db)):
    """Re-transcribe / translate just this clip's audio slice into Hinglish (Roman), Hindi (Devanagari), or English."""
    c = get_or_404(db, CandidateClip, clip_id, "Clip")
    tl = db.query(Timeline).filter(Timeline.clip_id == c.id).first()
    cap = db.query(CaptionTrack).filter(CaptionTrack.clip_id == c.id).first()
    art = storage.Artifacts(storage.project_folder(c.project_id))
    if not art.wav.exists():
        raise HTTPException(400, "Project analysis audio not found — run analysis first")
    tr_meta = storage.read_json(art.transcript, {})
    s_cfg = config.get_settings()
    start, end = (float(tl.data["start"]), float(tl.data["end"])) if tl else (c.start, c.end)
    try:
        words, used_model = transcription.transcribe_slice(
            art.wav, start, end, mode=body.mode,
            model_name=tr_meta.get("model") or s_cfg.get("whisper_model"),
            device_pref=s_cfg.get("whisper_device", "auto"),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Caption generation failed: {exc}")
    style_id = cap.style.get("id", "podcast_pro") if cap else "podcast_pro"
    st = captions.style_for(style_id)
    if cap:
        st.update({k: v for k, v in cap.style.items() if k != "id"})
    wpc = body.words_per_caption or int(st.get("words_per_caption", 4))
    st["words_per_caption"] = wpc
    st["caption_lang"] = body.mode
    items = captions.build_items(words, start, end, wpc)
    if (body.mode == "hi" or any(hinglish.has_devanagari(it["text"]) for it in items)) and st.get("font") not in captions.DEVANAGARI_FONTS:
        st["font"] = captions.default_devanagari_font()
        st["bold"] = True
    if cap is None:
        cap = CaptionTrack(clip_id=c.id, style=st, items=items)
        db.add(cap)
    else:
        cap.style, cap.items = st, items
    if tl:
        tl.version += 1
    return {"style": st, "items": items, "mode": body.mode, "model": used_model}


@router.post("/{clip_id}/apply-preset")
def apply_preset(clip_id: str, body: ApplyPreset, db: Session = Depends(get_db)):
    c = get_or_404(db, CandidateClip, clip_id, "Clip")
    tl = db.query(Timeline).filter(Timeline.clip_id == c.id).first()
    keep_range = (tl.data["start"], tl.data["end"]) if tl else None
    aspect = body.aspect or ((tl.data or {}).get("aspect") if tl else None) or config.get_settings()["default_aspect"]
    if keep_range:
        c.start, c.end = keep_range
        db.commit()
    pipeline.create_auto_edit(c.id, body.preset_id, aspect)
    db.expire_all()
    return editor_state(clip_id, db)


@router.post("/{clip_id}/reframe")
def recompute_reframe(clip_id: str, body: ReframeRequest, db: Session = Depends(get_db)):
    c = get_or_404(db, CandidateClip, clip_id, "Clip")
    tl = db.query(Timeline).filter(Timeline.clip_id == c.id).first()
    if tl is None:
        raise HTTPException(404, "Timeline not found")
    bundle, vis, scenes, m, _ = pipeline.load_bundle(c.project_id)
    d = copy.deepcopy(tl.data)
    aspect = body.aspect or d.get("aspect", "9:16")
    if body.mode == "manual":
        rf = d.get("reframe", {})
        rf.update({"mode": "manual", "aspect": aspect})
        if not rf.get("keyframes"):
            rf["keyframes"] = [{"t": d["start"], "x": 0.5, "y": 0.5}]
        rf["layouts"] = []
    else:
        spk_pos = {int(k): v for k, v in (vis.get("speaker_positions") or {}).items()}
        mode = "auto" if body.mode == "single" else body.mode
        rf = reframe.compute(vis.get("samples", []), scenes, bundle.sentences, spk_pos, m.width, m.height, aspect, d["start"], d["end"],
                             mode=mode, smoothness=body.smoothness, prefer_split=(body.mode == "split"))
        rf["mode"] = body.mode
        rf["smoothness"] = body.smoothness
        rf["offset"] = (d.get("reframe") or {}).get("offset", {"x": 0, "y": 0}) if body.mode != "center" else {"x": 0, "y": 0}
    d["reframe"] = rf
    d["aspect"] = aspect
    tl.data = d
    tl.version += 1
    db.flush()
    return {"timeline": d, "version": tl.version}


@router.post("/{clip_id}/rescore")
def rescore(clip_id: str, db: Session = Depends(get_db)):
    c = get_or_404(db, CandidateClip, clip_id, "Clip")
    tl = db.query(Timeline).filter(Timeline.clip_id == c.id).first()
    bundle, *_ = pipeline.load_bundle(c.project_id)
    s = config.get_settings()
    proj = db.get(Project, c.project_id)
    weights = (proj.options or {}).get("score_weights") or s["score_weights"]
    start, end = (tl.data["start"], tl.data["end"]) if tl else (c.start, c.end)
    r = discovery.score_range(bundle, start, end, weights)
    c.score, c.scores, c.reason = r["score"], r["scores"], r["reason"]
    c.explanations = {**r["explanations"], "_history": (c.explanations or {}).get("_history", [])}
    c.start, c.end = start, end
    c.transcript = discovery.clip_text(bundle, r["i"], r["j"])
    db.flush()
    return clip_out(db, c)


# ---------------------------------------------------------------- export
def _queue_export(db: Session, c: CandidateClip, settings: ExportSettings) -> dict:
    sd = settings.model_dump()
    if config.PUBLIC_CLOUD:
        sd["output_dir"] = str(config.exports_dir())
    elif sd.get("output_dir"):
        try:
            sd["output_dir"] = str(validate_output_dir(sd["output_dir"]))
        except SecurityError as exc:
            raise HTTPException(400, str(exc))
    else:
        sd["output_dir"] = str(config.exports_dir())
    ex = ExportJob(project_id=c.project_id, clip_id=c.id, status="queued", settings=sd, clip_title=c.title)
    db.add(ex)
    db.commit()
    job_id = manager.submit("render", c.project_id, {"export_id": ex.id, "clip_id": c.id})
    ex.job_id = job_id
    db.commit()
    return {"export_id": ex.id, "job_id": job_id}


@router.post("/{clip_id}/export")
def export_clip(clip_id: str, body: ExportSettings, db: Session = Depends(get_db)):
    c = get_or_404(db, CandidateClip, clip_id, "Clip")
    return _queue_export(db, c, body)


@router.get("/{clip_id}/exports")
def clip_exports(clip_id: str, db: Session = Depends(get_db)):
    rows = db.query(ExportJob).filter(ExportJob.clip_id == clip_id).order_by(ExportJob.created_at.desc()).all()
    return [export_out(db, e) for e in rows]
