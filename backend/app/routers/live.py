"""Authenticated WebSocket proxy from the browser to go2rtc's MSE stream."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlsplit

import websockets
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from app.deps import session_from_token
from app.logredact import redact
from app.models import Camera
from app.providers import PROVIDERS
from app.providers.base import ProviderError, Quality
from app.services import Services
from app.streams import StreamManager

log = logging.getLogger(__name__)
router = APIRouter()

MAX_CLIENT_MESSAGE = 2000
_CODECS_RE = re.compile(r'codecs="([^"]*)"')


def _same_origin(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    return origin is not None and urlsplit(origin).netloc == ws.headers.get("host")


async def _error(ws: WebSocket, code: str, close_code: int = 4000, **detail: Any) -> None:
    await ws.send_json({"type": "error", "code": code, **detail})
    await ws.close(code=close_code)


def _mark_live(ws: WebSocket, camera_id: int, quality: str, codecs: str | None) -> None:
    with ws.app.state.db.sessionmaker() as db:
        cam = db.get(Camera, camera_id)
        if cam is None:
            return
        now = datetime.now(UTC)
        cam.verified = True
        cam.status = "online"
        cam.status_code = None
        cam.last_seen_at = now
        if codecs:
            cam.discovered = {**(cam.discovered or {}), f"{quality}_live_codecs": codecs}
        db.commit()


@router.websocket("/api/cameras/{camera_id}/live/{quality}")
async def live(ws: WebSocket, camera_id: int, quality: str) -> None:
    # Reject cross-site WebSocket hijacking before accepting anything.
    if quality not in ("main", "sub") or not _same_origin(ws):
        await ws.close(code=4403)
        return
    q: Quality = "main" if quality == "main" else "sub"
    settings = ws.app.state.settings
    manager: StreamManager = ws.app.state.streams
    await ws.accept()

    with ws.app.state.db.sessionmaker() as db:
        if session_from_token(db, ws.cookies.get(settings.session_cookie_name)) is None:
            await _error(ws, "auth.not_authenticated", 4401)
            return
        cam = db.get(Camera, camera_id)
        provider = PROVIDERS.get(cam.provider) if cam else None
        if cam is None or provider is None:
            await _error(ws, "camera.not_found", 4404)
            return
        svc = Services(db, ws.app.state.runtime)
        ctx = svc.stored_camera_ctx(cam)
        try:
            name = await manager.acquire(
                camera_id, q, lambda: provider.get_stream_source(ctx, q)
            )
        except ProviderError as exc:
            await _error(ws, exc.code, **exc.detail)
            return

    try:
        await _pump(ws, manager, name, camera_id, quality)
    finally:
        await manager.release(name)


async def _pump(
    ws: WebSocket, manager: StreamManager, name: str, camera_id: int, quality: str
) -> None:
    url = f"{manager.ws_base}/api/ws?src={quote(name)}"
    try:
        upstream = await websockets.connect(url, max_size=16 * 1024 * 1024, open_timeout=10)
    except (OSError, websockets.WebSocketException, TimeoutError):
        await _error(ws, "go2rtc.unreachable")
        return

    codecs: str | None = None

    async def client_to_upstream() -> None:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            text = msg.get("text")
            if not text or len(text) > MAX_CLIENT_MESSAGE:
                continue
            try:
                data = json.loads(text)
            except ValueError:
                continue
            # Only MSE negotiation is forwarded; other go2rtc commands are not exposed.
            if isinstance(data, dict) and data.get("type") == "mse":
                value = data.get("value", "")
                if isinstance(value, str):
                    await upstream.send(json.dumps({"type": "mse", "value": value}))

    async def upstream_to_client() -> None:
        nonlocal codecs
        seen_media = False
        async for message in upstream:
            if isinstance(message, bytes):
                if not seen_media:
                    seen_media = True
                    await asyncio.to_thread(_mark_live, ws, camera_id, quality, codecs)
                await ws.send_bytes(message)
                continue
            try:
                data = json.loads(message)
            except ValueError:
                continue
            kind = data.get("type")
            if kind == "mse":
                m = _CODECS_RE.search(str(data.get("value", "")))
                codecs = m.group(1) if m else None
                await ws.send_text(json.dumps({"type": "mse", "value": str(data.get("value"))}))
            elif kind == "error":
                log.info("stream %s error: %s", name, redact(str(data.get("value", ""))))
                await ws.send_json({"type": "error", "code": "stream.upstream_error"})

    tasks = [
        asyncio.create_task(client_to_upstream()),
        asyncio.create_task(upstream_to_client()),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(
                asyncio.CancelledError, WebSocketDisconnect, websockets.WebSocketException,
                RuntimeError,
            ):
                await t
        await upstream.close()
        with contextlib.suppress(RuntimeError):
            await ws.close()
