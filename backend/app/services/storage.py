"""Project storage helpers: folder layout, JSON artifacts and analysis bundle loading."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np

from .. import config
from ..security import safe_join


def project_folder(project_id: str) -> Path:
    return safe_join(config.projects_dir(), project_id)


def ensure_layout(folder: Path) -> None:
    for sub in ("media", "analysis", "thumbs", "proxy", "renders"):
        (folder / sub).mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, default=_default), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _default(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    raise TypeError(type(o))


class Artifacts:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.a = self.folder / "analysis"

    @property
    def wav(self) -> Path: return self.a / "audio.wav"
    @property
    def waveform(self) -> Path: return self.a / "waveform.bin"
    @property
    def transcript(self) -> Path: return self.a / "transcript.json"
    @property
    def audio(self) -> Path: return self.a / "audio.json"
    @property
    def audio_frames(self) -> Path: return self.a / "audio_frames.npz"
    @property
    def diarization(self) -> Path: return self.a / "diarization.json"
    @property
    def vision_proxy(self) -> Path: return self.a / "vision_proxy.mp4"
    @property
    def scenes(self) -> Path: return self.a / "scenes.json"
    @property
    def vision(self) -> Path: return self.a / "vision.json"
    @property
    def semantic(self) -> Path: return self.a / "semantic.json"
    @property
    def preview_proxy(self) -> Path: return self.folder / "proxy" / "preview.mp4"
