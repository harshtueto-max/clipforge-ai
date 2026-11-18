"""Application configuration, paths and persistent user settings.

All application data lives under CLIPFORGE_HOME (default: %LOCALAPPDATA%\\ClipForgeAI).
User-facing settings are stored in settings.json and can be changed from the UI.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

APP_NAME = "ClipForge AI"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _default_home() -> Path:
    env = os.environ.get("CLIPFORGE_HOME")
    if env:
        return Path(env).expanduser().resolve()
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return (Path(base) / "ClipForgeAI").resolve()


HOME = _default_home()
DB_PATH = HOME / "clipforge.db"
SETTINGS_PATH = HOME / "settings.json"
MODELS_DIR = Path(os.environ["CLIPFORGE_MODELS_DIR"]).resolve() if os.environ.get("CLIPFORGE_MODELS_DIR") else HOME / "models"
WHISPER_DIR = MODELS_DIR / "whisper"
VISION_DIR = MODELS_DIR / "vision"
USER_AUDIO_DIR = HOME / "audio_library"
SECRETS_PATH = HOME / "secrets.bin"
LOG_DIR = HOME / "logs"
TMP_DIR = HOME / "tmp"
LIVE_DIR = HOME / "live_sessions"
BUILTIN_AUDIO_DIR = REPO_ROOT / "assets" / "audio"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

HOST = os.environ.get("CLIPFORGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("CLIPFORGE_PORT", "8765"))
PUBLIC_CLOUD = os.environ.get("CLIPFORGE_PUBLIC_CLOUD", "").lower() in ("1", "true", "yes")

DEFAULT_SETTINGS: dict[str, Any] = {
    "projects_dir": str(HOME / "projects"),
    "exports_dir": str(Path.home() / "Videos" / "ClipForge Exports"),
    "offline_mode": False,
    "whisper_model": "base",
    "whisper_device": "auto",  # auto | cuda | cpu
    "whisper_compute_type": "auto",
    "transcription_language": "auto",
    "analysis_quality": "balanced",  # fast | balanced | high
    "enable_diarization": True,
    "max_speakers": 4,
    "analysis_concurrency": 1,
    "render_concurrency": 1,
    "hardware_encoding": "auto",  # auto | off
    "proxy_mode": "auto",  # auto | always | never
    "copy_imports": True,
    "duration_targets": [30, 60],
    "duration_tolerance": 0.2,
    "max_clips_per_target": 8,
    "score_weights": {
        "hook": 20,
        "story": 20,
        "engagement": 15,
        "emotion": 15,
        "information": 10,
        "standalone": 10,
        "av_quality": 10,
    },
    "discovery_preferences": {
        "categories": [],  # empty = all
        "min_score": 0,
        "allow_alternates": False,
    },
    "default_preset": "podcast_pro",
    "default_aspect": "9:16",
    "telemetry": False,
}

_lock = threading.RLock()
_cache: dict[str, Any] | None = None


def ensure_dirs() -> None:
    for d in (HOME, MODELS_DIR, WHISPER_DIR, VISION_DIR, USER_AUDIO_DIR, LOG_DIR, TMP_DIR, LIVE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    s = get_settings()
    Path(s["projects_dir"]).mkdir(parents=True, exist_ok=True)
    try:
        Path(s["exports_dir"]).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def _merge(defaults: dict, current: dict) -> dict:
    out = dict(defaults)
    for k, v in current.items():
        if k in defaults and isinstance(defaults[k], dict) and isinstance(v, dict):
            out[k] = _merge(defaults[k], v)
        else:
            out[k] = v
    return out


def get_settings() -> dict[str, Any]:
    global _cache
    with _lock:
        if _cache is None:
            data: dict[str, Any] = {}
            if SETTINGS_PATH.exists():
                try:
                    data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    data = {}
            _cache = _merge(DEFAULT_SETTINGS, data)
        return json.loads(json.dumps(_cache))


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    global _cache
    with _lock:
        current = get_settings()
        merged = _merge(current, updates)
        HOME.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        os.replace(tmp, SETTINGS_PATH)
        _cache = merged
        return get_settings()


def reset_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def projects_dir() -> Path:
    return Path(get_settings()["projects_dir"])


def exports_dir() -> Path:
    return Path(get_settings()["exports_dir"])
