"""Hardware / dependency detection."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from typing import Any

import psutil

from .. import config
from . import media

_cache: dict[str, Any] = {}


def _nvidia() -> list[dict[str, Any]]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        cp = subprocess.run([exe, "--query-gpu=name,memory.total,memory.used,utilization.gpu,driver_version", "--format=csv,noheader,nounits"],
                            capture_output=True, text=True, timeout=5, creationflags=media.CREATE_NO_WINDOW)
        out = []
        for line in cp.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                out.append({"name": parts[0], "vram_total_mb": int(float(parts[1])), "vram_used_mb": int(float(parts[2])),
                            "utilization": int(float(parts[3])), "driver": parts[4], "vendor": "NVIDIA"})
        return out
    except Exception:  # noqa: BLE001
        return []


def _other_gpus() -> list[str]:
    if os.name != "nt":
        return []
    try:
        cp = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"], capture_output=True, text=True,
                            timeout=8, creationflags=media.CREATE_NO_WINDOW)
        return [x.strip() for x in cp.stdout.splitlines() if x.strip()]
    except Exception:  # noqa: BLE001
        return []


def hardware_summary() -> dict[str, Any]:
    if "hw" in _cache and time.time() - _cache["hw_t"] < 300:
        return dict(_cache["hw"])
    gpus = _nvidia()
    all_gpus = _other_gpus()
    hw = {
        "os": f"{platform.system()} {platform.release()} ({platform.version()})", "python": sys.version.split()[0],
        "cpu": platform.processor() or "CPU", "cpu_cores": psutil.cpu_count(logical=True) or 1,
        "ram_gb": round(psutil.virtual_memory().total / 1e9, 1), "gpus": gpus, "all_gpus": all_gpus,
        "gpu_vram_gb": round(max((g["vram_total_mb"] for g in gpus), default=0) / 1024, 1),
    }
    _cache["hw"], _cache["hw_t"] = hw, time.time()
    return dict(hw)


def live_status() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    try:
        disk = shutil.disk_usage(config.projects_dir())
    except OSError:
        disk = shutil.disk_usage(config.HOME)
    return {
        "cpu_percent": psutil.cpu_percent(interval=None), "ram_used_gb": round(vm.used / 1e9, 1), "ram_total_gb": round(vm.total / 1e9, 1),
        "ram_percent": vm.percent, "disk_free_gb": round(disk.free / 1e9, 1), "disk_total_gb": round(disk.total / 1e9, 1),
        "gpus": _nvidia(),
    }


def ffmpeg_version() -> str | None:
    f = media.ffmpeg_bin()
    if not f:
        return None
    try:
        cp = subprocess.run([f, "-version"], capture_output=True, text=True, timeout=10, creationflags=media.CREATE_NO_WINDOW)
        return cp.stdout.splitlines()[0] if cp.stdout else None
    except Exception:  # noqa: BLE001
        return None
