from __future__ import annotations

import re
from typing import Any, ClassVar
from urllib.parse import urlsplit

import httpx

from app.providers.base import (
    AccountContext,
    AccountProvider,
    CameraContext,
    Capabilities,
    Diagnostics,
    FieldSpec,
    InvalidConfig,
    Provider,
    ProviderError,
    Quality,
    StreamSource,
    Unsupported,
)
from app.providers.imou_client import DATA_CENTERS, ImouClient

# Hosts the Imou cloud is documented/observed to hand out for live streams.
STREAM_HOST_SUFFIXES = (".lechange.com", ".easy4ip.com", ".imoulife.com", ".imou.com")
_DEVICE_RE = re.compile(r"^[A-Za-z0-9]{4,64}$")
_CHANNEL_RE = re.compile(r"^\d{1,3}$")


def client_for(account: AccountContext, http: httpx.AsyncClient, timeout: float) -> ImouClient:
    async def save(state: dict[str, Any]) -> None:
        account.state = state
        await account.save_state(state)

    return ImouClient(
        http,
        account.config["data_center"],
        account.secrets["app_id"],
        account.secrets["app_secret"],
        timeout,
        account.state,
        save,
    )


class ImouAccountProvider(AccountProvider):
    id: ClassVar[str] = "imou"
    fields: ClassVar[tuple[FieldSpec, ...]] = (
        FieldSpec("data_center", kind="select", options=tuple(DATA_CENTERS), default="fk",
                  required=True),
        FieldSpec("app_id", secret=True, required=True),
        FieldSpec("app_secret", kind="password", secret=True, required=True),
    )

    async def check(self, account: AccountContext, http: httpx.AsyncClient) -> Diagnostics:
        diag = Diagnostics()
        client = client_for(account, http, 15)
        try:
            await client.token(force=True)
            diag.add("auth", "pass")
        except ProviderError as exc:
            diag.add("auth", "fail", exc.code, **exc.detail)
            return diag
        try:
            channels = await client.list_channels()
            diag.add("devices", "pass", channels=len(channels))
        except ProviderError as exc:
            diag.add("devices", "fail", exc.code, **exc.detail)
        return diag

    async def list_devices(
        self, account: AccountContext, http: httpx.AsyncClient
    ) -> list[dict[str, Any]]:
        return [dict(c) for c in await client_for(account, http, 15).list_channels()]


class ImouProvider(Provider):
    id: ClassVar[str] = "imou"
    transport = "cloud"
    account_provider: ClassVar[str | None] = "imou"
    fields: ClassVar[tuple[FieldSpec, ...]] = (
        FieldSpec("device_id", required=True),
        FieldSpec("channel_id", default="0", required=True),
        FieldSpec("battery", kind="checkbox", default=True),
    )

    def register(self, config: dict[str, Any], secrets: dict[str, Any]) -> tuple[
        dict[str, Any], dict[str, Any]
    ]:
        cfg, sec = super().register(config, secrets)
        if not _DEVICE_RE.match(cfg["device_id"]):
            raise InvalidConfig("validation.invalid", field="device_id")
        if not _CHANNEL_RE.match(cfg["channel_id"]):
            raise InvalidConfig("validation.invalid", field="channel_id")
        return cfg, sec

    def _client(self, ctx: CameraContext) -> ImouClient:
        if ctx.account is None:
            raise InvalidConfig("imou.account_required")
        return client_for(ctx.account, ctx.http, ctx.timeout)

    async def get_metadata(self, ctx: CameraContext) -> dict[str, Any]:
        return {"device_id": ctx.config["device_id"], "channel_id": ctx.config["channel_id"]}

    def get_capabilities(self, ctx: CameraContext) -> Capabilities:
        return Capabilities(transport="cloud", battery=bool(ctx.config.get("battery")))

    async def check_connectivity(self, ctx: CameraContext) -> Diagnostics:
        diag = Diagnostics()
        try:
            client = self._client(ctx)
            await client.token()
            diag.add("auth", "pass")
        except ProviderError as exc:
            diag.add("auth", "fail", exc.code, **exc.detail)
            return diag
        dev, ch = ctx.config["device_id"], ctx.config["channel_id"]
        try:
            state = await client.channel_online(dev, ch)
        except ProviderError as exc:
            diag.add("device", "fail", exc.code, **exc.detail)
            return diag
        if state == "1":
            diag.add("device", "pass", state="online")
        elif state == "4":
            diag.add("device", "pass", state="sleeping")
        else:
            diag.add("device", "fail", "imou.offline" if state == "0" else "imou.upgrading")
            return diag
        diag.discovered["imou_state"] = "sleeping" if state == "4" else "online"
        try:
            # Query only: creating a live address or pulling video would wake a battery camera.
            await client.rtmp_live(dev, ch, create=False)
            diag.add("stream_main", "pass", cloud=True, probe="on_live_view")
        except ProviderError as exc:
            if exc.code in ("imou.LV1002", "imou.LV1005"):
                diag.add("stream_main", "skip", "imou.live_created_on_first_view")
            else:
                diag.add("stream_main", "fail", exc.code, **exc.detail)
        return diag

    async def get_stream_source(self, ctx: CameraContext, quality: Quality) -> StreamSource:
        client = self._client(ctx)
        data = await client.rtmp_live(ctx.config["device_id"], ctx.config["channel_id"], True)
        url = str(data.get("rtmpHD" if quality == "main" else "rtmp") or data.get("rtmp") or "")
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme not in ("rtmp", "rtmps") or not host.endswith(STREAM_HOST_SUFFIXES):
            raise Unsupported("imou.unexpected_stream_host")
        return StreamSource(url=url, transport="cloud")
