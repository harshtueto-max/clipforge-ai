"""Live YouTube stream DVR capture, instant flash clipping, and rolling AI highlight radar.

Architecture (100% local media & AI processing):
- Resolves ongoing YouTube Live HLS/DASH streams (or authorized VODs / local test feeds) via `yt-dlp`.
- Spawns `FFmpeg` in the background writing 2-second HLS `.ts` segments into `%LOCALAPPDATA%\\ClipForgeAI\\live_sessions\\<id>\\hls`
  with `-hls_list_size` + `delete_segments` maintaining a rolling 30-minute DVR ring buffer on disk (~0% video CPU when H.264).
- Tracks monotonic stream timestamps across sliding HLS windows so `Clip Last 30s/45s/60s/90s` and `In -> Out` markers stay
  frame-accurate even as older `.ts` segments are automatically purged.
- Runs an optional rolling AI highlight radar in the background that transcribes new live chunks locally (Hinglish / Hindi /
  English), updates a live scrolling transcript, and automatically captures high-scoring hooks & laughter/excitement moments.
- Materializes every captured clip into a standalone local MP4 + full ClipForge `Project` + `CandidateClip` + 9:16 face-tracked
  auto-edit + word-timed captions so 1-click NVENC Export and the full Clip Editor work identically to standard projects.
"""
from __future__ import annotations

import json
import logging
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

from .. import config
from ..db import session_scope
from ..events import hub
from ..models import CandidateClip, Job, Project, Scene, SourceMedia, Transcript, new_id
from ..security import SecurityError, safe_join, sanitize_filename, validate_youtube_live_url
from . import audio_analysis, autoedit, diarization, discovery, media, pipeline, segmentation, storage, transcription, vision

log = logging.getLogger("clipforge.live")

CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0
SEG_DURATION = 2.0
CLIP_HANDLE_PAD = 6.0
AI_SCAN_STEP_S = 28.0
AI_WINDOW_S = 72.0
AI_MIN_SCORE = 48.0
_SEG_RE = re.compile(r"#EXTINF:([0-9.]+),[^\r\n]*\r?\n(seg_(\d+)\.ts)")


def _fmt_mmss(sec: float) -> str:
    sec = max(0, int(round(sec)))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _pick_installed_whisper(preferred: str | None = None) -> str | None:
    if preferred and transcription.is_installed(preferred):
        return preferred
    s_model = config.get_settings().get("whisper_model")
    if s_model and transcription.is_installed(s_model):
        return s_model
    for name in ("large-v3-turbo", "small", "base", "medium", "large-v3", "tiny"):
        if transcription.is_installed(name):
            return name
    return None


