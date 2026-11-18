"""Audio library management: built-in CC0 assets, user imports and mood-based recommendations."""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .. import config
from ..models import AudioAsset, Timeline
from ..security import AUDIO_EXTENSIONS, SecurityError, sanitize_filename
from . import media
from .presets import CATEGORY_MOODS

log = logging.getLogger("clipforge.audio_lib")

MUSIC_CATEGORIES = ["cinematic", "motivational", "emotional", "corporate", "podcast", "documentary", "suspense", "comedy", "lofi", "energetic"]
SFX_CATEGORIES = ["whoosh", "impact", "pop", "riser", "transition", "cinematic_hit", "notification", "comedy"]


def ensure_builtin_assets() -> dict[str, Any] | None:
    manifest = config.BUILTIN_AUDIO_DIR / "manifest.json"
    if manifest.exists():
        return json.loads(manifest.read_text())
    ff = media.ffmpeg_bin()
    if not ff:
        return None
    from . import audio_synth

    log.info("Generating built-in audio library (one-time)...")
    return audio_synth.generate(config.BUILTIN_AUDIO_DIR, ff)


def resolve_asset_path(a: AudioAsset) -> str | None:
    """Return a valid on-disk path for `a`, relocating built-in assets if the app folder moved."""
    if a.path and Path(a.path).is_file():
        return str(Path(a.path))
    if a.origin == "builtin" and a.path:
        fname = Path(a.path).name
        sub_dir = "music" if a.kind == "music" else "sfx"
        for cand in (config.BUILTIN_AUDIO_DIR / sub_dir / fname, config.BUILTIN_AUDIO_DIR / fname):
            if cand.is_file():
                return str(cand.resolve())
    return None


def sync_builtin(db: Session) -> int:
    manifest = ensure_builtin_assets()
    if not manifest:
        return 0
    rows = db.query(AudioAsset).filter(AudioAsset.origin == "builtin").order_by(AudioAsset.created_at.asc()).all()
    by_key: dict[tuple[str, str], AudioAsset] = {}
    id_remap: dict[str, str] = {}
    dups: list[AudioAsset] = []
    for r in rows:
        key = (r.kind, r.name)
        if key not in by_key:
            by_key[key] = r
        else:
            id_remap[r.id] = by_key[key].id
            dups.append(r)

    if id_remap:
        for tl in db.query(Timeline).all():
            d = dict(tl.data or {})
            changed = False
            mus = dict(d.get("music") or {})
            for mk in ("asset_id", "recommended_id"):
                if mus.get(mk) in id_remap:
                    mus[mk] = id_remap[mus[mk]]
                    changed = True
            if changed:
                d["music"] = mus
            if d.get("sfx_recommended_id") in id_remap:
                d["sfx_recommended_id"] = id_remap[d["sfx_recommended_id"]]
                changed = True
            sfx_list = list(d.get("sfx") or [])
            sfx_changed = False
            for fx in sfx_list:
                if isinstance(fx, dict) and fx.get("asset_id") in id_remap:
                    fx["asset_id"] = id_remap[fx["asset_id"]]
                    sfx_changed = True
            if sfx_changed:
                d["sfx"] = sfx_list
                changed = True
            if changed:
                tl.data = d
        for r in dups:
            db.delete(r)

    n = 0
    for it in manifest["items"]:
        p = str((config.BUILTIN_AUDIO_DIR / it["file"]).resolve())
        key = (it["kind"], it["name"])
        if key in by_key:
            cur = by_key[key]
            if cur.path != p:
                cur.path = p
                n += 1
            continue
        db.add(AudioAsset(kind=it["kind"], category=it["category"], name=it["name"], path=p, duration=it["duration"],
                          moods=it.get("moods", []), bpm=it.get("bpm"), license=manifest.get("license", "CC0"), origin="builtin"))
        n += 1
    db.flush()
    return n


def import_user_audio(db: Session, src: Path, kind: str, category: str, name: str | None, license_note: str) -> AudioAsset:
    if src.suffix.lower() not in AUDIO_EXTENSIONS:
        raise SecurityError("Unsupported audio format")
    info = media.probe(src)
    if not info["has_audio"]:
        raise SecurityError("File has no audio stream")
    config.USER_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    dst = config.USER_AUDIO_DIR / sanitize_filename(src.name)
    k = 1
    while dst.exists():
        dst = config.USER_AUDIO_DIR / f"{dst.stem}_{k}{dst.suffix}"
        k += 1
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    a = AudioAsset(kind=kind, category=category, name=name or src.stem, path=str(dst), duration=info["duration"],
                   moods=[category], license=license_note or "User-provided (user confirmed rights)", origin="user")
    db.add(a)
    db.flush()
    return a


def recommend_music(db: Session, category: str, preset_moods: list[str]) -> AudioAsset | None:
    cat_moods = CATEGORY_MOODS.get(category, ["podcast"])
    order = [m for m in cat_moods if m in preset_moods] + list(preset_moods) + cat_moods
    assets = db.query(AudioAsset).filter(AudioAsset.kind == "music").all()
    for mood in order:
        for a in assets:
            if a.category == mood:
                return a
    return assets[0] if assets else None


def recommend_sfx(db: Session, category: str) -> AudioAsset | None:
    pref = {"funny": ["pop", "comedy"], "emotional": ["cinematic_hit", "impact"], "story": ["whoosh", "transition"],
            "opinion": ["impact", "whoosh"], "advice": ["pop", "notification"], "educational": ["pop", "notification"]}.get(
        category, ["whoosh", "pop"])
    assets = db.query(AudioAsset).filter(AudioAsset.kind == "sfx").all()
    for c in pref:
        for a in assets:
            if a.category == c:
                return a
    return assets[0] if assets else None


def asset_to_dict(a: AudioAsset) -> dict[str, Any]:
    return {"id": a.id, "kind": a.kind, "category": a.category, "name": a.name, "duration": a.duration, "moods": a.moods,
            "bpm": a.bpm, "license": a.license, "origin": a.origin, "url": f"/api/audio/{a.id}/file"}
