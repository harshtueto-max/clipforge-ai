"""Background job queue with progress reporting, cancellation and crash recovery."""
from __future__ import annotations

import logging
import subprocess
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from . import config
from .db import session_scope
from .events import hub
from .models import Job, utcnow

log = logging.getLogger("clipforge.jobs")

POOL_FOR_KIND = {
    "analysis": "analysis",
    "render": "render",
    "import": "io",
    "download": "io",
    "proxy": "io",
    "model_download": "io",
    "rediscover": "analysis",
}


class JobCancelled(Exception):
    pass


class JobContext:
    def __init__(self, manager: "JobManager", job_id: str, project_id: str | None, params: dict[str, Any]):
        self.manager = manager
        self.job_id = job_id
        self.project_id = project_id
        self.params = params
        self.cancel_event = threading.Event()
        self._procs: list[subprocess.Popen] = []
        self._last_emit = 0.0
        self._stage: str | None = None
        self.result: dict[str, Any] = {}

    # progress -----------------------------------------------------------
    def progress(self, value: float, stage: str | None = None, message: str | None = None, force: bool = False) -> None:
        self.check_cancel()
        now = time.monotonic()
        stage_changed = stage is not None and stage != self._stage
        if stage is not None:
            self._stage = stage
        if not force and not stage_changed and now - self._last_emit < 0.4:
            return
        self._last_emit = now
        self.manager._update(self.job_id, progress=max(0.0, min(1.0, value)), stage=self._stage, message=message)

    def log(self, message: str) -> None:
        log.info("[job %s] %s", self.job_id, message)

    # cancellation -------------------------------------------------------
    def check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise JobCancelled()

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def register_process(self, proc: subprocess.Popen) -> None:
        self._procs.append(proc)
        if self.cancel_event.is_set():
            self.kill_processes()

    def unregister_process(self, proc: subprocess.Popen) -> None:
        if proc in self._procs:
            self._procs.remove(proc)

    def kill_processes(self) -> None:
        for p in list(self._procs):
            try:
                if p.poll() is None:
                    p.kill()
            except Exception:
                pass


Handler = Callable[[JobContext], dict[str, Any] | None]