def resolve_youtube_live(url: str) -> dict[str, Any]:
    """Extract playable stream URL(s), headers, and metadata from YouTube without bypassing access controls."""
    if config.get_settings().get("offline_mode"):
        raise RuntimeError("Global Offline Mode is enabled — disable Offline Mode to connect to a YouTube livestream.")
    clean_url = validate_youtube_live_url(url)
    import yt_dlp

    fmt = (
        "b[protocol^=m3u8][height<=1080][vcodec^=avc1]/"
        "b[protocol^=m3u8][height<=1080]/"
        "b[height<=1080][vcodec^=avc1]/"
        "bv*[height<=1080][vcodec^=avc1]+ba/"
        "bv*[height<=1080]+ba/b"
    )
    opts = {
        "format": fmt,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "ffmpeg_location": str(Path(media.ffmpeg_bin() or "ffmpeg").parent) if media.ffmpeg_bin() else None,
    }
    try:
        with yt_dlp.YoutubeDL({k: v for k, v in opts.items() if v is not None}) as ydl:
            info = ydl.extract_info(clean_url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        msg = str(exc)
        if "Sign in" in msg or "login" in msg.lower() or "age" in msg.lower() or "members-only" in msg.lower():
            raise RuntimeError(
                "This stream requires sign-in, membership, or age verification. ClipForge does not bypass access controls."
            ) from exc
        if "DRM" in msg:
            raise RuntimeError("This stream is DRM-protected and cannot be captured.") from exc
        if "will begin in" in msg.lower() or "premiere will begin" in msg.lower():
            raise RuntimeError("This livestream has not started yet (upcoming scheduled stream).") from exc
        raise RuntimeError(f"Could not connect to YouTube stream: {msg[-350:]}") from exc

    if not info:
        raise RuntimeError("YouTube returned no stream metadata.")
    live_status = info.get("live_status") or ""
    if live_status == "is_upcoming":
        raise RuntimeError("This livestream is scheduled/upcoming and has not started broadcasting yet.")

    inputs: list[dict[str, Any]] = []
    req_fmts = info.get("requested_formats")
    if req_fmts:
        for rf in req_fmts:
            if rf.get("url"):
                inputs.append({
                    "url": rf["url"],
                    "headers": rf.get("http_headers") or info.get("http_headers") or {},
                    "vcodec": rf.get("vcodec") or "none",
                    "acodec": rf.get("acodec") or "none",
                })
    elif info.get("url"):
        inputs.append({
            "url": info["url"],
            "headers": info.get("http_headers") or {},
            "vcodec": info.get("vcodec") or "h264",
            "acodec": info.get("acodec") or "aac",
        })
    if not inputs:
        raise RuntimeError("No playable video stream URL was found for this YouTube link.")

    return {
        "video_id": info.get("id") or "",
        "canonical_url": f"https://www.youtube.com/watch?v={info['id']}" if info.get("id") else clean_url,
        "title": (info.get("title") or "YouTube Live Stream").strip(),
        "channel": (info.get("uploader") or info.get("channel") or "YouTube").strip(),
        "is_live": bool(info.get("is_live") or live_status == "is_live"),
        "live_status": live_status or ("is_live" if info.get("is_live") else "vod"),
        "thumbnail": info.get("thumbnail"),
        "inputs": inputs,
    }


def _fast_vision_for_clip(mp4_path: Path, sentences: list[dict[str, Any]], sample_fps: float = 1.5) -> tuple[dict[str, Any], list[dict[str, float]]]:
    """Fast in-RAM 480p frame sampler + YuNet/Haar face tracker (~0.35s for a 45s clip, zero proxy file encode)."""
    import cv2

    cap = cv2.VideoCapture(str(mp4_path))
    if not cap.isOpened():
        return {"sample_fps": sample_fps, "width": 480, "height": 270, "detector": "none", "samples": [], "tracks": [], "speaker_positions": {}, "scene_stats": []}, [{"s": 0.0, "e": 1.0}]
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    dur = total / fps if total > 0 else 0.0
    det_w = 480
    det_h = max(180, int(round(det_w * src_h / max(1, src_w))))
    step = max(1, int(round(fps / sample_fps)))
    det = vision.FaceDetector(det_w, det_h)
    samples: list[dict[str, Any]] = []
    scene_cuts: list[float] = [0.0]
    prev_gray = None
    i = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if i % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            small = cv2.resize(frame, (det_w, det_h), interpolation=cv2.INTER_AREA)
            t = i / fps
            faces = det.detect(small)
            gray = cv2.cvtColor(cv2.resize(small, (160, max(60, int(160 * det_h / det_w)))), cv2.COLOR_BGR2GRAY)
            sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            bright = float(gray.mean())
            motion = 0.0
            subject = [0.5, 0.45]
            if prev_gray is not None and prev_gray.shape == gray.shape:
                diff = cv2.absdiff(gray, prev_gray).astype(np.float32)
                motion = float(diff.mean())
                if motion > 36.0 and (t - scene_cuts[-1]) >= 1.5:
                    scene_cuts.append(round(t, 3))
                if diff.sum() > 0 and motion > 2.0:
                    ys, xs = np.indices(diff.shape)
                    wsum = diff.sum()
                    subject = [float((xs * diff).sum() / wsum / diff.shape[1]), float((ys * diff).sum() / wsum / diff.shape[0])]
            prev_gray = gray
            samples.append({
                "t": round(t, 3),
                "faces": [[round(v, 4) for v in f] for f in faces],
                "motion": round(motion, 2),
                "sharp": round(sharp, 1),
                "bright": round(bright, 1),
                "subject": [round(subject[0], 3), round(subject[1], 3)],
            })
        i += 1
    cap.release()
    end_t = round(max(dur, samples[-1]["t"] + 0.5 if samples else 1.0), 3)
    scenes: list[dict[str, float]] = []
    for a, b in zip(scene_cuts, scene_cuts[1:] + [end_t]):
        if b > a + 0.2:
            scenes.append({"s": round(a, 3), "e": round(b, 3)})
    if not scenes:
        scenes = [{"s": 0.0, "e": end_t}]
    tracks = vision.track_faces(samples)
    spk_pos = {str(k): v for k, v in vision.speaker_positions(samples, sentences).items()}
    vis = {
        "sample_fps": sample_fps,
        "width": det_w,
        "height": det_h,
        "quality": "live_fast",
        "detector": det.kind,
        "samples": samples,
        "tracks": tracks,
        "speaker_positions": spk_pos,
        "scene_stats": vision.summarize(samples, scenes),
    }
    return vis, scenes


def _concat_segments_to_mp4(seg_paths: list[Path], dst_mp4: Path, work_dir: Path) -> None:
    """Concatenate MPEG-TS DVR segments into an MP4 container (`-c copy` first, re-encode fallback if needed)."""
    ffmpeg, _ = media.require_ffmpeg()
    dst_mp4.parent.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    list_file = work_dir / f"concat_{new_id()}.txt"
    try:
        lines = []
        for p in seg_paths:
            escaped = str(p.resolve()).replace("'", "'\\''")
            lines.append(f"file '{escaped}'")
        list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp_out = dst_mp4.with_suffix(".part.mp4")
        cmd = [
            ffmpeg, "-y", "-v", "error", "-nostdin",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", "-bsf:a", "aac_adtstoasc",
            "-movflags", "+faststart", str(tmp_out),
        ]
        cp = media.run(cmd, timeout=90)
        if cp.returncode != 0 or not tmp_out.exists() or tmp_out.stat().st_size < 1024:
            cmd_re = [
                ffmpeg, "-y", "-v", "error", "-nostdin",
                "-f", "concat", "-safe", "0", "-i", str(list_file),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(tmp_out),
            ]
            cp2 = media.run(cmd_re, timeout=180)
            if cp2.returncode != 0 or not tmp_out.exists():
                err = cp2.stderr.decode("utf-8", "ignore")[-300:]
                raise RuntimeError(f"Could not assemble live clip MP4: {err}")
        tmp_out.replace(dst_mp4)
    finally:
        list_file.unlink(missing_ok=True)


class LiveSession:
    """Manages one ongoing live stream DVR session, rolling AI highlight radar, and clip capture worker."""

    def __init__(
        self,
        session_id: str,
        folder: Path,
        meta: dict[str, Any],
        *,
        language: str = "hinglish",
        preset_id: str = "podcast_pro",
        aspect: str = "9:16",
        auto_highlight: bool = True,
        dvr_minutes: int = 30,
        target_duration: float = 45.0,
        pace_realtime: bool | None = None,
    ):
        self.id = session_id
        self.folder = folder
        self.hls_dir = folder / "hls"
        self.work_dir = folder / "work"
        self.state_file = folder / "session.json"
        self.hls_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)

        self.video_id: str = meta.get("video_id", "")
        self.source_url: str = meta["canonical_url"]
        self.title: str = meta["title"]
        self.channel: str = meta.get("channel", "YouTube")
        self.is_live_broadcast: bool = bool(meta.get("is_live", True))
        self.thumbnail_url: str | None = meta.get("thumbnail")
        self._inputs: list[dict[str, Any]] = meta.get("inputs", [])
        self._local_source: str | None = meta.get("local_source")
        self._pace_realtime = (not self.is_live_broadcast) if pace_realtime is None else pace_realtime

        self.language = language or "hinglish"
        self.preset_id = preset_id or config.get_settings().get("default_preset", "podcast_pro")
        self.aspect = aspect or "9:16"
        self.auto_highlight = bool(auto_highlight)
        self.dvr_minutes = int(dvr_minutes)
        self.target_duration = float(target_duration)

        self.status = "connecting"  # connecting | live | ended | stopped | error
        self.error: str | None = None
        self.created_at = time.time()
        self.ai_scanning = False
        self.last_ai_scan_pts = 0.0
        self.last_ai_scan_at: float | None = None

        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self._stop_evt = threading.Event()
        self._segments: dict[int, dict[str, Any]] = {}
        self._next_pts = 0.0
        self.dvr_start = 0.0
        self.dvr_end = 0.0

        self.clip_ids: list[str] = []
        self._auto_clipped_ranges: list[tuple[float, float]] = []
        self.transcript_tail: list[dict[str, Any]] = []
        self.pending_clips: dict[str, dict[str, Any]] = {}

        self._clip_q: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._monitor_thread: threading.Thread | None = None
        self._clip_thread: threading.Thread | None = None
        self._stderr_tail: list[str] = []

    def start(self) -> None:
        cmd = self._build_ffmpeg_cmd()
        log.info("Starting live session %s (%s): %s", self.id, self.title, " ".join(cmd[:10]))
        self._proc = subprocess.Popen(
            cmd,
            cwd=str(self.hls_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
        )
        threading.Thread(target=self._drain_stderr, daemon=True, name=f"live-err-{self.id[:6]}").start()
        self._clip_thread = threading.Thread(target=self._clip_worker, daemon=True, name=f"live-clip-{self.id[:6]}")
        self._clip_thread.start()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True, name=f"live-mon-{self.id[:6]}")
        self._monitor_thread.start()
        self._persist()

    def _drain_stderr(self) -> None:
        proc = self._proc
        if not proc or not proc.stderr:
            return
        try:
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", "ignore").strip()
                if line:
                    with self._lock:
                        self._stderr_tail.append(line)
                        if len(self._stderr_tail) > 25:
                            self._stderr_tail = self._stderr_tail[-25:]
        except Exception:  # noqa: BLE001
            pass

    def _build_ffmpeg_cmd(self) -> list[str]:
        ffmpeg, _ = media.require_ffmpeg()
        list_size = max(15, int(round(self.dvr_minutes * 60.0 / SEG_DURATION)))
        seg_tmpl = "seg_%06d.ts"
        m3u8 = "live.m3u8"

        cmd = [ffmpeg, "-y", "-nostdin", "-loglevel", "warning"]
        if self._pace_realtime:
            cmd.append("-re")

        if self._local_source:
            cmd += ["-i", str(Path(self._local_source).resolve())]
            vcodec = "h264"
            two_inputs = False
        else:
            two_inputs = len(self._inputs) >= 2
            vcodec = (self._inputs[0].get("vcodec") or "").lower()
            for inp in self._inputs[:2]:
                url = inp["url"]
                headers = inp.get("headers") or {}
                if url.startswith(("http://", "https://")):
                    if headers:
                        hdr_str = "".join(f"{k}: {v}\r\n" for k, v in headers.items() if k and v)
                        if hdr_str:
                            cmd += ["-headers", hdr_str]
                    cmd += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5", "-rw_timeout", "15000000"]
                cmd += ["-i", url]

        if two_inputs:
            cmd += ["-map", "0:v:0", "-map", "1:a:0"]
        else:
            cmd += ["-map", "0:v:0", "-map", "0:a:0?"]

        if vcodec.startswith(("avc", "h264")):
            cmd += ["-c:v", "copy"]
        else:
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-g", "60", "-sc_threshold", "0"]

        cmd += [
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
            "-f", "hls",
            "-hls_time", "2",
            "-hls_list_size", str(list_size),
            "-hls_delete_threshold", "6",
            "-hls_flags", "delete_segments+independent_segments+temp_file",
            "-hls_segment_filename", seg_tmpl,
            m3u8,
        ]
        return cmd

    def sync_playlist(self) -> None:
        m3u8 = self.hls_dir / "live.m3u8"
        if not m3u8.exists():
            return
        try:
            txt = m3u8.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return
        matches = _SEG_RE.findall(txt)
        if not matches:
            return
        changed = False
        with self._lock:
            for dur_s, fname, idx_s in matches:
                idx = int(idx_s)
                if idx not in self._segments:
                    dur = max(0.2, float(dur_s))
                    s = self._next_pts
                    e = round(s + dur, 3)
                    self._next_pts = e
                    self._segments[idx] = {"idx": idx, "file": fname, "dur": dur, "s": round(s, 3), "e": e}
                    changed = True
            # Prune segments deleted from disk by FFmpeg's rolling DVR window
            stale = [idx for idx, seg in self._segments.items() if not (self.hls_dir / seg["file"]).exists()]
            for idx in stale:
                self._segments.pop(idx, None)
                changed = True
            if self._segments:
                ordered = sorted(self._segments.values(), key=lambda x: x["idx"])
                self.dvr_start = ordered[0]["s"]
                self.dvr_end = ordered[-1]["e"]
                if self.status == "connecting" and len(ordered) >= 2:
                    self.status = "live"
                    changed = True
        if changed:
            self._persist()
            hub.publish("live_session", self.summary_dict())

    def _monitor_loop(self) -> None:
        last_ai_attempt = 0.0
        while not self._stop_evt.is_set():
            self.sync_playlist()
            proc = self._proc
            if proc is not None and proc.poll() is not None:
                self.sync_playlist()
                with self._lock:
                    if self._stop_evt.is_set() or self.status == "stopped":
                        self.status = "stopped"
                    elif self._segments:
                        self.status = "ended"
                    else:
                        self.status = "error"
                        tail = " | ".join(self._stderr_tail[-3:])
                        self.error = tail or f"FFmpeg stream capture exited with code {proc.returncode}"
                self._persist()
                hub.publish("live_session", self.summary_dict())
                break

            now = time.time()
            if (
                self.auto_highlight
                and not self.ai_scanning
                and self._clip_q.empty()
                and (self.dvr_end - self.last_ai_scan_pts) >= AI_SCAN_STEP_S
                and (self.dvr_end - self.dvr_start) >= 26.0
                and (now - last_ai_attempt) >= 12.0
            ):
                last_ai_attempt = now
                self._run_rolling_ai_scan()

            self._stop_evt.wait(1.0)

    def _segments_for_range(self, win_s: float, win_e: float) -> list[dict[str, Any]]:
        with self._lock:
            ordered = sorted(self._segments.values(), key=lambda x: x["idx"])
            chosen = [
                dict(seg)
                for seg in ordered
                if seg["e"] > win_s and seg["s"] < win_e and (self.hls_dir / seg["file"]).exists()
            ]
        return chosen

    def _any_render_busy(self) -> bool:
        try:
            with session_scope() as s:
                return s.query(Job).filter(Job.kind == "render", Job.status == "running").count() > 0
        except Exception:  # noqa: BLE001
            return False

    def _run_rolling_ai_scan(self) -> None:
        model_name = _pick_installed_whisper()
        if not model_name or self._any_render_busy():
            return
        with self._lock:
            scan_e = self.dvr_end
            scan_s = max(self.dvr_start, scan_e - AI_WINDOW_S)
            new_from = max(scan_s, self.last_ai_scan_pts)
        segs = self._segments_for_range(scan_s, scan_e)
        if len(segs) < 6:
            return

        self.ai_scanning = True
        hub.publish("live_session", self.summary_dict())
        tmp_mp4 = self.work_dir / f"aiscan_{new_id()}.mp4"
        tmp_wav = self.work_dir / f"aiscan_{new_id()}.wav"
        try:
            seg_paths = [self.hls_dir / s["file"] for s in segs]
            seg0_s = segs[0]["s"]
            _concat_segments_to_mp4(seg_paths, tmp_mp4, self.work_dir)
            info = media.probe(tmp_mp4)
            if not info.get("has_audio") or info["duration"] < 10.0:
                self.last_ai_scan_pts = scan_e
                return
            media.extract_audio(tmp_mp4, tmp_wav, duration=info["duration"])
            s_cfg = config.get_settings()
            lang_mode = self.language if self.language != "en" else "en"
            words, _ = transcription.transcribe_slice(
                tmp_wav, 0.0, info["duration"],
                mode="en" if self.language in ("en", "en_translate") else ("hi" if self.language == "hi" else "hinglish"),
                model_name=model_name,
                device_pref=s_cfg.get("whisper_device", "auto"),
            )
            self.last_ai_scan_pts = scan_e
            self.last_ai_scan_at = time.time()
            if not words:
                return

            sents = segmentation.build_sentences(words)
            # Append newly transcribed sentences into rolling live transcript tail (stream coordinates)
            with self._lock:
                existing_ends = [row["e"] for row in self.transcript_tail]
                cutoff = max(existing_ends) if existing_ends else (new_from - 1.0)
                for st in sents:
                    abs_s = round(seg0_s + st["s"], 2)
                    abs_e = round(seg0_s + st["e"], 2)
                    if abs_e > cutoff + 0.8 and st["text"].strip():
                        self.transcript_tail.append({"s": abs_s, "e": abs_e, "text": st["text"].strip()})
                if len(self.transcript_tail) > 60:
                    self.transcript_tail = self.transcript_tail[-60:]

            # Score rolling window for standout highlights
            audio_data, sr = media.load_wav(tmp_wav)
            au = audio_analysis.analyze(audio_data, sr, words)
            frames = au.pop("_frames", None)
            del audio_data
            b = discovery.prepare(discovery.Bundle(
                duration=info["duration"],
                words=words,
                sentences=sents,
                audio_frames=frames,
                vad=au.get("vad", []),
                laughter=au.get("laughter", []),
                has_video=bool(info.get("has_video", True)),
            ))
            tgt = min(max(20.0, self.target_duration), max(20.0, info["duration"] - 4.0))
            cands = discovery.discover(b, [tgt], 0.35, s_cfg["score_weights"], max_per_target=2, preferences={"min_score": AI_MIN_SCORE})
            for cand in cands:
                if cand["score"] < AI_MIN_SCORE:
                    continue
                abs_cs = seg0_s + cand["start"]
                abs_ce = seg0_s + cand["end"]
                # Avoid clipping right against the unfinished live edge (leave 1.5s post-roll) or duplicating recent auto-clips
                if abs_ce > scan_e - 1.0:
                    continue
                with self._lock:
                    overlap = any(min(abs_ce, b_e) - max(abs_cs, b_s) > 10.0 for b_s, b_e in self._auto_clipped_ranges)
                    if overlap:
                        continue
                    self._auto_clipped_ranges.append((abs_cs, abs_ce))
                self.enqueue_clip(start_time=abs_cs, end_time=abs_ce, source="auto_ai", title=cand.get("title"))
                break
        except Exception as exc:  # noqa: BLE001
            log.warning("Live rolling AI scan skipped (%s): %s", self.id, exc)
        finally:
            tmp_mp4.unlink(missing_ok=True)
            tmp_wav.unlink(missing_ok=True)
            self.ai_scanning = False
            self._persist()
            hub.publish("live_session", self.summary_dict())

    def enqueue_clip(
        self,
        *,
        start_time: float,
        end_time: float,
        source: str = "manual",
        title: str | None = None,
        wait: bool = False,
    ) -> dict[str, Any]:
        self.sync_playlist()
        with self._lock:
            if not self._segments:
                raise RuntimeError("Live DVR buffer has no segments yet — wait ~4 seconds for buffering.")
            s = max(self.dvr_start, float(start_time))
            e = min(self.dvr_end, float(end_time))
            if e - s < 3.0:
                # Expand slightly within available DVR window
                s = max(self.dvr_start, e - max(5.0, end_time - start_time))
            if e - s < 2.5:
                raise RuntimeError("Not enough buffered video yet for that range — wait a few seconds and clip again.")
            task_id = new_id()
            task = {
                "task_id": task_id,
                "start_time": round(s, 2),
                "end_time": round(e, 2),
                "source": source,
                "title": title,
                "status": "processing",
                "message": f"Capturing {_fmt_mmss(s)}–{_fmt_mmss(e)}…",
                "created_at": time.time(),
            }
            self.pending_clips[task_id] = task
        hub.publish("live_clip_status", {"session_id": self.id, **task})
        done_evt = threading.Event() if wait else None
        out_holder: dict[str, Any] = {}
        self._clip_q.put({"task": task, "done_evt": done_evt, "out": out_holder})
        if done_evt is not None:
            done_evt.wait(timeout=180)
            if "error" in out_holder:
                raise RuntimeError(out_holder["error"])
            return out_holder.get("result", task)
        return task

    def _clip_worker(self) -> None:
        while True:
            item = self._clip_q.get()
            if item is None:
                break
            task = item["task"]
            tid = task["task_id"]
            try:
                res = self._materialize_clip(
                    req_s=task["start_time"],
                    req_e=task["end_time"],
                    source=task["source"],
                    custom_title=task.get("title"),
                    task_id=tid,
                )
                item["out"]["result"] = res
            except Exception as exc:  # noqa: BLE001
                log.exception("Live clip capture failed (%s)", tid)
                item["out"]["error"] = str(exc)
                hub.publish("live_clip_status", {
                    "session_id": self.id, "task_id": tid, "status": "failed", "error": str(exc),
                })
            finally:
                with self._lock:
                    self.pending_clips.pop(tid, None)
                self._persist()
                if item["done_evt"] is not None:
                    item["done_evt"].set()
                self._clip_q.task_done()

    def _update_task(self, tid: str, message: str) -> None:
        with self._lock:
            if tid in self.pending_clips:
                self.pending_clips[tid]["message"] = message
                payload = {"session_id": self.id, **self.pending_clips[tid]}
            else:
                return
        hub.publish("live_clip_status", payload)

    def _materialize_clip(
        self,
        *,
        req_s: float,
        req_e: float,
        source: str,
        custom_title: str | None,
        task_id: str,
    ) -> dict[str, Any]:
        win_s = max(self.dvr_start, req_s - CLIP_HANDLE_PAD)
        win_e = min(self.dvr_end, req_e + CLIP_HANDLE_PAD)
        segs = self._segments_for_range(win_s, win_e)
        if not segs:
            raise RuntimeError("Requested DVR segments expired from the 30-minute rolling buffer.")

        seg0_s = segs[0]["s"]
        pid = new_id()
        p_folder = storage.project_folder(pid)
        storage.ensure_layout(p_folder)
        art = storage.Artifacts(p_folder)
        mp4_path = p_folder / "media" / "live_capture.mp4"

        self._update_task(task_id, "Remuxing DVR segments (lossless)…")
        _concat_segments_to_mp4([self.hls_dir / s["file"] for s in segs], mp4_path, self.work_dir)
        info = media.probe(mp4_path)
        dur = float(info["duration"] or 0.0)
        if dur <= 0.5:
            raise RuntimeError("Captured segment duration was empty.")

        local_s = max(0.0, min(dur - 1.0, req_s - seg0_s))
        local_e = max(local_s + 1.0, min(dur, req_e - seg0_s))
        target_dur = round(max(10.0, local_e - local_s), 1)

        thumb = None
        if info["has_video"]:
            try:
                thumb = media.thumbnail(mp4_path, p_folder / "thumbs" / "project.jpg", at=min(dur * 0.5, local_s + 1.5))
            except Exception:  # noqa: BLE001
                thumb = None

        words: list[dict[str, Any]] = []
        used_model = "none"
        au = {"vad": [], "laughter": [], "excitement": [], "long_pauses": [], "speech_ratio": 0.0}
        frames = None
        if info["has_audio"]:
            self._update_task(task_id, f"Extracting audio & transcribing ({self.language})…")
            media.extract_audio(mp4_path, art.wav, duration=dur)
            media.waveform_peaks(art.wav, art.waveform)
            model_name = _pick_installed_whisper()
            s_cfg = config.get_settings()
            if model_name:
                cap_mode = "en" if self.language in ("en", "en_translate") else ("hi" if self.language == "hi" else "hinglish")
                try:
                    words, used_model = transcription.transcribe_slice(
                        art.wav, 0.0, dur,
                        mode=cap_mode,
                        model_name=model_name,
                        device_pref=s_cfg.get("whisper_device", "auto"),
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("Live clip transcription fallback (%s)", exc)
            audio_data, sr = media.load_wav(art.wav)
            au = audio_analysis.analyze(audio_data, sr, words)
            frames = au.pop("_frames", None)
            del audio_data
            if frames is not None:
                np.savez_compressed(art.audio_frames, **frames)
            storage.write_json(art.audio, au)

        sents = segmentation.build_sentences(words)
        dia = diarization._single(words, sents, "live")
        tr_doc = {
            "language": "en" if self.language in ("en", "en_translate") else "hi",
            "language_mode": self.language,
            "language_probability": 1.0,
            "model": used_model,
            "device": config.get_settings().get("whisper_device", "auto"),
            "duration": dur,
            "words": words,
            "sentences": sents,
        }
        storage.write_json(art.transcript, tr_doc)
        storage.write_json(art.diarization, dia)

        if info["has_video"]:
            self._update_task(task_id, "Tracking faces & framing 9:16…")
            vis, scenes = _fast_vision_for_clip(mp4_path, sents)
        else:
            vis = {"samples": [], "tracks": [], "speaker_positions": {}, "scene_stats": [], "quality": "live_fast"}
            scenes = [{"s": 0.0, "e": dur}]
        storage.write_json(art.vision, vis)
        storage.write_json(art.scenes, scenes)

        # Create DB rows so load_bundle & create_auto_edit work identically to full projects
        label_window = f"{_fmt_mmss(req_s)}–{_fmt_mmss(req_e)}"
        proj_name = f"[Live] {self.title[:110]} ({label_window})"
        with session_scope() as s:
            p = Project(
                id=pid,
                name=proj_name,
                folder=str(p_folder),
                status="analyzed",
                thumbnail=str(thumb) if thumb else None,
                options={
                    "is_live_clip": True,
                    "live_session_id": self.id,
                    "live_stream_title": self.title,
                    "live_stream_offset": round(seg0_s, 3),
                    "language": self.language,
                    "preset_id": self.preset_id,
                    "aspect": self.aspect,
                },
                analysis_summary={"live_capture": True, "stream_window": label_window, "model": used_model},
            )
            s.add(p)
            s.flush()
            m_row = SourceMedia(
                project_id=pid,
                original_name=sanitize_filename(f"{self.title[:60]}_{label_window.replace(':', '-')}.mp4", default="live.mp4"),
                path=str(mp4_path),
                is_reference=False,
                source_url=self.source_url,
                size_bytes=mp4_path.stat().st_size,
                duration=dur,
                width=info["width"],
                height=info["height"],
                fps=info["fps"],
                video_codec=info["video_codec"],
                audio_codec=info["audio_codec"],
                has_audio=info["has_audio"],
                has_video=info["has_video"],
                probe=info,
                thumbnail=str(thumb) if thumb else None,
                waveform=str(art.waveform) if info["has_audio"] else None,
            )
            s.add(m_row)
            s.add(Transcript(
                project_id=pid,
                language=tr_doc["language"],
                language_probability=1.0,
                model=used_model,
                device=tr_doc["device"],
                word_count=len(words),
                sentence_count=len(sents),
                path=str(art.transcript),
            ))
            for st_ in vis.get("scene_stats") or [{"index": 0, "s": 0.0, "e": dur, "face_count": 0.0}]:
                s.add(Scene(project_id=pid, index=st_["index"], start=st_["s"], end=st_["e"], face_count=st_["face_count"]))
            s.flush()
            s.expunge(m_row)

        bundle = pipeline.build_bundle(tr_doc, au, frames, dia, vis, scenes, m_row)
        storage.write_json(art.semantic, {"topic_bounds": bundle.topic_bounds, "keywords": bundle.keywords, "topics": len(bundle.topic_bounds)})

        # Snap boundaries cleanly to speech/sentence edges so we never cut mid-utterance
        nat_s, nat_e = autoedit._natural_bounds(local_s, local_e, words, au.get("vad", []), dur)
        s_cfg = config.get_settings()
        if sents:
            scored = discovery.score_range(bundle, nat_s, nat_e, s_cfg["score_weights"])
            score = scored["score"]
            scores = scored["scores"]
            explanations = scored["explanations"]
            clip_text = discovery.clip_text(bundle, scored["i"], scored["j"])
            auto_title = discovery.make_title(bundle, scored["i"], scored["j"], scored.get("category", "insight"))
            hook_line = sents[scored["i"]]["text"][:180] if 0 <= scored["i"] < len(sents) else ""
            category = scored.get("category", "insight")
            reason = scored.get("reason", f"Captured live ({label_window})")
        else:
            score = 70.0
            scores = {k: 70.0 for k in discovery.DIMENSIONS}
            explanations = {}
            clip_text = ""
            auto_title = f"Live Clip {label_window}"
            hook_line = ""
            category = "insight"
            reason = f"Captured live at {label_window}"

        final_title = (custom_title or "").strip() or auto_title or f"Live Clip {label_window}"
        tag_kind = "live_ai" if source == "auto_ai" else "live_manual"

        with session_scope() as s:
            c_row = CandidateClip(
                project_id=pid,
                target_duration=target_dur,
                start=round(nat_s, 3),
                end=round(nat_e, 3),
                score=score,
                scores=scores,
                explanations=explanations,
                title=final_title[:140],
                category=category,
                hook=hook_line,
                description=f"Captured live from {self.title} ({label_window})",
                reason=reason,
                transcript=clip_text,
                speakers=[0],
                tags=[tag_kind, f"stream:{label_window}"],
                status="accepted" if source == "manual" else "suggested",
                fits_duration=True,
                analysis_source=tag_kind,
                rank=1,
            )
            s.add(c_row)
            s.flush()
            cid = c_row.id

        self._update_task(task_id, "Building auto-edit & captions…")
        pipeline.create_auto_edit(cid, self.preset_id, self.aspect, bundle=bundle, vis=vis, scenes=scenes, m=m_row)

        with self._lock:
            self.clip_ids.insert(0, cid)
        self._persist()
        hub.publish("clips", {"project_id": pid})
        hub.publish("live_clip_ready", {"session_id": self.id, "clip_id": cid, "source": source, "title": final_title})
        hub.publish("live_session", self.summary_dict())
        return {"clip_id": cid, "project_id": pid, "title": final_title, "source": source}

    def update_options(self, **kwargs: Any) -> None:
        with self._lock:
            for k in ("language", "preset_id", "aspect", "auto_highlight", "target_duration"):
                if kwargs.get(k) is not None:
                    setattr(self, k, kwargs[k])
        self._persist()
        hub.publish("live_session", self.summary_dict())

    def stop(self) -> None:
        self._stop_evt.set()
        with self._lock:
            if self.status in ("connecting", "live"):
                self.status = "stopped"
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=4)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        self._persist()
        hub.publish("live_session", self.summary_dict())

    def shutdown_worker(self) -> None:
        self.stop()
        self._clip_q.put(None)

    def _persist(self) -> None:
        try:
            with self._lock:
                payload = {
                    "id": self.id,
                    "video_id": self.video_id,
                    "source_url": self.source_url,
                    "title": self.title,
                    "channel": self.channel,
                    "is_live_broadcast": self.is_live_broadcast,
                    "thumbnail_url": self.thumbnail_url,
                    "language": self.language,
                    "preset_id": self.preset_id,
                    "aspect": self.aspect,
                    "auto_highlight": self.auto_highlight,
                    "dvr_minutes": self.dvr_minutes,
                    "target_duration": self.target_duration,
                    "status": self.status,
                    "error": self.error,
                    "created_at": self.created_at,
                    "dvr_start": self.dvr_start,
                    "dvr_end": self.dvr_end,
                    "clip_ids": list(self.clip_ids),
                    "transcript_tail": list(self.transcript_tail[-50:]),
                }
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.state_file)
        except OSError:
            pass

    def summary_dict(self) -> dict[str, Any]:
        with self._lock:
            seg_count = len(self._segments)
            playlist_ready = seg_count >= 2 and (self.hls_dir / "live.m3u8").exists()
            return {
                "id": self.id,
                "video_id": self.video_id,
                "source_url": self.source_url,
                "title": self.title,
                "channel": self.channel,
                "is_live_broadcast": self.is_live_broadcast,
                "thumbnail_url": self.thumbnail_url,
                "status": self.status,
                "error": self.error,
                "created_at": self.created_at,
                "dvr_start": round(self.dvr_start, 2),
                "dvr_end": round(self.dvr_end, 2),
                "buffered_seconds": round(max(0.0, self.dvr_end - self.dvr_start), 2),
                "dvr_minutes": self.dvr_minutes,
                "segment_count": seg_count,
                "playlist_ready": playlist_ready,
                "hls_url": f"/api/live/sessions/{self.id}/hls/live.m3u8",
                "language": self.language,
                "preset_id": self.preset_id,
                "aspect": self.aspect,
                "auto_highlight": self.auto_highlight,
                "target_duration": self.target_duration,
                "ai_scanning": self.ai_scanning,
                "last_ai_scan_at": self.last_ai_scan_at,
                "clip_count": len(self.clip_ids),
                "pending_clips": list(self.pending_clips.values()),
            }

    def detail_dict(self, clips_serialized: list[dict[str, Any]]) -> dict[str, Any]:
        base = self.summary_dict()
        with self._lock:
            base["transcript_tail"] = list(self.transcript_tail)
            base["clip_ids"] = list(self.clip_ids)
        base["clips"] = clips_serialized
        return base


class LiveSessionManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._sessions: dict[str, LiveSession] = {}

    def load_historical(self) -> None:
        """Load persisted stopped/ended live sessions from disk on startup."""
        config.LIVE_DIR.mkdir(parents=True, exist_ok=True)
        for sub in sorted(config.LIVE_DIR.iterdir(), reverse=True):
            sf = sub / "session.json"
            if not sub.is_dir() or not sf.exists():
                continue
            try:
                d = json.loads(sf.read_text(encoding="utf-8"))
                sid = d["id"]
            except Exception:  # noqa: BLE001
                continue
            with self._lock:
                if sid in self._sessions:
                    continue
                meta = {
                    "video_id": d.get("video_id", ""),
                    "canonical_url": d.get("source_url", ""),
                    "title": d.get("title", "Live Stream"),
                    "channel": d.get("channel", "YouTube"),
                    "is_live": d.get("is_live_broadcast", True),
                    "thumbnail": d.get("thumbnail_url"),
                    "inputs": [],
                }
                sess = LiveSession(
                    sid,
                    sub,
                    meta,
                    language=d.get("language", "hinglish"),
                    preset_id=d.get("preset_id", "podcast_pro"),
                    aspect=d.get("aspect", "9:16"),
                    auto_highlight=d.get("auto_highlight", True),
                    dvr_minutes=d.get("dvr_minutes", 30),
                    target_duration=d.get("target_duration", 45.0),
                )
                sess.status = "stopped" if d.get("status") in ("connecting", "live") else d.get("status", "stopped")
                sess.error = d.get("error")
                sess.created_at = float(d.get("created_at") or time.time())
                sess.dvr_start = float(d.get("dvr_start") or 0.0)
                sess.dvr_end = float(d.get("dvr_end") or 0.0)
                sess.clip_ids = list(d.get("clip_ids") or [])
                sess.transcript_tail = list(d.get("transcript_tail") or [])
                self._sessions[sid] = sess

    def create(
        self,
        *,
        url: str | None = None,
        local_source: str | Path | None = None,
        title_override: str | None = None,
        language: str = "hinglish",
        preset_id: str | None = None,
        aspect: str = "9:16",
        auto_highlight: bool = True,
        dvr_minutes: int = 30,
        target_duration: float = 45.0,
        pace_realtime: bool | None = None,
    ) -> LiveSession:
        media.require_ffmpeg()
        free = shutil.disk_usage(config.LIVE_DIR).free
        if free < 800e6:
            raise RuntimeError(f"Insufficient free disk space for live DVR buffer ({free / 1e6:.0f} MB free, need >= 800 MB).")

        if local_source is not None:
            meta = {
                "video_id": "local",
                "canonical_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "title": title_override or Path(local_source).stem,
                "channel": "Local Test Feed",
                "is_live": False,
                "thumbnail": None,
                "inputs": [],
                "local_source": str(local_source),
            }
        else:
            if not url:
                raise ValueError("URL is required")
            meta = resolve_youtube_live(url)

        sid = new_id()
        folder = safe_join(config.LIVE_DIR, sid)
        folder.mkdir(parents=True, exist_ok=True)
        sess = LiveSession(
            sid,
            folder,
            meta,
            language=language,
            preset_id=preset_id or config.get_settings().get("default_preset", "podcast_pro"),
            aspect=aspect,
            auto_highlight=auto_highlight,
            dvr_minutes=dvr_minutes,
            target_duration=target_duration,
            pace_realtime=pace_realtime,
        )
        with self._lock:
            self._sessions[sid] = sess
        sess.start()
        return sess

    def get(self, session_id: str) -> LiveSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def list_all(self) -> list[dict[str, Any]]:
        with self._lock:
            items = sorted(self._sessions.values(), key=lambda s: s.created_at, reverse=True)
        return [s.summary_dict() for s in items]

    def stop(self, session_id: str) -> LiveSession:
        sess = self.get(session_id)
        if sess is None:
            raise KeyError(session_id)
        sess.stop()
        return sess

    def delete(self, session_id: str) -> bool:
        with self._lock:
            sess = self._sessions.pop(session_id, None)
        if sess is None:
            return False
        sess.shutdown_worker()
        shutil.rmtree(sess.folder, ignore_errors=True)
        return True

    def clear_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for s in sessions:
            s.shutdown_worker()
            shutil.rmtree(s.folder, ignore_errors=True)
        if config.LIVE_DIR.exists():
            shutil.rmtree(config.LIVE_DIR, ignore_errors=True)
            config.LIVE_DIR.mkdir(parents=True, exist_ok=True)

    def shutdown(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
        for s in sessions:
            s.shutdown_worker()


live_manager = LiveSessionManager()
