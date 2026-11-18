"""ClipForge AI Windows launcher: dependency check, start/stop the local server, open the browser.

Used by start.bat / stop.bat. Runs with the project's virtual-environment Python.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
HOST = os.environ.get("CLIPFORGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("CLIPFORGE_PORT", "8765"))
URL = f"http://{HOST}:{PORT}"
HOME = Path(os.environ.get("CLIPFORGE_HOME") or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ClipForgeAI")
PID_FILE = HOME / "server.pid"
LOG_FILE = HOME / "logs" / "server-console.log"
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200


def health(timeout: float = 1.5) -> dict | None:
    try:
        with urllib.request.urlopen(f"{URL}/api/health", timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:  # noqa: BLE001
        return None


def check() -> bool:
    ok = True
    print("Checking dependencies...")
    if sys.version_info < (3, 10):
        print(f"  [X] Python 3.10+ required (found {sys.version.split()[0]})")
        ok = False
    else:
        print(f"  [OK] Python {sys.version.split()[0]}")
    for exe in ("ffmpeg", "ffprobe"):
        p = shutil.which(exe)
        print(f"  [{'OK' if p else 'X '}] {exe}: {p or 'NOT FOUND - run setup.bat or install FFmpeg'}")
        ok &= bool(p)
    dist = ROOT / "frontend" / "dist" / "index.html"
    print(f"  [{'OK' if dist.exists() else 'X '}] Frontend build: {'present' if dist.exists() else 'missing - run setup.bat'}")
    ok &= dist.exists()
    try:
        import fastapi  # noqa: F401
        import faster_whisper  # noqa: F401

        print("  [OK] Python packages")
    except Exception as exc:  # noqa: BLE001
        print(f"  [X ] Python packages missing ({exc}) - run setup.bat")
        ok = False
    models = HOME / "models" / "whisper"
    installed = [d.name for d in models.iterdir() if (d / "model.bin").exists()] if models.exists() else []
    if installed:
        print(f"  [OK] Whisper models: {', '.join(installed)}")
    else:
        print("  [! ] No Whisper model installed yet - download one in Settings > AI Models (the app will guide you)")
    return ok


def start(open_browser: bool = True) -> int:
    h = health()
    if h:
        print(f"ClipForge AI is already running at {URL}")
        if open_browser:
            webbrowser.open(URL)
        return 0
    if not check():
        print("\nSome required dependencies are missing. Please run setup.bat first.")
        return 1
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.setdefault("DISABLE_SQLALCHEMY_CEXT_RUNTIME", "1")
    env["PYTHONUNBUFFERED"] = "1"
    log = open(LOG_FILE, "a", encoding="utf-8")
    log.write(f"\n==== start {time.strftime('%Y-%m-%d %H:%M:%S')} ====\n")
    log.flush()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", HOST, "--port", str(PORT), "--log-level", "info"],
                            cwd=str(BACKEND), stdout=log, stderr=subprocess.STDOUT, env=env,
                            creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP, close_fds=True)
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(proc.pid))
    print(f"Starting backend (pid {proc.pid}) on {URL} ...", end="", flush=True)
    for _ in range(120):
        if proc.poll() is not None:
            print(f"\nBackend exited with code {proc.returncode}. See log: {LOG_FILE}")
            return 1
        if health():
            print(" ready.")
            if open_browser:
                webbrowser.open(URL)
            print(f"\nClipForge AI is running at {URL}\nClose it any time with stop.bat. Logs: {HOME / 'logs'}")
            return 0
        print(".", end="", flush=True)
        time.sleep(1)
    print(f"\nBackend did not become ready in time. See log: {LOG_FILE}")
    return 1


def stop() -> int:
    pid = PID_FILE.read_text().strip() if PID_FILE.exists() else None
    if pid:
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
        PID_FILE.unlink(missing_ok=True)
    # Also stop any uvicorn app.main:app process on our port (e.g. started manually or venv child)
    if health():
        try:
            import psutil

            me = os.getpid()
            for proc in psutil.process_iter(["pid", "cmdline"]):
                try:
                    cmd = " ".join(proc.info.get("cmdline") or [])
                    if proc.info["pid"] != me and "app.main:app" in cmd and str(PORT) in cmd:
                        subprocess.run(["taskkill", "/PID", str(proc.info["pid"]), "/T", "/F"], capture_output=True)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:  # noqa: BLE001
            pass
    if health():
        try:
            out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[1].endswith(f":{PORT}") and parts[3] == "LISTENING" and parts[4] != "0":
                    subprocess.run(["taskkill", "/PID", parts[4], "/T", "/F"], capture_output=True)
        except Exception:  # noqa: BLE001
            pass
    for _ in range(10):
        if not health(0.5):
            break
        time.sleep(0.5)
    print("ClipForge AI stopped." if not health(0.5) else "Could not stop the server - close the python process manually.")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    if cmd == "start":
        sys.exit(start("--no-browser" not in sys.argv))
    if cmd == "stop":
        sys.exit(stop())
    if cmd == "check":
        sys.exit(0 if check() else 1)
    print("usage: launcher.py start|stop|check")
    sys.exit(2)
