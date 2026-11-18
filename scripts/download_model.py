"""Download a Whisper model from the command line (used by setup.bat). Shows size before downloading."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("DISABLE_SQLALCHEMY_CEXT_RUNTIME", "1")

from app import config  # noqa: E402
from app.services import transcription, vision  # noqa: E402


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "base"
    if name == "yunet":
        print("Downloading YuNet face detector (0.2 MB)...")
        vision.download_yunet()
        print("Done.")
        return 0
    if name not in transcription.WHISPER_MODELS:
        print(f"Unknown model. Choose one of: {', '.join(transcription.WHISPER_MODELS)}")
        return 1
    config.ensure_dirs()
    if transcription.is_installed(name):
        print(f"Whisper '{name}' already installed.")
        return 0
    spec = transcription.WHISPER_MODELS[name]
    print(f"Downloading Whisper '{name}' ({spec['size_mb']} MB, needs ~{spec['ram_gb']} GB RAM) to {transcription.model_dir(name)}")
    transcription.download_model(name, lambda p, msg: print(f"\r  {p * 100:5.1f}%  {msg}      ", end="", flush=True))
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
