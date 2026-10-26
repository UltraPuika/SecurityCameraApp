"""Imou Open Platform HTTP client (documented endpoints only)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.providers.base import (
    AuthFailed,
    InvalidConfig,
    ProviderError,
    QuotaExceeded,
    Timeout,
    Unreachable,
    Unsupported,
)

DATA_CENTERS = {
    "sg": "https://openapi-sg.easy4ip.com",
    "fk": "https://openapi-fk.easy4ip.com",
    "or": "https://openapi-or.easy4ip.com",
}
TOKEN_REFRESH_MARGIN = 3600

_QUOTA = {"OP1011", "OP1013", "OP1014", "OP1016", "FL1001", "FL1002", "FL1003", "FL1004", "FL1005"}
_AUTH = {"SN1001", "SN1004", "OP1008", "OP1010", "TK1003"}
_TOKEN_EXPIRED = {"TK1002"}
_NOT_FOUND = {"DV1002", "DV1011", "DV1028", "OP1015"}


def calc_sign(ts: int, nonce: str, app_secret: str) -> str:
    password = hashlib.sha256(app_secret.encode()).hexdigest().lower()
    template = f"time:{ts},nonce:{nonce},appSecret:{app_secret}"
    digest = hmac.new(password.encode(), template.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


class ImouApiError(ProviderError):
    pass


def map_error(code: str) -> ProviderError:
    if code in _QUOTA:
        return QuotaExceeded("imou.quota_exceeded", vendor_code=code)
    if code in _AUTH:
        return AuthFailed("imou.auth_failed", vendor_code=code)
    if code in ("DV1007", "DV1020"):
        return Unreachable("imou.offline")
    if code == "DV1030":
        return Unreachable("imou.sleeping")
    if code in _NOT_FOUND:
        return InvalidConfig("imou.device_not_found")
    if code == "LV1008":
        return Unsupported("imou.realname_required")
    if code in ("OP1009", "OP1012", "DV1019", "DV1026"):
        return Unsupported("imou.not_permitted", vendor_code=code)
    return ImouApiError(f"imou.{code}", vendor_code=code)


class ImouClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        data_center: str,
        app_id: str,
        app_secret: str,
        timeout: float,
        state: dict[str, Any],
        save_state: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if data_center not in DATA_CENTERS:
            raise InvalidConfig("validation.invalid", field="data_center")
        self.http = http
        self.base = DATA_CENTERS[data_center]
        self.app_id = app_id
        self.app_secret = app_secret
        self.timeout = timeout
        self.state = state
        self.save_state = save_state

    async def _raw(self, method: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        ts = int(time.time())
        nonce = uuid.uuid4().hex
        body = {
            "system": {
                "ver": "1.0",
                "appId": self.app_id,
                "sign": calc_sign(ts, nonce, self.app_secret),
                "time": ts,
                "nonce": nonce,
            },
            "id": str(uuid.uuid4()),
            "params": params,
        }
        try:
            resp = await self.http.post(
                f"{self.base}/openapi/{method}",
                json=body,
                timeout=self.timeout,
                follow_redirects=False,
            )
        except httpx.TimeoutException as exc:
            raise Timeout("imou.timeout") from exc
        except httpx.HTTPError as exc:
            raise Unreachable("imou.unreachable") from exc
        if resp.status_code != 200:
            raise Unreachable("imou.http_error", http_status=resp.status_code)
        try:
            result = resp.json()["result"]
            code = str(result["code"])
        except (ValueError, KeyError, TypeError) as exc:
            raise Unreachable("imou.bad_response") from exc
        data = result.get("data") or {}
        return code, data if isinstance(data, dict) else {}

    async def token(self, force: bool = False) -> str:
        cached = self.state.get("token")
        remaining = self.state.get("expires_at", 0) - time.time()
        if not force and cached and remaining > TOKEN_REFRESH_MARGIN:
            return str(cached)
        code, data = await self._raw("accessToken", {})
        if code != "0":
            raise map_error(code)
        token = str(data.get("accessToken", ""))
        if not token:
            raise Unreachable("imou.bad_response")
        self.state = {"token": token, "expires_at": time.time() + int(data.get("expireTime", 0))}
        await self.save_state(self.state)
        return token

    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(2):
            token = await self.token(force=attempt > 0)
            code, data = await self._raw(method, {**params, "token": token})
            if code == "0":
                return data
            if code in _TOKEN_EXPIRED and attempt == 0:
                continue
            raise map_error(code)
        raise AuthFailed("imou.auth_failed", vendor_code="TK1002")

    async def list_channels(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        bind_id = -1
        for _ in range(50):
            data = await self.call(
                "deviceBaseList",
                {"bindId": bind_id, "limit": 128, "type": "bindAndShare", "needApInfo": False},
            )
            devices = data.get("deviceList") or []
            for dev in devices:
                for ch in dev.get("channels") or []:
                    out.append(
                        {
                            "device_id": str(dev.get("deviceId", "")),
                            "channel_id": str(ch.get("channelId", "")),
                            "name": str(ch.get("channelName", "")),
                        }
                    )
            if len(devices) < 128:
                break
            bind_id = int(devices[-1].get("bindId", 0))
        return out

    async def channel_online(self, device_id: str, channel_id: str) -> str:
        data = await self.call("deviceOnline", {"deviceId": device_id})
        for ch in data.get("channels") or []:
            if str(ch.get("channelId")) == channel_id:
                return str(ch.get("onLine", "0"))
        raise InvalidConfig("imou.channel_not_found")

    async def rtmp_live(self, device_id: str, channel_id: str, create: bool) -> dict[str, Any]:
        params = {"deviceId": device_id, "channelId": channel_id}
        try:
            return await self.call("queryDeviceRtmpLive", params)
        except ImouApiError as exc:
            if not create or exc.code not in ("imou.LV1002", "imou.LV1005"):
                raise
        return await self.call("createDeviceRtmpLive", params)