class JobManager:
    def __init__(self) -> None:
        self.handlers: dict[str, Handler] = {}
        self.pools: dict[str, ThreadPoolExecutor] = {}
        self.active: dict[str, JobContext] = {}
        self._lock = threading.Lock()
        self.on_finish: dict[str, Callable[[str, str, dict], None]] = {}

    def start(self) -> None:
        s = config.get_settings()
        self.pools = {
            "analysis": ThreadPoolExecutor(max_workers=max(1, int(s.get("analysis_concurrency", 1))), thread_name_prefix="analysis"),
            "render": ThreadPoolExecutor(max_workers=max(1, int(s.get("render_concurrency", 1))), thread_name_prefix="render"),
            "io": ThreadPoolExecutor(max_workers=3, thread_name_prefix="io"),
        }

    def shutdown(self) -> None:
        for ctx in list(self.active.values()):
            ctx.cancel_event.set()
            ctx.kill_processes()
        for p in self.pools.values():
            p.shutdown(wait=False, cancel_futures=True)
        self.pools = {}

    def register(self, kind: str, handler: Handler, on_finish: Callable[[str, str, dict], None] | None = None) -> None:
        self.handlers[kind] = handler
        if on_finish:
            self.on_finish[kind] = on_finish

    # ------------------------------------------------------------------
    def submit(self, kind: str, project_id: str | None, params: dict[str, Any] | None = None, job_id: str | None = None) -> str:
        params = params or {}
        with session_scope() as s:
            if job_id:
                job = s.get(Job, job_id)
                job.status = "queued"
                job.progress = 0.0
                job.error = None
                job.message = "Queued"
                job.started_at = None
                job.finished_at = None
                job.params = params or job.params
            else:
                job = Job(kind=kind, project_id=project_id, params=params, status="queued", message="Queued")
                s.add(job)
            s.flush()
            job_id = job.id
            data = job_to_dict(job)
        hub.publish("job", data)
        self._dispatch(job_id, kind)
        return job_id

    def _dispatch(self, job_id: str, kind: str) -> None:
        if not self.pools:
            self.start()
        pool = self.pools[POOL_FOR_KIND.get(kind, "io")]
        pool.submit(self._run, job_id)

    def _run(self, job_id: str) -> None:
        with session_scope() as s:
            job = s.get(Job, job_id)
            if job is None or job.status != "queued":
                return
            job.status = "running"
            job.started_at = utcnow()
            job.message = "Starting"
            kind, project_id, params = job.kind, job.project_id, dict(job.params or {})
            hub.publish("job", job_to_dict(job))
        ctx = JobContext(self, job_id, project_id, params)
        with self._lock:
            self.active[job_id] = ctx
        handler = self.handlers.get(kind)
        status, error, result = "completed", None, {}
        try:
            if handler is None:
                raise RuntimeError(f"No handler for job kind {kind}")
            result = handler(ctx) or {}
            ctx.check_cancel()
        except JobCancelled:
            status, error = "cancelled", None
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            error = f"{type(exc).__name__}: {exc}"
            log.error("Job %s (%s) failed: %s\n%s", job_id, kind, exc, traceback.format_exc())
        finally:
            ctx.kill_processes()
            with self._lock:
                self.active.pop(job_id, None)
        self._update(
            job_id,
            status=status,
            error=error,
            result=result,
            progress=1.0 if status == "completed" else None,
            message={"completed": "Completed", "cancelled": "Cancelled by user", "failed": "Failed"}[status],
            finished=True,
        )
        cb = self.on_finish.get(kind)
        if cb:
            try:
                cb(job_id, status, {"error": error, "result": result, "params": params, "project_id": project_id})
            except Exception:  # noqa: BLE001
                log.exception("on_finish callback failed for %s", job_id)

    def _update(self, job_id: str, *, status: str | None = None, progress: float | None = None, stage: str | None = None,
                message: str | None = None, error: str | None = None, result: dict | None = None, finished: bool = False) -> None:
        with session_scope() as s:
            job = s.get(Job, job_id)
            if job is None:
                return
            if status:
                job.status = status
            if progress is not None:
                job.progress = progress
            if stage is not None:
                job.stage = stage
            if message is not None:
                job.message = message
            if error is not None:
                job.error = error
            if result is not None:
                job.result = result
            if finished:
                job.finished_at = utcnow()
            data = job_to_dict(job)
        hub.publish("job", data)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            ctx = self.active.get(job_id)
        if ctx:
            ctx.cancel_event.set()
            ctx.kill_processes()
            return True
        with session_scope() as s:
            job = s.get(Job, job_id)
            if job and job.status == "queued":
                job.status = "cancelled"
                job.message = "Cancelled before start"
                job.finished_at = utcnow()
                hub.publish("job", job_to_dict(job))
                return True
        return False

    def retry(self, job_id: str) -> str:
        with session_scope() as s:
            job = s.get(Job, job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status in ("running", "queued"):
                raise ValueError("Job is still active")
            kind, project_id, params = job.kind, job.project_id, dict(job.params or {})
        params["resume"] = True
        return self.submit(kind, project_id, params, job_id=job_id)

    def recover(self) -> int:
        """Mark jobs that were running when the app stopped as interrupted."""
        n = 0
        with session_scope() as s:
            for job in s.query(Job).filter(Job.status.in_(["running", "queued"])).all():
                job.status = "interrupted"
                job.message = "Interrupted by application shutdown - you can resume it"
                job.finished_at = utcnow()
                n += 1
        return n


def job_to_dict(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "message": job.message,
        "error": job.error,
        "params": job.params,
        "result": job.result,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


manager = JobManager()
