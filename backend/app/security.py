"""Security helpers: path validation, filename sanitization, URL validation, secret storage."""
from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import sys
import threading
import unicodedata
from ctypes import wintypes
from pathlib import Path
from urllib.parse import urlparse

from . import config

MEDIA_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".wmv", ".mpg", ".mpeg", ".ts", ".mts",
    ".m2ts", ".3gp", ".ogv", ".mxf",
}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class SecurityError(ValueError):
    pass


def sanitize_filename(name: str, max_len: int = 120, default: str = "file") -> str:
    name = unicodedata.normalize("NFKC", name or "")
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = default
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    if stem.upper() in _RESERVED:
        stem = f"_{stem}"
    ext = ext[:10]
    stem = stem[: max(1, max_len - len(ext) - 1)]
    return f"{stem}.{ext}" if ext else stem


def approved_roots() -> list[Path]:
    s = config.get_settings()
    roots = [config.HOME, Path(s["projects_dir"]), Path(s["exports_dir"]), config.BUILTIN_AUDIO_DIR]
    return [r.resolve() for r in roots]


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def ensure_approved(path: str | Path, extra_roots: list[Path] | None = None) -> Path:
    """Resolve path and make sure it lies within an approved application directory."""
    p = Path(path).resolve()
    roots = approved_roots() + [r.resolve() for r in (extra_roots or [])]
    if not any(is_within(p, r) for r in roots):
        raise SecurityError("Path is outside approved application directories")
    return p


def safe_join(root: Path, *parts: str) -> Path:
    root = root.resolve()
    p = root.joinpath(*parts).resolve()
    if not is_within(p, root):
        raise SecurityError("Directory traversal detected")
    return p


def validate_media_file(path: str | Path) -> Path:
    """Validate a user-selected local media file for read-only import."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        raise SecurityError("Please provide an absolute file path")
    p = p.resolve()
    if not p.is_file():
        raise SecurityError("File does not exist")
    if p.suffix.lower() not in MEDIA_EXTENSIONS | AUDIO_EXTENSIONS:
        raise SecurityError(f"Unsupported file type '{p.suffix}'")
    return p


def validate_output_dir(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        raise SecurityError("Output directory must be an absolute path")
    p = p.resolve()
    if p.exists() and not p.is_dir():
        raise SecurityError("Output path is not a directory")
    # Refuse system-critical locations
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")).resolve()
    if is_within(p, windir) or p == Path(p.anchor):
        raise SecurityError("Refusing to use a system directory")
    return p


_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"}
_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_CHANNEL_LIVE = re.compile(r"^/(?:@[A-Za-z0-9_.\-]{2,80}|channel/[A-Za-z0-9_\-]{10,40}|c/[A-Za-z0-9_.\-]{2,80})/live/?$")


def validate_youtube_url(url: str) -> str:
    url = (url or "").strip()
    if len(url) > 500:
        raise SecurityError("URL too long")
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise SecurityError("URL must start with http:// or https://")
    host = (u.hostname or "").lower()
    if host not in _YT_HOSTS:
        raise SecurityError("Only YouTube URLs (youtube.com / youtu.be) are supported")
    vid = None
    if host.endswith("youtu.be"):
        vid = u.path.strip("/").split("/")[0]
    elif u.path == "/watch":
        from urllib.parse import parse_qs

        vid = (parse_qs(u.query).get("v") or [None])[0]
    elif u.path.startswith(("/shorts/", "/live/", "/embed/")):
        vid = u.path.split("/")[2] if len(u.path.split("/")) > 2 else None
    if not vid or not _YT_ID.match(vid):
        raise SecurityError("Could not find a valid YouTube video id in the URL (playlists are not supported)")
    return f"https://www.youtube.com/watch?v={vid}"


def validate_youtube_live_url(url: str) -> str:
    """Validate a YouTube video, /live/<id>, or @handle/live URL for live stream capture."""
    raw = (url or "").strip()
    if len(raw) > 500:
        raise SecurityError("URL too long")
    u = urlparse(raw)
    if u.scheme in ("http", "https") and (u.hostname or "").lower() in _YT_HOSTS and _YT_CHANNEL_LIVE.match(u.path or ""):
        clean_path = u.path.rstrip("/")
        return f"https://www.youtube.com{clean_path}"
    return validate_youtube_url(raw)


# ---------------------------------------------------------------- secrets
class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DataBlob()
    entropy_bytes = b"ClipForgeAI-v1"
    ebuf = ctypes.create_string_buffer(entropy_bytes, len(entropy_bytes))
    entropy = _DataBlob(len(entropy_bytes), ctypes.cast(ebuf, ctypes.POINTER(ctypes.c_char)))
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(blob_in), None, ctypes.byref(entropy), None, None, 0x01, ctypes.byref(blob_out))
    if not ok:
        raise OSError("DPAPI operation failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _encrypt(data: bytes) -> bytes:
    if sys.platform == "win32":
        return b"DPAPI:" + _dpapi(data, True)
    return b"PLAIN:" + base64.b64encode(data)  # non-Windows fallback (development only)


def _decrypt(data: bytes) -> bytes:
    if data.startswith(b"DPAPI:"):
        return _dpapi(data[6:], False)
    if data.startswith(b"PLAIN:"):
        return base64.b64decode(data[6:])
    raise OSError("Unknown secret format")


_secret_lock = threading.Lock()


def _load_secrets() -> dict[str, str]:
    if not config.SECRETS_PATH.exists():
        return {}
    try:
        return json.loads(_decrypt(config.SECRETS_PATH.read_bytes()).decode("utf-8"))
    except Exception:
        return {}


def set_secret(key: str, value: str | None) -> None:
    with _secret_lock:
        data = _load_secrets()
        if value:
            data[key] = value
        else:
            data.pop(key, None)
        config.SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
        config.SECRETS_PATH.write_bytes(_encrypt(json.dumps(data).encode("utf-8")))


def get_secret(key: str) -> str | None:
    with _secret_lock:
        return _load_secrets().get(key)


def clear_secrets() -> None:
    with _secret_lock:
        if config.SECRETS_PATH.exists():
            config.SECRETS_PATH.unlink()
