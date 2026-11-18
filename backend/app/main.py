"""ClipForge AI - FastAPI application entry point."""
from __future__ import annotations

import os

os.environ.setdefault("DISABLE_SQLALCHEMY_CEXT_RUNTIME", "1")  # pure-python fallback (some Windows policies block the C ext)
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import asyncio
import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import __version__, config
from .api import ai, clips, exports, library, live, projects, system
from .db import init_engine, session_scope
from .events import hub
from .jobs import manager
from .services import audio_library, live_stream, pipeline


def setup_logging() -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(config.LOG_DIR / "clipforge.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        root.addHandler(fh)
        root.addHandler(sh)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    log = logging.getLogger("clipforge")
    config.ensure_dirs()
    init_engine()
    hub.bind_loop(asyncio.get_running_loop())
    pipeline.register_handlers()
    n = manager.recover()
    if n:
        log.warning("Marked %d interrupted job(s) from the previous session", n)
    manager.start()
    live_stream.live_manager.load_historical()
    with session_scope() as s:
        library.sync_builtin_presets(s)
    try:
        with session_scope() as s:
            added = audio_library.sync_builtin(s)
            if added:
                log.info("Registered %d built-in audio assets", added)
    except Exception as exc:  # noqa: BLE001
        log.warning("Audio library unavailable: %s", exc)
    log.info("%s %s ready on http://%s:%s (data: %s)", config.APP_NAME, __version__, config.HOST, config.PORT, config.HOME)
    yield
    live_stream.live_manager.shutdown()
    manager.shutdown()


app = FastAPI(title="ClipForge AI", version=__version__, lifespan=lifespan,
              description="Local AI video clipping & editing studio. All media processing runs on this computer.")

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "testserver"}
_TUNNEL_SUFFIXES = (".trycloudflare.com", ".ngrok-free.app", ".ngrok.app", ".ts.net", ".railway.app", ".onrender.com", ".koyeb.app", ".hf.space")


def _is_allowed_host(host: str) -> bool:
    if config.PUBLIC_CLOUD or config.HOST not in ("127.0.0.1", "localhost"):
        return True
    if host in ALLOWED_HOSTS or any(host.endswith(sfx) for sfx in _TUNNEL_SUFFIXES):
        return True
    extra = {h.strip().lower() for h in os.environ.get("CLIPFORGE_ALLOWED_HOSTS", "").split(",") if h.strip()}
    return host in extra


@app.middleware("http")
async def host_guard(request: Request, call_next):
    """Reject requests whose Host header is not local/tunnel (protects against DNS-rebinding) and support Chrome PNA."""
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].lower()
    if not _is_allowed_host(host):
        return JSONResponse({"detail": "Forbidden host"}, status_code=403)
    response = await call_next(request)
    if request.headers.get("access-control-request-private-network") == "true":
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if config.PUBLIC_CLOUD else ["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_origin_regex=None if config.PUBLIC_CLOUD else r"^https://[a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)*\.(vercel\.app|hf\.space)$|^http://(127\.0\.0\.1|localhost)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
    allow_private_network=True,
)

for r in (system.router, projects.router, clips.router, exports.router, library.router, ai.router, live.router):
    app.include_router(r)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    host = (ws.headers.get("host") or "").rsplit(":", 1)[0].lower()
    if not _is_allowed_host(host):
        await ws.close(code=1008)
        return
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(ws)


@app.exception_handler(RuntimeError)
async def runtime_error_handler(_request: Request, exc: RuntimeError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


# ---------------------------------------------------------------- frontend (built SPA)
@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str):
    if full_path.startswith(("api/", "ws")):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    dist = config.FRONTEND_DIST
    if not dist.exists():
        return JSONResponse({"detail": "Frontend not built. Run setup.bat (or `npm run build` in frontend/)."}, status_code=503)
    target = (dist / full_path).resolve()
    if full_path and target.is_file() and str(target).startswith(str(dist.resolve())):
        headers = {"Cache-Control": "public, max-age=31536000, immutable"} if "/assets/" in f"/{full_path}" else {}
        return FileResponse(target, headers=headers)
    return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})


def run() -> None:  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, log_level="info", reload=False, workers=1)


if __name__ == "__main__":  # pragma: no cover
    run()
