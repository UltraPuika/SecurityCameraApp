"""Stream lifecycle (lazy start, idle stop, limits) and the authenticated MSE proxy."""

import asyncio
import json
import threading
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.server import ServerConnection, serve

from app.config import Settings
from app.main import create_app
from app.providers.base import StreamSource
from app.streams import StreamLimitReached, StreamManager
from tests.conftest import login


class FakeGo2rtc:
    def __init__(self) -> None:
        self.streams: dict[str, str] = {}
        self.calls: list[str] = []
        self.ws_port = 0
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.client_messages: list[str] = []

    def http(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/api" and request.method == "GET":
            return httpx.Response(200, json={"version": "fake"})
        if request.url.path == "/api/streams" and request.method == "PUT":
            self.streams[request.url.params["name"]] = request.url.params["src"]
            return httpx.Response(200)
        if request.url.path == "/api/streams" and request.method == "DELETE":
            self.streams.pop(request.url.params["src"], None)
            return httpx.Response(200)
        return httpx.Response(404)

    async def _ws(self, conn: ServerConnection) -> None:
        src = conn.request.path.split("src=", 1)[-1] if conn.request else ""
        async for msg in conn:
            self.client_messages.append(str(msg))
            if src not in self.streams:
                await conn.send(json.dumps({"type": "error", "value": "stream not found"}))
                return
            await conn.send(json.dumps(
                {"type": "mse", "value": 'video/mp4; codecs="avc1.640029"'}))
            for i in range(3):
                await conn.send(bytes([0, 0, 0, i]))
            await asyncio.sleep(0.5)
            await conn.send(json.dumps(
                {"type": "error", "value": "rtsp://admin:s3cret@10.0.0.9/x EOF"}))

    def __enter__(self) -> "FakeGo2rtc":
        self.thread.start()

        async def start() -> int:
            self.server = await serve(self._ws, "127.0.0.1", 0)
            return list(self.server.sockets)[0].getsockname()[1]  # type: ignore[no-any-return]

        self.ws_port = asyncio.run_coroutine_threadsafe(start(), self.loop).result(5)
        return self

    def __exit__(self, *_: object) -> None:
        async def stop() -> None:
            self.server.close()
            await self.server.wait_closed()

        asyncio.run_coroutine_threadsafe(stop(), self.loop).result(5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


# --- StreamManager unit tests --------------------------------------------------------


def _manager(fake: FakeGo2rtc, idle: float = 0.2, max_streams: int = 2) -> tuple[
    StreamManager, httpx.AsyncClient
]:
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.http))
    return StreamManager(http, "http://go2rtc:1984", idle, max_streams), http


async def _src() -> StreamSource:
    return StreamSource("rtsp://u:p@10.0.0.9:554/x", "local")


def test_shared_upstream_and_idle_stop() -> None:
    fake = FakeGo2rtc()
    sources = 0

    async def counting_src() -> StreamSource:
        nonlocal sources
        sources += 1
        return await _src()

    async def go() -> None:
        mgr, http = _manager(fake)
        async with http:
            a = await mgr.acquire(1, "sub", counting_src)
            b = await mgr.acquire(1, "sub", counting_src)
            assert a == b == "cam1_sub" and sources == 1
            assert mgr.active[a].viewers == 2
            await mgr.release(a)
            await mgr.release(a)
            assert "cam1_sub" in fake.streams
            await asyncio.sleep(0.35)
            assert "cam1_sub" not in fake.streams and not mgr.active

    asyncio.run(go())


def test_reacquire_cancels_idle_stop() -> None:
    fake = FakeGo2rtc()

    async def go() -> None:
        mgr, http = _manager(fake)
        async with http:
            name = await mgr.acquire(1, "sub", _src)
            await mgr.release(name)
            await asyncio.sleep(0.1)
            await mgr.acquire(1, "sub", _src)
            await asyncio.sleep(0.25)
            assert name in mgr.active and name in fake.streams

    asyncio.run(go())


def test_stream_limit() -> None:
    fake = FakeGo2rtc()

    async def go() -> None:
        mgr, http = _manager(fake, max_streams=2)
        async with http:
            await mgr.acquire(1, "sub", _src)
            await mgr.acquire(2, "sub", _src)
            with pytest.raises(StreamLimitReached) as exc:
                await mgr.acquire(3, "sub", _src)
            assert exc.value.code == "stream.limit_reached"
            # Joining an already-running stream is always allowed.
            await mgr.acquire(1, "sub", _src)

    asyncio.run(go())


def test_drop_removes_immediately() -> None:
    fake = FakeGo2rtc()

    async def go() -> None:
        mgr, http = _manager(fake)
        async with http:
            await mgr.acquire(5, "main", _src)
            await mgr.drop(5)
            assert not mgr.active and not fake.streams

    asyncio.run(go())


def test_go2rtc_down_is_unreachable() -> None:
    async def go() -> None:
        http = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: (_ for _ in ()).throw(httpx.ConnectError("down"))))
        async with http:
            mgr = StreamManager(http, "http://go2rtc:1984", 1, 2)
            with pytest.raises(Exception) as exc:
                await mgr.acquire(1, "sub", _src)
            assert getattr(exc.value, "code", "") == "go2rtc.unreachable"
            assert not mgr.active

    asyncio.run(go())


