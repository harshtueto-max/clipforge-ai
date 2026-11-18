"""FFmpeg / FFprobe integration: probing, thumbnails, waveform peaks, audio extraction, proxies."""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

import numpy as np

log = logging.getLogger("clipforge.media")

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0

BROWSER_VIDEO_CODECS = {"h264", "vp8", "vp9", "av1"}
BROWSER_AUDIO_CODECS = {"aac", "opus", "vorbis", "mp3"}
BROWSER_CONTAINERS = {".mp4", ".m4v", ".webm", ".mov"}


class MediaError(RuntimeError):
    pass


def ffmpeg_bin() -> str | None:
    return shutil.which("ffmpeg")


def ffprobe_bin() -> str | None:
    return shutil.which("ffprobe")


def require_ffmpeg() -> tuple[str, str]:
    f, p = ffmpeg_bin(), ffprobe_bin()
    if not f or not p:
        raise MediaError("FFmpeg/FFprobe not found on PATH. Run setup.bat or install FFmpeg (see README).")
    return f, p


def run(cmd: list[str], timeout: float | None = None, ctx=None) -> subprocess.CompletedProcess:
    log.debug("run: %s", " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
    if ctx is not None:
        ctx.register_process(proc)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise MediaError(f"Command timed out: {cmd[0]}")
    finally:
        if ctx is not None:
            ctx.unregister_process(proc)
    if ctx is not None:
        ctx.check_cancel()
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def _parse_rate(rate: str | None) -> float:
    if not rate or rate in ("0/0", "N/A"):
        return 0.0
    try:
        return float(Fraction(rate))
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path: str | Path) -> dict[str, Any]:
    _, ffprobe = require_ffmpeg()
    cp = run([ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], timeout=120)
    if cp.returncode != 0:
        msg = cp.stderr.decode("utf-8", "ignore").strip().splitlines()
        raise MediaError(f"FFprobe could not read the file: {msg[-1] if msg else 'unknown error'}")
    data = json.loads(cp.stdout.decode("utf-8", "ignore") or "{}")
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    v = next((s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(fmt.get("duration") or 0) or float((v or a or {}).get("duration") or 0)
    rotation = 0
    if v:
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rotation = int(sd["rotation"])
        rotation = int((v.get("tags") or {}).get("rotate", rotation))
    width, height = (int(v.get("width", 0)), int(v.get("height", 0))) if v else (0, 0)
    if abs(rotation) in (90, 270):
        width, height = height, width
    return {
        "duration": duration,
        "size_bytes": int(fmt.get("size") or 0),
        "format_name": fmt.get("format_name"),
        "bit_rate": int(fmt.get("bit_rate") or 0),
        "has_video": v is not None,
        "has_audio": a is not None,
        "width": width,
        "height": height,
        "rotation": rotation,
        "fps": _parse_rate(v.get("avg_frame_rate")) or _parse_rate(v.get("r_frame_rate")) if v else 0.0,
        "video_codec": v.get("codec_name") if v else None,
        "pix_fmt": v.get("pix_fmt") if v else None,
        "audio_codec": a.get("codec_name") if a else None,
        "audio_channels": int(a.get("channels", 0)) if a else 0,
        "audio_sample_rate": int(a.get("sample_rate", 0)) if a else 0,
        "stream_count": len(streams),
    }


def needs_proxy(path: Path, info: dict[str, Any]) -> bool:
    if not info.get("has_video"):
        return False
    if path.suffix.lower() not in BROWSER_CONTAINERS:
        return True
    if info.get("video_codec") not in BROWSER_VIDEO_CODECS:
        return True
    if info.get("has_audio") and info.get("audio_codec") not in BROWSER_AUDIO_CODECS:
        return True
    if info.get("pix_fmt") not in (None, "yuv420p", "yuvj420p"):
        return True
    return False


def thumbnail(src: str | Path, dst: str | Path, at: float = 1.0, width: int = 480) -> Path:
    ffmpeg, _ = require_ffmpeg()
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-y", "-v", "error", "-ss", f"{max(0.0, at):.3f}", "-i", str(src), "-frames:v", "1",
           "-vf", f"scale={width}:-2", "-q:v", "4", str(dst)]
    cp = run(cmd, timeout=60)
    if cp.returncode != 0 or not dst.exists():
        cmd[cmd.index("-ss") + 1] = "0"
        cp = run(cmd, timeout=60)
        if cp.returncode != 0 or not dst.exists():
            raise MediaError("Thumbnail generation failed: " + cp.stderr.decode("utf-8", "ignore")[-300:])
    return dst


def extract_audio(src: str | Path, dst: str | Path, sample_rate: int = 16000, ctx=None,
                  progress: Callable[[float], None] | None = None, duration: float = 0.0) -> Path:
    """Extract a mono 16 kHz PCM WAV analysis copy (the original file is untouched)."""
    ffmpeg, _ = require_ffmpeg()
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".part.wav")
    cmd = [ffmpeg, "-y", "-v", "error", "-nostdin", "-i", str(src), "-vn", "-ac", "1", "-ar", str(sample_rate),
           "-c:a", "pcm_s16le", "-progress", "pipe:1", str(tmp)]
    run_with_progress(cmd, duration, progress, ctx)
    tmp.replace(dst)
    return dst


