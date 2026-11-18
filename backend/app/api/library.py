"""Audio library, presets, caption styles and fonts."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..models import AudioAsset, Preset
from ..schemas import AudioOut, PresetIn
from ..security import AUDIO_EXTENSIONS, SecurityError, sanitize_filename
from ..services import audio_library, captions
from ..services.presets import BUILTIN_PRESETS
from .common import get_or_404

router = APIRouter(tags=["library"])


@router.get("/api/audio", response_model=list[AudioOut])
def list_audio(kind: Optional[str] = None, category: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(AudioAsset)
    if kind:
        q = q.filter(AudioAsset.kind == kind)
    if category:
        q = q.filter(AudioAsset.category == category)
    return [audio_library.asset_to_dict(a) for a in q.order_by(AudioAsset.kind, AudioAsset.category, AudioAsset.name).all()]


@router.get("/api/audio/categories")
def audio_categories():
    return {"music": audio_library.MUSIC_CATEGORIES, "sfx": audio_library.SFX_CATEGORIES}


@router.get("/api/audio/{asset_id}/file")
def audio_file(asset_id: str, db: Session = Depends(get_db)):
    a = get_or_404(db, AudioAsset, asset_id, "Audio asset")
    resolved = audio_library.resolve_asset_path(a)
    if not resolved:
        raise HTTPException(404, "Audio file missing")
    if a.path != resolved:
        a.path = resolved
        db.flush()
    mt = {".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".flac": "audio/flac",
          ".aac": "audio/aac", ".opus": "audio/ogg"}.get(Path(resolved).suffix.lower(), "application/octet-stream")
    return FileResponse(resolved, media_type=mt)


@router.post("/api/audio/import", response_model=AudioOut)
async def import_audio(request: Request, kind: str = "music", category: str = "podcast", name: Optional[str] = None,
                       license_note: str = "", confirm_rights: bool = False, db: Session = Depends(get_db)):
    if not confirm_rights:
        raise HTTPException(400, "Confirm that you have the rights to use this audio")
    if kind not in ("music", "sfx"):
        raise HTTPException(400, "kind must be music or sfx")
    cats = audio_library.MUSIC_CATEGORIES if kind == "music" else audio_library.SFX_CATEGORIES
    if category not in cats:
        raise HTTPException(400, f"category must be one of {cats}")
    fname = sanitize_filename(unquote(request.headers.get("x-filename", "audio.mp3")), default="audio.mp3")
    if Path(fname).suffix.lower() not in AUDIO_EXTENSIONS:
        raise HTTPException(400, "Unsupported audio format")
    config.TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = config.TMP_DIR / fname
    size = 0
    with open(tmp, "wb") as f:
        async for chunk in request.stream():
            size += len(chunk)
            if size > 500 * 1024 * 1024:
                f.close()
                tmp.unlink(missing_ok=True)
                raise HTTPException(413, "Audio file too large (max 500 MB)")
            f.write(chunk)
    try:
        a = audio_library.import_user_audio(db, tmp, kind, category, name, license_note)
    except (SecurityError, Exception) as exc:
        raise HTTPException(400, f"Could not import audio: {exc}")
    finally:
        tmp.unlink(missing_ok=True)
    return audio_library.asset_to_dict(a)


@router.delete("/api/audio/{asset_id}")
def delete_audio(asset_id: str, db: Session = Depends(get_db)):
    a = get_or_404(db, AudioAsset, asset_id, "Audio asset")
    if a.origin != "user":
        raise HTTPException(400, "Built-in assets cannot be deleted")
    Path(a.path).unlink(missing_ok=True)
    db.delete(a)
    return {"deleted": True}


# ---------------------------------------------------------------- presets
def _preset_dict(p: Preset) -> dict:
    return {"id": p.id, "name": p.name, "description": p.description, "builtin": p.builtin, "config": p.config}


def sync_builtin_presets(db: Session) -> None:
    for pid, spec in BUILTIN_PRESETS.items():
        row = db.get(Preset, pid)
        if row is None:
            db.add(Preset(id=pid, name=spec["name"], description=spec["description"], builtin=True, config=spec["config"]))
        else:
            row.name, row.description, row.config, row.builtin = spec["name"], spec["description"], spec["config"], True


@router.get("/api/presets")
def list_presets(db: Session = Depends(get_db)):
    rows = db.query(Preset).all()
    rows.sort(key=lambda p: (not p.builtin, list(BUILTIN_PRESETS).index(p.id) if p.id in BUILTIN_PRESETS else 0, p.name))
    return [_preset_dict(p) for p in rows]


@router.post("/api/presets")
def create_preset(body: PresetIn, db: Session = Depends(get_db)):
    p = Preset(name=body.name, description=body.description, builtin=False, config=body.config)
    db.add(p)
    db.flush()
    return _preset_dict(p)


@router.put("/api/presets/{preset_id}")
def update_preset(preset_id: str, body: PresetIn, db: Session = Depends(get_db)):
    p = get_or_404(db, Preset, preset_id, "Preset")
    if p.builtin:
        raise HTTPException(400, "Built-in presets are read-only - duplicate it to customise")
    p.name, p.description, p.config = body.name, body.description, body.config
    return _preset_dict(p)


@router.post("/api/presets/{preset_id}/duplicate")
def duplicate_preset(preset_id: str, db: Session = Depends(get_db)):
    p = get_or_404(db, Preset, preset_id, "Preset")
    n = Preset(name=f"{p.name} (copy)", description=p.description, builtin=False, config=dict(p.config))
    db.add(n)
    db.flush()
    return _preset_dict(n)


@router.delete("/api/presets/{preset_id}")
def delete_preset(preset_id: str, db: Session = Depends(get_db)):
    p = get_or_404(db, Preset, preset_id, "Preset")
    if p.builtin:
        raise HTTPException(400, "Built-in presets cannot be deleted")
    db.delete(p)
    return {"deleted": True}


@router.get("/api/caption-styles")
def caption_styles():
    return captions.CAPTION_STYLES


FONT_CANDIDATES = {
    "Arial": "arial.ttf", "Arial Black": "ariblk.ttf", "Impact": "impact.ttf", "Nirmala UI": "Nirmala.ttc",
    "Segoe UI": "segoeui.ttf", "Segoe UI Semibold": "seguisb.ttf", "Segoe UI Black": "seguibl.ttf", "Verdana": "verdana.ttf",
    "Georgia": "georgia.ttf", "Trebuchet MS": "trebuc.ttf", "Bahnschrift": "bahnschrift.ttf", "Calibri": "calibri.ttf",
    "Tahoma": "tahoma.ttf", "Comic Sans MS": "comic.ttf", "Consolas": "consola.ttf", "Times New Roman": "times.ttf",
    "Franklin Gothic Medium": "framd.ttf", "Mangal": "mangal.ttf",
}


@router.get("/api/fonts")
def fonts():
    import os
    import sys

    if sys.platform != "win32":
        return ["Noto Sans Devanagari", "Noto Sans", "DejaVu Sans", "Liberation Sans", "Arial", "Impact"]
    fdir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    out = [name for name, f in FONT_CANDIDATES.items() if (fdir / f).exists()]
    return out or list(FONT_CANDIDATES)
