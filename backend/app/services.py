"""Glue between DB rows, encrypted secrets and providers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.crypto import SecretBox
from app.models import Camera, ProviderAccount
from app.netguard import NetGuard
from app.providers import ACCOUNT_PROVIDERS, PROVIDERS
from app.providers.base import (
    AccountContext,
    AccountProvider,
    CameraContext,
    Diagnostics,
    Provider,
    ProviderError,
)

UNSUPPORTED_CODES = frozenset(
    {"imou.realname_required", "imou.not_permitted", "imou.unexpected_stream_host"}
)
UNREACHABLE_CODES = frozenset(
    {
        "net.tcp_timeout",
        "net.tcp_refused",
        "rtsp.timeout",
        "rtsp.connection_closed",
        "onvif.timeout",
        "onvif.unreachable",
        "imou.offline",
        "imou.sleeping",
        "imou.timeout",
        "imou.unreachable",
    }
)
QUOTA_CODES = frozenset({"imou.quota_exceeded"})


@dataclass
class Runtime:
    box: SecretBox
    guard: NetGuard
    http: httpx.AsyncClient
    timeout: float


def merge_secrets(stored: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Secrets are write-only: an empty/missing field keeps the stored value."""
    merged = dict(stored)
    merged.update({k: v for k, v in incoming.items() if v not in (None, "")})
    return merged


def get_provider(provider_id: str) -> Provider:
    provider = PROVIDERS.get(provider_id)
    if provider is None:
        raise ProviderError("provider.unknown")
    return provider


def get_account_provider(provider_id: str) -> AccountProvider:
    provider = ACCOUNT_PROVIDERS.get(provider_id)
    if provider is None:
        raise ProviderError("provider.unknown")
    return provider


class Services:
    def __init__(self, db: Session, rt: Runtime) -> None:
        self.db = db
        self.rt = rt

    # --- secrets ---------------------------------------------------------------------

    def seal(self, data: dict[str, Any]) -> str:
        return self.rt.box.encrypt(json.dumps(data))

    def unseal(self, blob: str | None) -> dict[str, Any]:
        if not blob:
            return {}
        data: dict[str, Any] = json.loads(self.rt.box.decrypt(blob))
        return data

    # --- accounts --------------------------------------------------------------------

    def account_ctx(
        self, provider: str, config: dict[str, Any], secrets: dict[str, Any],
        row: ProviderAccount | None,
    ) -> AccountContext:
        async def save_state(state: dict[str, Any]) -> None:
            if row is not None:
                row.state_enc = self.seal(state)
                self.db.commit()

        return AccountContext(
            id=row.id if row else 0,
            config=config,
            secrets=secrets,
            state=self.unseal(row.state_enc) if row else {},
            save_state=save_state,
        )

    def stored_account_ctx(self, row: ProviderAccount) -> AccountContext:
        return self.account_ctx(row.provider, row.config, self.unseal(row.secrets_enc), row)

    # --- cameras ---------------------------------------------------------------------

    def camera_ctx(
        self,
        config: dict[str, Any],
        secrets: dict[str, Any],
        discovered: dict[str, Any],
        account: ProviderAccount | None,
    ) -> CameraContext:
        return CameraContext(
            config=config,
            secrets=secrets,
            discovered=discovered,
            guard=self.rt.guard,
            http=self.rt.http,
            timeout=self.rt.timeout,
            account=self.stored_account_ctx(account) if account else None,
        )

    def stored_camera_ctx(self, cam: Camera) -> CameraContext:
        return self.camera_ctx(
            cam.config, self.unseal(cam.secrets_enc), cam.discovered or {}, cam.account
        )

    async def run_test(self, provider: Provider, ctx: CameraContext) -> Diagnostics:
        try:
            return await provider.check_connectivity(ctx)
        except ProviderError as exc:
            diag = Diagnostics()
            diag.add("provider", "fail", exc.code)
            return diag

    def apply_result(self, cam: Camera, diag: Diagnostics) -> None:
        now = datetime.now(UTC)
        cam.last_checked_at = now
        if diag.ok:
            cam.status = "sleeping" if diag.discovered.get("imou_state") == "sleeping" else "online"
            cam.status_code = None
            cam.last_seen_at = now
            cam.discovered = {**(cam.discovered or {}), **diag.discovered}
            return
        err = diag.first_error
        code = err.code if err else "provider.error"
        cam.status_code = code
        if code in UNSUPPORTED_CODES:
            cam.status = "unsupported"
        elif code in UNREACHABLE_CODES and cam.last_seen_at is not None:
            cam.status = "offline"
        elif code in QUOTA_CODES:
            cam.status = "quota"
        else:
            cam.status = "needs_setup"
