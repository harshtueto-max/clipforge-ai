"""System status, dependency checks, settings, native dialogs and local data deletion."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import __version__, config
from ..db import get_db
from ..jobs import manager
from ..models import AIProvider, CandidateClip, ExportJob, Job, Project
from ..schemas import SettingsUpdate
from ..security import SecurityError, clear_secrets, validate_output_dir
from ..services import media, transcription, vision
from ..services.system_info import ffmpeg_version, hardware_summary, live_status

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health():
    return {"ok": True, "app": config.APP_NAME, "version": __version__}


@router.get("/api/system/status")
def system_status(db: Session = Depends(get_db)):
    s = config.get_settings()
    active = db.query(Job).filter(Job.status.in_(["queued", "running"])).count()
    return {"live": live_status(), "hardware": hardware_summary(), "offline_mode": s["offline_mode"], "active_jobs": active,
            "whisper_model": s["whisper_model"], "whisper_installed": transcription.is_installed(s["whisper_model"])}


@router.get("/api/system/dependencies")
def dependencies():
    checks: list[dict[str, Any]] = []

    def add(name, ok, detail, required=True, fix=None):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "required": required, "fix": fix})

    fv = ffmpeg_version()
    add("FFmpeg", bool(fv), fv or "not found on PATH", fix="Run setup.bat (installs FFmpeg via winget) or install from https://www.gyan.dev/ffmpeg/builds/")
    add("FFprobe", bool(media.ffprobe_bin()), media.ffprobe_bin() or "not found", fix="Installed together with FFmpeg")
    add("Python", sys.version_info >= (3, 10), sys.version.split()[0])
    eng = transcription.engine_status()
    add("Speech recognition engine", eng["available"], eng["engine"] if eng["available"] else eng["error"],
        fix="Re-run setup.bat. If Windows Smart App Control blocks DLLs, see TROUBLESHOOTING.md")
    s = config.get_settings()
    add(f"Whisper model '{s['whisper_model']}'", transcription.is_installed(s["whisper_model"]),
        "installed" if transcription.is_installed(s["whisper_model"]) else "not downloaded", fix="Settings > AI Models > Download")
    ok, msg = transcription.cuda_usable() if eng["available"] else (False, "n/a")
    add("NVIDIA CUDA (optional)", ok, msg, required=False, fix="Optional: setup.bat installs CUDA runtime wheels when an NVIDIA GPU is present")
    add("NVENC hardware encoding (optional)", media.encoder_works("h264_nvenc"), "h264_nvenc", required=False)
    add("YuNet face detector (optional)", vision.yunet_installed(), "installed" if vision.yunet_installed() else "using Haar cascade fallback",
        required=False, fix="Settings > AI Models > YuNet")
    add("Audio library", (config.BUILTIN_AUDIO_DIR / "manifest.json").exists(), str(config.BUILTIN_AUDIO_DIR), required=False)
    for mod in ("cv2", "scenedetect", "librosa", "sklearn", "vaderSentiment", "yt_dlp"):
        try:
            __import__(mod)
            add(f"Python module {mod}", True, "ok")
        except Exception as exc:  # noqa: BLE001
            add(f"Python module {mod}", False, str(exc), fix="Re-run setup.bat")
    free = shutil.disk_usage(config.projects_dir()).free / 1e9
    min_free = 0.1 if config.PUBLIC_CLOUD else 5.0
    add("Free disk space", free > min_free, f"{free:.1f} GB free in projects folder", fix="Free up space or choose another projects folder")
    return {"checks": checks, "ready": all(c["ok"] for c in checks if c["required"])}


@router.get("/api/settings")
def get_settings():
    return config.get_settings()


@router.put("/api/settings")
def put_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    upd = body.model_dump(exclude_none=True)
    if config.PUBLIC_CLOUD:
        for blocked in ("projects_dir", "exports_dir", "offline_mode"):
            upd.pop(blocked, None)
    for key in ("projects_dir", "exports_dir"):
        if key in upd:
            try:
                p = validate_output_dir(upd[key])
                p.mkdir(parents=True, exist_ok=True)
                upd[key] = str(p)
            except (SecurityError, OSError) as exc:
                raise HTTPException(400, f"{key}: {exc}")
    if "whisper_model" in upd and upd["whisper_model"] not in transcription.WHISPER_MODELS:
        raise HTTPException(400, "Unknown Whisper model")
    if "score_weights" in upd:
        w = {k: float(v) for k, v in upd["score_weights"].items() if k in config.DEFAULT_SETTINGS["score_weights"]}
        if sum(w.values()) <= 0:
            raise HTTPException(400, "At least one score weight must be positive")
        upd["score_weights"] = w
    if "duration_targets" in upd:
        t = sorted({float(x) for x in upd["duration_targets"] if 5 <= float(x) <= 900})
        if not t:
            raise HTTPException(400, "Provide at least one duration target between 5 and 900 seconds")
        upd["duration_targets"] = t
    if upd.get("offline_mode"):
        for p in db.query(AIProvider).filter(AIProvider.enabled == True, AIProvider.is_local == False).all():  # noqa: E712
            p.enabled = False
    s = config.save_settings(upd)
    if "whisper_device" in upd or "whisper_model" in upd:
        transcription.unload_models()
    return s


class DialogReq(BaseModel):
    kind: str = "file"  # file | folder | audio
    title: str = "Select"


_DIALOG = r"""
import sys, tkinter as tk
from tkinter import filedialog
root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)
kind = sys.argv[1]
if kind == 'folder':
    p = filedialog.askdirectory(title=sys.argv[2])
