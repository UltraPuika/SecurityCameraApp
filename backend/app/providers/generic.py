from __future__ import annotations

import re
from typing import Any, ClassVar
from urllib.parse import quote

from app.netguard import AddressRejected, host_for_url, validate_host_syntax
from app.providers import rtsp
from app.providers.base import (
    AuthFailed,
    CameraContext,
    Capabilities,
    Diagnostics,
    FieldSpec,
    InvalidConfig,
    Provider,
    ProviderError,
    Quality,
    StreamSource,
    Unreachable,
    Unsupported,
)
from app.providers.onvif import OnvifClient, select_channel_profiles

_PATH_RE = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:%/?-]*$")

H265_WARNING = "codec.h265_limited_browser_support"


class GenericRtspProvider(Provider):
    id: ClassVar[str] = "generic"
    transport = "local"
    fields: ClassVar[tuple[FieldSpec, ...]] = (
        FieldSpec("host", required=True),
        FieldSpec("username", secret=True),
        FieldSpec("password", kind="password", secret=True),
        FieldSpec("use_onvif", kind="checkbox", default=True),
        FieldSpec("onvif_port", kind="number", default=80, min=1, max=65535),
        FieldSpec("onvif_https", kind="checkbox", default=False),
        FieldSpec("channel", kind="number", default=1, min=1, max=256),
        FieldSpec("rtsp_port", kind="number", default=554, min=1, max=65535),
        FieldSpec("rtsp_tls", kind="checkbox", default=False),
        FieldSpec("main_path"),
        FieldSpec("sub_path"),
    )

    def register(self, config: dict[str, Any], secrets: dict[str, Any]) -> tuple[
        dict[str, Any], dict[str, Any]
    ]:
        cfg, sec = super().register(config, secrets)
        try:
            cfg["host"] = validate_host_syntax(cfg["host"])
        except AddressRejected as exc:
            raise InvalidConfig(exc.code, field="host") from exc
        for name in ("main_path", "sub_path"):
            if cfg[name] and not _PATH_RE.match(cfg[name]):
                raise InvalidConfig("validation.invalid_path", field=name)
        if not cfg["use_onvif"] and not cfg["main_path"]:
            raise InvalidConfig("validation.required", field="main_path")
        return cfg, sec

    def _path(self, ctx: CameraContext, quality: Quality) -> str | None:
        key = f"{quality}_path"
        path: str | None = ctx.config.get(key) or ctx.discovered.get(key)
        return path

    async def get_metadata(self, ctx: CameraContext) -> dict[str, Any]:
        info: dict[str, Any] = ctx.discovered.get("device_info") or {}
        return info

    def get_capabilities(self, ctx: CameraContext) -> Capabilities:
        streams: tuple[Quality, ...] = ("main", "sub") if self._path(ctx, "sub") else ("main",)
        return Capabilities(transport="local", streams=streams)

    async def check_connectivity(self, ctx: CameraContext) -> Diagnostics:
        cfg, sec, t = ctx.config, ctx.secrets, ctx.timeout
        user, pw = sec.get("username", ""), sec.get("password", "")
        diag = Diagnostics()
        try:
            ip = await ctx.guard.resolve(cfg["host"], cfg["rtsp_port"])
        except AddressRejected as exc:
            diag.add("dns", "fail", exc.code)
            return diag
        diag.add("dns", "pass", ip=ip)

        try:
            await rtsp.tcp_check(ip, cfg["rtsp_port"], t)
            diag.add("tcp", "pass", port=cfg["rtsp_port"])
        except ProviderError as exc:
            diag.add("tcp", "fail", exc.code, port=cfg["rtsp_port"])
            return diag

        paths: dict[str, str | None] = {"main": cfg["main_path"], "sub": cfg["sub_path"]}
        rtsp_port = cfg["rtsp_port"]
        if cfg["use_onvif"]:
            client = OnvifClient(
                ctx.http, ip, cfg["onvif_port"], user, pw, t, https=cfg["onvif_https"]
            )
            try:
                await client.sync_clock()
                info = await client.device_info()
                diag.add("auth", "pass", method="onvif")
                profiles = await client.profiles()
                main, sub = select_channel_profiles(profiles, cfg["channel"])
                # The device-reported RTSP port is ignored: we only connect to the validated one.
                _, main_path = await client.stream_uri(main.token)
                sub_path = (await client.stream_uri(sub.token))[1] if sub else None
                diag.add("onvif", "pass", profiles=len(profiles))
                diag.discovered.update(
                    device_info={k: v for k, v in info.items() if k != "SerialNumber"},
                    main_path=main_path,
                    sub_path=sub_path,
                )
                paths["main"] = paths["main"] or main_path
                paths["sub"] = paths["sub"] or sub_path
            except AuthFailed as exc:
                diag.add("auth", "fail", exc.code, method="onvif")
                return diag
            except ProviderError as exc:
                diag.add("onvif", "fail", exc.code, **exc.detail)
                if not paths["main"]:
                    return diag

        for quality in ("main", "sub"):
            path = paths[quality]
            if not path:
                if quality == "main":
                    diag.add("stream_main", "fail", "stream.path_unknown")
                else:
                    diag.add("stream_sub", "skip", "stream.no_substream")
                continue
            try:
                probe = await rtsp.describe(ip, rtsp_port, path, user, pw, t, cfg["rtsp_tls"])
            except AuthFailed as exc:
                diag.add("auth", "fail", exc.code, method="rtsp")
                return diag
            except ProviderError as exc:
                diag.add(f"stream_{quality}", "fail", exc.code, **exc.detail)
                continue
            if not any(s.name == "auth" for s in diag.steps):
                diag.add("auth", "pass", method="rtsp")
            warnings = [H265_WARNING] if probe.codec == "H265" else []
            diag.add(f"stream_{quality}", "pass", **probe.as_dict(), warnings=warnings)
            diag.discovered[f"{quality}_probe"] = probe.as_dict()
        return diag

    async def get_stream_source(self, ctx: CameraContext, quality: Quality) -> StreamSource:
        path = self._path(ctx, quality) or (self._path(ctx, "main") if quality == "sub" else None)
        if not path:
            raise Unsupported("stream.path_unknown")
        try:
            ip = await ctx.guard.resolve(ctx.config["host"], ctx.config["rtsp_port"])
        except AddressRejected as exc:
            raise Unreachable(exc.code) from exc
        user = quote(ctx.secrets.get("username", ""), safe="")
        pw = quote(ctx.secrets.get("password", ""), safe="")
        auth = f"{user}:{pw}@" if user else ""
        scheme = "rtsps" if ctx.config["rtsp_tls"] else "rtsp"
        url = f"{scheme}://{auth}{host_for_url(ip)}:{ctx.config['rtsp_port']}{path}"
        return StreamSource(url=url, transport="local")


