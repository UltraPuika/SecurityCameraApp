"""Registers camera upstreams with go2rtc on demand and removes them after an idle period."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx

from app.providers.base import ProviderError, StreamSource, Unreachable

log = logging.getLogger(__name__)


class StreamLimitReached(ProviderError):
    code = "stream.limit_reached"


@dataclass
class ActiveStream:
    name: str
    camera_id: int
    quality: str
    url: str
    transport: str
    viewers: int = 0
    started_at: float = field(default_factory=time.time)
    idle_task: asyncio.Task[None] | None = None


class StreamManager:
    def __init__(
        self, http: httpx.AsyncClient, go2rtc_url: str, idle_seconds: float, max_streams: int
    ) -> None:
        self.http = http
        self.base = go2rtc_url.rstrip("/")
        self.idle_seconds = idle_seconds
        self.max_streams = max_streams
        self.active: dict[str, ActiveStream] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def name(camera_id: int, quality: str) -> str:
        return f"cam{camera_id}_{quality}"

    @property
    def ws_base(self) -> str:
        return "ws" + self.base[4:] if self.base.startswith("http") else self.base

    async def acquire(
        self,
        camera_id: int,
        quality: str,
        source: Callable[[], Awaitable[StreamSource]],
    ) -> str:
        name = self.name(camera_id, quality)
        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            st = self.active.get(name)
            if st is None:
                if len(self.active) >= self.max_streams:
                    raise StreamLimitReached(max=self.max_streams)
                src = await source()
                st = ActiveStream(name, camera_id, quality, src.url, src.transport)
            elif st.idle_task is not None:
                st.idle_task.cancel()
                st.idle_task = None
            # Re-registering is idempotent and recovers from a go2rtc restart.
            await self._register(name, st.url)
            self.active[name] = st
            st.viewers += 1
            return name

    async def release(self, name: str) -> None:
        st = self.active.get(name)
        if st is None:
            return
        st.viewers = max(0, st.viewers - 1)
        if st.viewers == 0 and st.idle_task is None:
            st.idle_task = asyncio.create_task(self._expire(name))

    async def drop(self, camera_id: int) -> None:
        """Forget a camera's streams immediately (e.g. after its settings changed)."""
        for quality in ("main", "sub"):
            name = self.name(camera_id, quality)
            st = self.active.pop(name, None)
            if st is not None:
                if st.idle_task is not None:
                    st.idle_task.cancel()
                await self._unregister(name)

    async def _expire(self, name: str) -> None:
        await asyncio.sleep(self.idle_seconds)
        async with self._locks.setdefault(name, asyncio.Lock()):
            st = self.active.get(name)
            if st is not None and st.viewers == 0:
                del self.active[name]
                await self._unregister(name)

    async def _register(self, name: str, url: str) -> None:
        try:
            resp = await self.http.put(
                f"{self.base}/api/streams", params={"name": name, "src": url}, timeout=5
            )
        except httpx.HTTPError as exc:
            raise Unreachable("go2rtc.unreachable") from exc
        if resp.status_code >= 400:
            raise Unreachable("go2rtc.rejected", http_status=resp.status_code)

    async def _unregister(self, name: str) -> None:
        with contextlib.suppress(httpx.HTTPError):
            await self.http.delete(f"{self.base}/api/streams", params={"src": name}, timeout=5)

    async def healthy(self) -> bool:
        try:
            resp = await self.http.get(f"{self.base}/api", timeout=3)
        except httpx.HTTPError:
            return False
        return resp.status_code == 200

    async def close(self) -> None:
        for name in list(self.active):
            st = self.active.pop(name)
            if st.idle_task is not None:
                st.idle_task.cancel()
            await self._unregister(name)
