import asyncio
import json
from typing import Any

import httpx
import pytest

from app.providers.base import (
    AccountContext,
    AuthFailed,
    CameraContext,
    QuotaExceeded,
    Unsupported,
)
from app.providers.imou import ImouAccountProvider, ImouProvider
from app.providers.imou_client import ImouClient, calc_sign
from tests.fakes import PermissiveGuard


def test_sign_matches_official_test_vector() -> None:
    # Values from https://open.imoulife.com/book/http/develop.html section 4.3
    sign = calc_sign(1706511734, "f5a1ae2d-c09c-4d39-a744-83a5c2c653c2", "test123456789test123456789")
    assert sign == "xjhCQBoJ9hRDsCjyDcHjtDNzRZ3ZJezcawsfWeiaoxU="


class FakeImou:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.tokens_issued = 0
        self.expire_next_call = False
        self.online = "1"
        self.live: dict[str, str] | None = None
        self.quota_on: str | None = None

    def ok(self, data: dict[str, Any]) -> httpx.Response:
        return httpx.Response(200, json={"result": {"code": "0", "msg": "ok", "data": data}})

    def err(self, code: str) -> httpx.Response:
        return httpx.Response(200, json={"result": {"code": code, "msg": "x"}})

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "openapi-fk.easy4ip.com"
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content)
        assert body["system"]["appId"] == "app-id"
        assert body["system"]["sign"] == calc_sign(
            body["system"]["time"], body["system"]["nonce"], "app-secret"
        )
        self.calls.append(method)
        if method == "accessToken":
            self.tokens_issued += 1
            return self.ok({"accessToken": f"At_{self.tokens_issued}", "expireTime": 259200})
        if self.expire_next_call:
            self.expire_next_call = False
            return self.err("TK1002")
        if self.quota_on == method:
            return self.err("OP1011")
        if method == "deviceOnline":
            return self.ok({"deviceId": "BASE1", "onLine": "1",
                            "channels": [{"channelId": "0", "onLine": self.online},
                                         {"channelId": "1", "onLine": "4"}]})
        if method == "deviceBaseList":
            return self.ok({"count": 1, "deviceList": [{"bindId": 7, "deviceId": "BASE1",
                            "channels": [{"channelId": "0", "channelName": "Gate"},
                                         {"channelId": "1", "channelName": "Yard"}]}]})
        if method == "queryDeviceRtmpLive":
            return self.ok(self.live) if self.live else self.err("LV1002")
        if method == "createDeviceRtmpLive":
            self.live = {"rtmp": "rtmp://cmgw-fk.lechange.com:1935/live/sd",
                         "rtmpHD": "rtmp://cmgw-fk.lechange.com:1935/live/hd"}
            return self.ok(self.live)
        return self.err("OP1005")


def _account(state: dict[str, Any] | None = None) -> tuple[AccountContext, list[dict[str, Any]]]:
    saved: list[dict[str, Any]] = []

    async def save(s: dict[str, Any]) -> None:
        saved.append(s)

    return AccountContext(1, {"data_center": "fk"}, {"app_id": "app-id", "app_secret": "app-secret"},
                          state or {}, save), saved


def _ctx(fake: FakeImou, http: httpx.AsyncClient, channel: str = "0") -> CameraContext:
    acc, _ = _account()
    return CameraContext({"device_id": "BASE1", "channel_id": channel, "battery": True},
                         {}, {}, PermissiveGuard(), http, 5, acc)


def _http(fake: FakeImou) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))


def test_token_cached_and_refreshed_on_tk1002() -> None:
    fake = FakeImou()

    async def go() -> None:
        async with _http(fake) as http:
            acc, saved = _account()
            client = ImouClient(http, "fk", "app-id", "app-secret", 5, acc.state, acc.save_state)
            await client.call("deviceOnline", {"deviceId": "BASE1"})
            await client.call("deviceOnline", {"deviceId": "BASE1"})
            assert fake.tokens_issued == 1
            fake.expire_next_call = True
            await client.call("deviceOnline", {"deviceId": "BASE1"})
            assert fake.tokens_issued == 2
            assert len(saved) == 2 and saved[-1]["token"] == "At_2"

    asyncio.run(go())


def test_quota_maps_to_typed_error() -> None:
    fake = FakeImou()
    fake.quota_on = "deviceOnline"

    async def go() -> None:
        async with _http(fake) as http:
            client = ImouClient(http, "fk", "app-id", "app-secret", 5, {}, _noop)
            with pytest.raises(QuotaExceeded) as exc:
                await client.call("deviceOnline", {"deviceId": "BASE1"})
            assert exc.value.code == "imou.quota_exceeded"
            assert exc.value.detail == {"vendor_code": "OP1011"}

    asyncio.run(go())


async def _noop(_s: dict[str, Any]) -> None:
    return None


def test_bad_secret_is_auth_failure() -> None:
    async def go() -> None:
        http = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"result": {"code": "SN1001", "msg": "x"}})))
        async with http:
            with pytest.raises(AuthFailed):
                await ImouClient(http, "fk", "a", "b", 5, {}, _noop).token()

    asyncio.run(go())


def test_check_connectivity_online_and_sleeping_without_waking() -> None:
    fake = FakeImou()

    async def go() -> None:
        async with _http(fake) as http:
            diag = await ImouProvider().check_connectivity(_ctx(fake, http, "0"))
            assert diag.ok
            assert [s.name for s in diag.steps] == ["auth", "device", "stream_main"]
            assert diag.steps[2].status == "skip"
            diag = await ImouProvider().check_connectivity(_ctx(fake, http, "1"))
            assert diag.ok and diag.discovered["imou_state"] == "sleeping"
            # A test must never create a live address (that would wake/charge quota).
            assert "createDeviceRtmpLive" not in fake.calls

    asyncio.run(go())


def test_offline_channel_fails() -> None:
    fake = FakeImou()
    fake.online = "0"

    async def go() -> None:
        async with _http(fake) as http:
            diag = await ImouProvider().check_connectivity(_ctx(fake, http))
            assert not diag.ok and diag.first_error and diag.first_error.code == "imou.offline"

    asyncio.run(go())


def test_stream_source_creates_live_and_picks_quality() -> None:
    fake = FakeImou()

    async def go() -> None:
        async with _http(fake) as http:
            main = await ImouProvider().get_stream_source(_ctx(fake, http), "main")
            sub = await ImouProvider().get_stream_source(_ctx(fake, http), "sub")
            assert main.url.endswith("/hd") and sub.url.endswith("/sd")
            assert main.transport == "cloud"

    asyncio.run(go())


def test_stream_source_rejects_unexpected_host() -> None:
    fake = FakeImou()
    fake.live = {"rtmp": "rtmp://169.254.169.254/x", "rtmpHD": "rtmp://evil.example/x"}

    async def go() -> None:
        async with _http(fake) as http:
            with pytest.raises(Unsupported) as exc:
                await ImouProvider().get_stream_source(_ctx(fake, http), "main")
            assert exc.value.code == "imou.unexpected_stream_host"

    asyncio.run(go())


def test_account_lists_channels() -> None:
    fake = FakeImou()

    async def go() -> None:
        async with _http(fake) as http:
            acc, _ = _account()
            devices = await ImouAccountProvider().list_devices(acc, http)
            assert devices == [
                {"device_id": "BASE1", "channel_id": "0", "name": "Gate"},
                {"device_id": "BASE1", "channel_id": "1", "name": "Yard"},
            ]

    asyncio.run(go())