def run_with_progress(cmd: list[str], duration: float, progress: Callable[[float], None] | None, ctx=None) -> str:
    """Run an ffmpeg command that has `-progress pipe:1`, reporting fractional progress. Returns stderr tail."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW,
                            text=True, encoding="utf-8", errors="ignore")
    if ctx is not None:
        ctx.register_process(proc)
    err_lines: list[str] = []
    import threading

    def _drain():
        assert proc.stderr is not None
        for line in proc.stderr:
            err_lines.append(line)
            if len(err_lines) > 200:
                del err_lines[:100]

    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    us = int(line.split("=", 1)[1])
                except ValueError:
                    continue
                if duration > 0 and progress:
                    progress(min(0.999, (us / 1_000_000) / duration))
            if ctx is not None and ctx.cancelled:
                proc.kill()
                break
        proc.wait()
    finally:
        t.join(timeout=2)
        if ctx is not None:
            ctx.unregister_process(proc)
    if ctx is not None:
        ctx.check_cancel()
    if proc.returncode != 0:
        tail = "".join(err_lines[-15:]).strip()
        raise MediaError(f"FFmpeg failed (exit {proc.returncode}): {tail[-1200:]}")
    return "".join(err_lines[-15:])


def load_wav(path: str | Path) -> tuple[np.ndarray, int]:
    import soundfile as sf

    data, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data, sr


def waveform_peaks(wav_path: str | Path, dst: str | Path, per_second: int = 50) -> Path:
    """Compute peak envelope (uint8, `per_second` values/sec) and store as compact binary + JSON header."""
    data, sr = load_wav(wav_path)
    hop = max(1, sr // per_second)
    n = len(data) // hop
    if n == 0:
        peaks = np.zeros(1, dtype=np.uint8)
    else:
        frames = np.abs(data[: n * hop]).reshape(n, hop)
        p = frames.max(axis=1)
        mx = float(np.percentile(p, 99.5)) or 1.0
        peaks = np.clip(p / mx * 255.0, 0, 255).astype(np.uint8)
    dst = Path(dst)
    dst.write_bytes(peaks.tobytes())
    dst.with_suffix(".json").write_text(json.dumps({"per_second": per_second, "count": int(len(peaks))}))
    return dst


def read_peaks(path: str | Path, start: float, end: float, points: int) -> list[float]:
    path = Path(path)
    meta = json.loads(path.with_suffix(".json").read_text())
    ps = meta["per_second"]
    arr = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    a, b = int(max(0, start) * ps), int(max(0, end) * ps)
    seg = arr[a:max(a + 1, b)]
    if len(seg) == 0:
        return [0.0] * points
    points = max(1, min(points, 4000))
    idx = np.linspace(0, len(seg), points + 1).astype(int)
    out = []
    for i in range(points):
        chunk = seg[idx[i]:max(idx[i] + 1, idx[i + 1])]
        out.append(round(float(chunk.max()) / 255.0, 3) if len(chunk) else 0.0)
    return out


_ENCODER_CACHE: dict[str, bool] = {}


def encoder_works(name: str) -> bool:
    """Test whether an encoder actually works on this machine (not just compiled in)."""
    if name in _ENCODER_CACHE:
        return _ENCODER_CACHE[name]
    ffmpeg = ffmpeg_bin()
    ok = False
    if ffmpeg:
        cmd = [ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.2", "-frames:v", "3",
               "-c:v", name, "-f", "null", "-"]
        try:
            cp = run(cmd, timeout=30)
            ok = cp.returncode == 0
        except Exception:  # noqa: BLE001
            ok = False
    _ENCODER_CACHE[name] = ok
    return ok


def make_proxy(src: str | Path, dst: str | Path, duration: float, ctx=None, progress=None) -> Path:
    """Create a 720p H.264/AAC proxy that every browser can play, for editor preview only."""
    ffmpeg, _ = require_ffmpeg()
    dst = Path(dst)
    tmp = dst.with_name(dst.stem + ".part.mp4")
    venc = ["-c:v", "h264_nvenc", "-preset", "p2", "-cq", "28"] if encoder_works("h264_nvenc") else \
        ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26"]
    cmd = [ffmpeg, "-y", "-v", "error", "-nostdin", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?",
           "-vf", "scale=-2:'min(720,ih)',format=yuv420p", *venc, "-g", "48", "-c:a", "aac", "-b:a", "128k",
           "-movflags", "+faststart", "-progress", "pipe:1", str(tmp)]
    run_with_progress(cmd, duration, progress, ctx)
    tmp.replace(dst)
    return dst


def ts(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}" if h else f"{m:02d}:{s:06.3f}"


def parse_ts(value: str | float | int) -> float:
    """Parse '1:02:03.5', '02:03', '123.4' into seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    v = value.strip()
    if not re.fullmatch(r"\d+(:\d{1,2}){0,2}(\.\d+)?", v):
        raise ValueError(f"Invalid timestamp: {value!r}")
    parts = [float(p) for p in v.split(":")]
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total