class BitVisionProvider(GenericRtspProvider):
    """Herospeed/Longse (BitVision app) NVRs and IPCs: preset ports, channel-based ONVIF."""

    id: ClassVar[str] = "bitvision"
    fields: ClassVar[tuple[FieldSpec, ...]] = (
        FieldSpec("host", required=True),
        FieldSpec("channel", kind="number", default=1, min=1, max=64, required=True),
        FieldSpec("username", secret=True, default="admin"),
        FieldSpec("password", kind="password", secret=True, required=True),
        FieldSpec("use_onvif", kind="checkbox", default=True),
        FieldSpec("onvif_port", kind="number", default=80, min=1, max=65535),
        FieldSpec("onvif_https", kind="checkbox", default=False),
        FieldSpec("rtsp_port", kind="number", default=554, min=1, max=65535),
        FieldSpec("rtsp_tls", kind="checkbox", default=False),
        FieldSpec("main_path"),
        FieldSpec("sub_path"),
    )
    # Factory default documented in the BitVision Wi-Fi kit manual.
    DEFAULT_PASSWORDS: ClassVar[frozenset[str]] = frozenset({"12345", "123456", "admin"})

    def register(self, config: dict[str, Any], secrets: dict[str, Any]) -> tuple[
        dict[str, Any], dict[str, Any]
    ]:
        cfg, sec = super().register(config, secrets)
        if sec.get("password") in self.DEFAULT_PASSWORDS:
            raise InvalidConfig("bitvision.default_password", field="password")
        return cfg, sec
