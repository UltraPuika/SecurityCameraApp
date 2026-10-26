from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

import httpx

from app.netguard import NetGuard

Quality = Literal["main", "sub"]
Transport = Literal["local", "cloud"]
FieldKind = Literal["text", "password", "number", "select", "checkbox"]
StepStatus = Literal["pass", "fail", "skip"]


class ProviderError(Exception):
    code = "provider.error"

    def __init__(self, code: str | None = None, **detail: Any) -> None:
        self.code = code or type(self).code
        self.detail = detail
        super().__init__(self.code)


class InvalidConfig(ProviderError):
    code = "provider.invalid_config"


class Unsupported(ProviderError):
    code = "provider.unsupported"


class AuthFailed(ProviderError):
    code = "provider.auth_failed"


class Unreachable(ProviderError):
    code = "provider.unreachable"


class Timeout(ProviderError):
    code = "provider.timeout"


class QuotaExceeded(ProviderError):
    code = "provider.quota_exceeded"


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: FieldKind = "text"
    required: bool = False
    secret: bool = False
    default: str | int | bool | None = None
    options: tuple[str, ...] = ()
    min: int | None = None
    max: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "required": self.required,
            "secret": self.secret,
            "default": self.default,
            "options": list(self.options),
            "min": self.min,
            "max": self.max,
        }


@dataclass
class StreamProbe:
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"codec": self.codec, "width": self.width, "height": self.height, "fps": self.fps}


@dataclass
class Step:
    name: str
    status: StepStatus
    code: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Diagnostics:
    steps: list[Step] = field(default_factory=list)
    # Non-secret facts learned during the test (e.g. discovered stream paths, codec).
    discovered: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(s.status != "fail" for s in self.steps)

    @property
    def first_error(self) -> Step | None:
        return next((s for s in self.steps if s.status == "fail"), None)

    def add(self, name: str, status: StepStatus, code: str | None = None, **detail: Any) -> None:
        self.steps.append(Step(name, status, code, detail))

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "steps": [
                {"name": s.name, "status": s.status, "code": s.code, "detail": s.detail}
                for s in self.steps
            ],
            "discovered": self.discovered,
        }


@dataclass(frozen=True)
class Capabilities:
    transport: Transport
    streams: tuple[Quality, ...] = ("main", "sub")
    snapshot: bool = False
    battery: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "transport": self.transport,
            "streams": list(self.streams),
            "snapshot": self.snapshot,
            "battery": self.battery,
        }


@dataclass(frozen=True)
class StreamSource:
    """Upstream URL for go2rtc. Contains credentials: server-side only, never logged."""

    url: str
    transport: Transport


@dataclass
class AccountContext:
    id: int
    config: dict[str, Any]
    secrets: dict[str, Any]
    state: dict[str, Any]
    save_state: Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class CameraContext:
    config: dict[str, Any]
    secrets: dict[str, Any]
    discovered: dict[str, Any]
    guard: NetGuard
    http: httpx.AsyncClient
    timeout: float
    account: AccountContext | None = None


class Provider(ABC):
    id: ClassVar[str]
    transport: ClassVar[Transport]
    fields: ClassVar[tuple[FieldSpec, ...]]
    account_provider: ClassVar[str | None] = None

    def register(self, config: dict[str, Any], secrets: dict[str, Any]) -> tuple[
        dict[str, Any], dict[str, Any]
    ]:
        """Validate and normalise a camera's settings before they are stored."""
        return normalise_fields(self.fields, config, secrets)

    @abstractmethod
    async def get_metadata(self, ctx: CameraContext) -> dict[str, Any]: ...

    @abstractmethod
    async def check_connectivity(self, ctx: CameraContext) -> Diagnostics: ...

    @abstractmethod
    def get_capabilities(self, ctx: CameraContext) -> Capabilities: ...

    @abstractmethod
    async def get_stream_source(self, ctx: CameraContext, quality: Quality) -> StreamSource: ...

    async def get_snapshot(self, ctx: CameraContext) -> bytes:
        raise Unsupported("provider.snapshot_unsupported")


class AccountProvider(ABC):
    """Cloud account (e.g. Imou developer app) shared by several cameras."""

    id: ClassVar[str]
    fields: ClassVar[tuple[FieldSpec, ...]]

    def register(self, config: dict[str, Any], secrets: dict[str, Any]) -> tuple[
        dict[str, Any], dict[str, Any]
    ]:
        return normalise_fields(self.fields, config, secrets)

    @abstractmethod
    async def check(self, account: AccountContext, http: httpx.AsyncClient) -> Diagnostics: ...

    @abstractmethod
    async def list_devices(
        self, account: AccountContext, http: httpx.AsyncClient
    ) -> list[dict[str, Any]]: ...


def normalise_fields(
    specs: tuple[FieldSpec, ...], config: dict[str, Any], secrets: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    known = {s.name for s in specs}
    unknown = (set(config) | set(secrets)) - known
    if unknown:
        raise InvalidConfig("validation.unknown_field", fields=sorted(unknown))
    out_cfg: dict[str, Any] = {}
    out_sec: dict[str, Any] = {}
    for spec in specs:
        source = secrets if spec.secret else config
        value = source.get(spec.name, spec.default)
        if spec.kind == "number":
            if value in (None, ""):
                value = None
            else:
                try:
                    value = int(str(value))
                except (TypeError, ValueError) as exc:
                    raise InvalidConfig("validation.invalid", field=spec.name) from exc
                if (spec.min is not None and value < spec.min) or (
                    spec.max is not None and value > spec.max
                ):
                    raise InvalidConfig("validation.out_of_range", field=spec.name)
        elif spec.kind == "checkbox":
            value = bool(value)
        else:
            value = "" if value is None else str(value).strip()
            if len(value) > 512 or any(c in value for c in "\r\n\x00"):
                raise InvalidConfig("validation.invalid", field=spec.name)
            if spec.kind == "select" and value and value not in spec.options:
                raise InvalidConfig("validation.invalid", field=spec.name)
        if spec.required and value in (None, ""):
            raise InvalidConfig("validation.required", field=spec.name)
        (out_sec if spec.secret else out_cfg)[spec.name] = value
    return out_cfg, out_sec
