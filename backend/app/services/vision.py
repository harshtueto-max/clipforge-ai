"""Local visual analysis: scene detection (PySceneDetect), face detection & tracking (OpenCV),
subject/motion estimation for automatic reframing."""
from __future__ import annotations

import logging
import urllib.request
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .. import config
from . import media

log = logging.getLogger("clipforge.vision")

YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
YUNET_PATH = config.VISION_DIR / "face_detection_yunet_2023mar.onnx"
YUNET_SIZE_KB = 228

QUALITY = {
    "fast": {"sample_fps": 1.0, "width": 480, "scene_threshold": 30.0},
    "balanced": {"sample_fps": 2.0, "width": 640, "scene_threshold": 27.0},
    "high": {"sample_fps": 4.0, "width": 854, "scene_threshold": 25.0},
}


def yunet_installed() -> bool:
    return YUNET_PATH.exists() and YUNET_PATH.stat().st_size > 100_000


def download_yunet() -> Path:
    if config.get_settings().get("offline_mode"):
        raise RuntimeError("Offline mode is enabled")
    YUNET_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = YUNET_PATH.with_suffix(".part")
    req = urllib.request.Request(YUNET_URL, headers={"User-Agent": "ClipForgeAI/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        f.write(r.read())
    tmp.replace(YUNET_PATH)
    return YUNET_PATH


class FaceDetector:
    def __init__(self, width: int, height: int):
        import cv2

        self.cv2 = cv2
        self.kind = "haar"
        self.yunet = None
        if yunet_installed():
            try:
                self.yunet = cv2.FaceDetectorYN.create(str(YUNET_PATH), "", (width, height), 0.7, 0.3, 50)
                self.kind = "yunet"
            except Exception as exc:  # noqa: BLE001
                log.warning("YuNet unavailable (%s); using Haar cascades", exc)
        if self.yunet is None:
            self.frontal = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            self.profile = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")

    def detect(self, frame: np.ndarray) -> list[list[float]]:
        h, w = frame.shape[:2]
        out: list[list[float]] = []
        if self.yunet is not None:
            self.yunet.setInputSize((w, h))
            _, faces = self.yunet.detect(frame)
            if faces is not None:
                for f in faces:
                    x, y, fw, fh, score = float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[14])
                    out.append([(x + fw / 2) / w, (y + fh / 2) / h, fw / w, fh / h, score])
        else:
            gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
            gray = self.cv2.equalizeHist(gray)
            min_size = (max(20, w // 25), max(20, w // 25))
            rects = list(self.frontal.detectMultiScale(gray, 1.1, 5, minSize=min_size))
            if not rects:
                rects = list(self.profile.detectMultiScale(gray, 1.1, 5, minSize=min_size))
            for (x, y, fw, fh) in rects:
                out.append([(x + fw / 2) / w, (y + fh / 2) / h, fw / w, fh / h, 0.8])
        # drop tiny / implausible detections
        out = [f for f in out if f[2] > 0.02 and f[3] > 0.03]
        out.sort(key=lambda f: -f[2] * f[3])
        return out[:6]


def make_analysis_proxy(src: str | Path, dst: Path, duration: float, width: int, ctx=None, progress=None) -> Path:
    ffmpeg, _ = media.require_ffmpeg()
    tmp = dst.with_name(dst.stem + ".part.mp4")
    # Software decode is used deliberately: in testing `-hwaccel auto` (d3d11va copy-back) was ~2x slower for this
    # downscale workload than multi-threaded CPU decoding.
    cmd = [ffmpeg, "-y", "-v", "error", "-nostdin", "-threads", "0", "-i", str(src), "-map", "0:v:0", "-an",
           "-vf", f"fps=12,scale={width}:-2:flags=fast_bilinear", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-g", "24",
           "-progress", "pipe:1", str(tmp)]
    media.run_with_progress(cmd, duration, progress, ctx)
    tmp.replace(dst)
    return dst


def detect_scenes(proxy: Path, threshold: float, ctx=None, progress=None) -> list[dict[str, float]]:
    from scenedetect import ContentDetector, SceneManager, open_video

    video = open_video(str(proxy))
    sm = SceneManager()
    sm.add_detector(ContentDetector(threshold=threshold, min_scene_len=12))
    total = video.duration.frame_num if video.duration else 0

    def _cb(_img, frame_num):
        if ctx is not None and ctx.cancelled:
            raise RuntimeError("cancelled")
        if progress and total:
            n = frame_num if isinstance(frame_num, (int, float)) else getattr(frame_num, "frame_num", 0)
            progress(min(0.999, n / total))

    try:
        sm.detect_scenes(video=video, callback=_cb, show_progress=False)
    except TypeError:
        sm.detect_scenes(video=video, show_progress=False)
    if ctx is not None:
        ctx.check_cancel()
    scenes = sm.get_scene_list()
    out = [{"s": round(a.seconds, 3), "e": round(b.seconds, 3)} for a, b in scenes]
    if not out:
        dur = video.duration.seconds if video.duration else 0
        out = [{"s": 0.0, "e": round(dur, 3)}]
    return out


def sample_frames(proxy: Path, sample_fps: float, ctx=None, progress=None) -> dict[str, Any]:
    """Sample frames at a controlled rate; detect faces, motion, sharpness and subject position."""
    import cv2

    cap = cv2.VideoCapture(str(proxy))
    if not cap.isOpened():
        raise RuntimeError("Could not open analysis proxy")
    fps = cap.get(cv2.CAP_PROP_FPS) or 12.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    step = max(1, int(round(fps / sample_fps)))
    det = FaceDetector(w, h)
    samples = []
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
            t = i / fps
            faces = det.detect(frame)
            gray = cv2.cvtColor(cv2.resize(frame, (160, int(160 * h / w))), cv2.COLOR_BGR2GRAY)
            sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            bright = float(gray.mean())
            motion = 0.0
            subject = [0.5, 0.45]
            if prev_gray is not None and prev_gray.shape == gray.shape:
                diff = cv2.absdiff(gray, prev_gray).astype(np.float32)
                motion = float(diff.mean())
                if diff.sum() > 0 and motion > 2:
                    ys, xs = np.indices(diff.shape)
                    wsum = diff.sum()
                    subject = [float((xs * diff).sum() / wsum / diff.shape[1]), float((ys * diff).sum() / wsum / diff.shape[0])]
            prev_gray = gray
            samples.append({"t": round(t, 3), "faces": [[round(v, 4) for v in f] for f in faces], "motion": round(motion, 2),
                            "sharp": round(sharp, 1), "bright": round(bright, 1), "subject": [round(subject[0], 3), round(subject[1], 3)]})
            if progress and total:
                progress(min(0.999, i / total))
            if ctx is not None:
                ctx.check_cancel()
        i += 1
    cap.release()
    tracks = track_faces(samples)
    return {"sample_fps": sample_fps, "width": w, "height": h, "detector": det.kind, "samples": samples, "tracks": tracks}


def track_faces(samples: list[dict[str, Any]], max_dist: float = 0.12, max_gap: int = 4) -> list[dict[str, Any]]:
    """Greedy centroid tracker linking detections into face tracks."""
    tracks: list[dict[str, Any]] = []
    active: list[int] = []
    for si, smp in enumerate(samples):
        used = set()
        for fi, f in enumerate(smp["faces"]):
            best, bd = None, max_dist
            for ti in active:
                tr = tracks[ti]
                if si - tr["last"] > max_gap:
                    continue
                lx, ly = tr["pts"][-1][1], tr["pts"][-1][2]
                d = ((f[0] - lx) ** 2 + (f[1] - ly) ** 2) ** 0.5
                if d < bd and ti not in used:
                    best, bd = ti, d
            if best is None:
                tracks.append({"id": len(tracks), "pts": [[smp["t"], f[0], f[1], f[2], f[3]]], "last": si})
                active.append(len(tracks) - 1)
                f.append(len(tracks) - 1)
            else:
                tracks[best]["pts"].append([smp["t"], f[0], f[1], f[2], f[3]])
                tracks[best]["last"] = si
                used.add(best)
                f.append(best)
        active = [ti for ti in active if si - tracks[ti]["last"] <= max_gap]
    out = []
    for tr in tracks:
        if len(tr["pts"]) >= 3:
            pts = np.array(tr["pts"])
            out.append({"id": tr["id"], "start": float(pts[0, 0]), "end": float(pts[-1, 0]), "cx": round(float(np.median(pts[:, 1])), 3),
                        "cy": round(float(np.median(pts[:, 2])), 3), "size": round(float(np.median(pts[:, 3])), 3), "n": len(pts)})
    return out


def speaker_positions(samples: list[dict[str, Any]], sentences: list[dict[str, Any]]) -> dict[int, dict[str, float]]:
    """Estimate where each (anonymous) speaker usually appears on screen, using frames where exactly one
    face is visible while that speaker is talking (common in multi-camera podcasts)."""
    if not sentences or not samples:
        return {}
    times = np.array([s["s"] for s in sentences])
    acc: dict[int, list[float]] = {}
    for smp in samples:
        if len(smp["faces"]) != 1:
            continue
        j = int(np.searchsorted(times, smp["t"], side="right") - 1)
        if j < 0 or smp["t"] > sentences[j]["e"]:
            continue
        sp = int(sentences[j].get("speaker", 0))
        acc.setdefault(sp, []).append(smp["faces"][0][0])
    out = {}
    for sp, xs in acc.items():
        if len(xs) >= 5:
            out[sp] = {"cx": round(float(np.median(xs)), 3), "n": len(xs), "spread": round(float(np.std(xs)), 3)}
    return out


def summarize(samples: list[dict[str, Any]], scenes: list[dict[str, float]]) -> list[dict[str, Any]]:
    """Per-scene face statistics."""
    out = []
    times = np.array([s["t"] for s in samples]) if samples else np.array([])
    for k, sc in enumerate(scenes):
        idx = np.where((times >= sc["s"]) & (times < sc["e"]))[0] if len(times) else []
        fc = [len(samples[i]["faces"]) for i in idx]
        out.append({"index": k, "s": sc["s"], "e": sc["e"], "face_count": round(float(np.mean(fc)), 2) if fc else 0.0})
    return out