# --- WebSocket proxy -----------------------------------------------------------------


@pytest.fixture
def stack(make_settings: Callable[..., Settings]) -> Iterator[tuple[TestClient, str, FakeGo2rtc]]:
    with FakeGo2rtc() as fake:
        settings = make_settings(
            go2rtc_url=f"http://127.0.0.1:{fake.ws_port}", stream_idle_seconds=5,
            probe_timeout_seconds=1,
        )
        app = create_app(settings, http_transport=httpx.MockTransport(fake.http))
        with TestClient(app, base_url="https://testserver") as c:
            yield c, login(c), fake


def _camera(c: TestClient, csrf: str) -> dict[str, Any]:
    body = {
        "name": "Gate", "provider": "generic",
        "config": {"host": "10.0.0.9", "use_onvif": False, "main_path": "/ch01/0",
                   "sub_path": "/ch01/1"},
        "secrets": {"username": "admin", "password": "s3cret"},
    }
    r = c.post("/api/cameras", json=body, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201
    return r.json()  # type: ignore[no-any-return]


def _ws_headers(c: TestClient) -> dict[str, str]:
    cookie = "; ".join(f"{k}={v}" for k, v in c.cookies.items())
    return {"origin": "https://testserver", "cookie": cookie}


def test_live_stream_proxied_and_camera_verified(stack: tuple[TestClient, str, FakeGo2rtc]) -> None:
    c, csrf, fake = stack
    cam = _camera(c, csrf)
    assert cam["verified"] is False
    with c.websocket_connect(f"/api/cameras/{cam['id']}/live/sub", headers=_ws_headers(c)) as ws:
        ws.send_text(json.dumps({"type": "mse", "value": "avc1.640029"}))
        assert ws.receive_json() == {"type": "mse", "value": 'video/mp4; codecs="avc1.640029"'}
        frames = [ws.receive_bytes() for _ in range(3)]
        assert frames[2] == bytes([0, 0, 0, 2])
        err = ws.receive_json()
        # Upstream error text (which contains credentials) is never forwarded.
        assert err == {"type": "error", "code": "stream.upstream_error"}

    assert fake.streams[f"cam{cam['id']}_sub"] == "rtsp://admin:s3cret@10.0.0.9:554/ch01/1"
    listed = c.get("/api/cameras").json()[0]
    assert listed["verified"] is True and listed["status"] == "online"
    assert "s3cret" not in c.get("/api/cameras").text
    assert "s3cret" not in json.dumps(c.get("/api/diagnostics").json())


def test_only_mse_messages_forwarded(stack: tuple[TestClient, str, FakeGo2rtc]) -> None:
    c, csrf, fake = stack
    cam = _camera(c, csrf)
    with c.websocket_connect(f"/api/cameras/{cam['id']}/live/sub", headers=_ws_headers(c)) as ws:
        ws.send_text(json.dumps({"type": "webrtc/offer", "value": "v=0"}))
        ws.send_text("not json")
        ws.send_text(json.dumps({"type": "mse", "value": ""}))
        ws.receive_json()
    assert fake.client_messages == [json.dumps({"type": "mse", "value": ""})]


def test_ws_requires_same_origin(stack: tuple[TestClient, str, FakeGo2rtc]) -> None:
    c, csrf, _ = stack
    cam = _camera(c, csrf)
    headers = {**_ws_headers(c), "origin": "https://evil.example"}
    with pytest.raises(WebSocketDisconnect) as exc, c.websocket_connect(
        f"/api/cameras/{cam['id']}/live/sub", headers=headers
    ):
        pass
    assert exc.value.code == 4403


def test_ws_requires_session(stack: tuple[TestClient, str, FakeGo2rtc]) -> None:
    c, csrf, _ = stack
    cam = _camera(c, csrf)
    with c.websocket_connect(
        f"/api/cameras/{cam['id']}/live/sub", headers={"origin": "https://testserver"}
    ) as ws:
        assert ws.receive_json() == {"type": "error", "code": "auth.not_authenticated"}


def test_unknown_camera(stack: tuple[TestClient, str, FakeGo2rtc]) -> None:
    c, _, _ = stack
    with c.websocket_connect("/api/cameras/999/live/main", headers=_ws_headers(c)) as ws:
        assert ws.receive_json()["code"] == "camera.not_found"


def test_diagnostics_and_manifest(stack: tuple[TestClient, str, FakeGo2rtc]) -> None:
    c, _, _ = stack
    d = c.get("/api/diagnostics").json()
    assert d["backend"] == "ok" and d["db"] == "ok" and d["go2rtc"] == "ok"
    assert d["streams"]["max"] == 6
    lv = c.get("/manifest.webmanifest", headers={"accept-language": "lv-LV,en;q=0.5"})
    assert lv.headers["content-type"].startswith("application/manifest+json")
    assert lv.json()["name"] == "Kameru panelis" and lv.json()["display"] == "standalone"
    assert c.get("/manifest.webmanifest", headers={"accept-language": "de"}).json()["lang"] == "en"

