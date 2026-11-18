"""WebSocket event hub. Thread-safe publish from worker threads."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("clipforge.events")


class EventHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def _broadcast(self, message: str) -> None:
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._loop is None or not self._clients:
            return
        msg = json.dumps({"type": event_type, "data": payload}, default=str)
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast(msg), self._loop)
        except RuntimeError:
            pass


hub = EventHub()