elif kind == 'audio':
    p = filedialog.askopenfilename(title=sys.argv[2], filetypes=[('Audio', '*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus'), ('All', '*.*')])
else:
    p = filedialog.askopenfilename(title=sys.argv[2], filetypes=[('Video', '*.mp4 *.mov *.mkv *.webm *.avi *.m4v *.wmv *.flv *.ts *.mts *.mpg'), ('Audio', '*.mp3 *.wav *.m4a *.flac'), ('All', '*.*')])
sys.stdout.write(p or '')
"""


@router.post("/api/system/dialog")
def native_dialog(body: DialogReq):
    """Open a native Windows file/folder picker on the local machine (the app only binds to localhost)."""
    if config.PUBLIC_CLOUD:
        raise HTTPException(403, "Desktop file dialogs are disabled on the public cloud — drag and drop or browse in your browser instead.")
    try:
        cp = subprocess.run([sys.executable, "-c", _DIALOG, body.kind, body.title[:80]], capture_output=True, text=True, timeout=600)
        return {"path": cp.stdout.strip() or None}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Native dialog unavailable: {exc}")


@router.post("/api/system/open-folder")
def open_folder(which: str = "exports"):
    if config.PUBLIC_CLOUD:
        raise HTTPException(403, "Opening desktop folders is disabled on the public cloud — click Download to save your exported MP4.")
    s = config.get_settings()
    target = {"exports": s["exports_dir"], "projects": s["projects_dir"], "data": str(config.HOME), "logs": str(config.LOG_DIR)}.get(which)
    if not target:
        raise HTTPException(400, "Unknown folder")
    Path(target).mkdir(parents=True, exist_ok=True)
    subprocess.Popen(["explorer", str(Path(target))])
    return {"ok": True}


@router.delete("/api/system/data")
def delete_local_data(confirm: str, include_exports: bool = False, include_models: bool = False, db: Session = Depends(get_db)):
    """Delete all local ClipForge data (projects, analysis, database records, secrets). Requires confirm=DELETE."""
    if config.PUBLIC_CLOUD:
        raise HTTPException(403, "Wiping server data is disabled on the shared public cloud instance.")
    if confirm != "DELETE":
        raise HTTPException(400, "Pass confirm=DELETE to proceed")
    for j in db.query(Job).filter(Job.status.in_(["queued", "running"])).all():
        manager.cancel(j.id)
    from ..services.live_stream import live_manager

    live_manager.clear_all()
    if include_exports:
        for e in db.query(ExportJob).all():
            if e.output_path:
                Path(e.output_path).unlink(missing_ok=True)
    from ..models import AudioAsset, Preset

    for model in (ExportJob, CandidateClip, Project, Job, AIProvider):
        db.query(model).delete()
    db.query(AudioAsset).filter(AudioAsset.origin == "user").delete()
    db.query(Preset).filter(Preset.builtin == False).delete()  # noqa: E712
    db.commit()
    pd = config.projects_dir()
    for child in pd.iterdir() if pd.exists() else []:
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
    shutil.rmtree(config.USER_AUDIO_DIR, ignore_errors=True)
    shutil.rmtree(config.TMP_DIR, ignore_errors=True)
    clear_secrets()
    if include_models:
        transcription.unload_models()
        shutil.rmtree(config.MODELS_DIR, ignore_errors=True)
    config.ensure_dirs()
    return {"deleted": True}
