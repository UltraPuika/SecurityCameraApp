from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps import AdminUser, ServicesDep
from app.errors import ApiError, from_provider
from app.models import Camera, ProviderAccount
from app.providers.base import AccountProvider, ProviderError
from app.services import Services, get_account_provider, merge_secrets

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider: str = Field(min_length=1, max_length=32)
    config: dict[str, str | int | bool | None] = Field(default_factory=dict, max_length=16)
    secrets: dict[str, str | None] = Field(default_factory=dict, max_length=16)


class AccountTestIn(AccountIn):
    name: str = Field(default="test", max_length=100)
    account_id: int | None = None


class AccountOut(BaseModel):
    id: int
    name: str
    provider: str
    config: dict[str, Any]
    secrets_set: list[str]


def _out(svc: Services, acc: ProviderAccount) -> AccountOut:
    return AccountOut(
        id=acc.id,
        name=acc.name,
        provider=acc.provider,
        config=acc.config,
        secrets_set=sorted(k for k, v in svc.unseal(acc.secrets_enc).items() if v),
    )


def _load(svc: Services, account_id: int) -> ProviderAccount:
    acc = svc.db.get(ProviderAccount, account_id)
    if acc is None:
        raise ApiError(404, "account.not_found")
    return acc


def _prepare(
    svc: Services, body: AccountIn, stored: ProviderAccount | None
) -> tuple[AccountProvider, dict[str, Any], dict[str, Any]]:
    try:
        provider = get_account_provider(body.provider)
        if stored is not None and stored.provider != body.provider:
            raise ApiError(422, "account.provider_immutable")
        secrets = merge_secrets(svc.unseal(stored.secrets_enc) if stored else {}, body.secrets)
        cfg, sec = provider.register(dict(body.config), secrets)
    except ProviderError as exc:
        raise from_provider(exc) from exc
    return provider, cfg, sec


@router.get("")
def list_accounts(_a: AdminUser, svc: ServicesDep) -> list[AccountOut]:
    rows = svc.db.scalars(select(ProviderAccount).order_by(ProviderAccount.name)).all()
    return [_out(svc, a) for a in rows]


@router.post("/test")
async def test_account(body: AccountTestIn, _a: AdminUser, svc: ServicesDep) -> dict[str, Any]:
    stored = _load(svc, body.account_id) if body.account_id is not None else None
    provider, cfg, sec = _prepare(svc, body, stored)
    same_credentials = stored is not None and sec == svc.unseal(stored.secrets_enc)
    ctx = svc.account_ctx(provider.id, cfg, sec, stored if same_credentials else None)
    return (await provider.check(ctx, svc.rt.http)).as_dict()


@router.post("", status_code=201)
def create_account(body: AccountIn, _a: AdminUser, svc: ServicesDep) -> AccountOut:
    provider, cfg, sec = _prepare(svc, body, None)
    acc = ProviderAccount(
        name=body.name, provider=provider.id, config=cfg, secrets_enc=svc.seal(sec)
    )
    svc.db.add(acc)
    svc.db.commit()
    return _out(svc, acc)


@router.put("/{account_id}")
def update_account(account_id: int, body: AccountIn, _a: AdminUser, svc: ServicesDep) -> AccountOut:
    acc = _load(svc, account_id)
    _, cfg, sec = _prepare(svc, body, acc)
    if cfg != acc.config or sec != svc.unseal(acc.secrets_enc):
        acc.state_enc = None  # cached token belongs to the old credentials
    acc.name, acc.config, acc.secrets_enc = body.name, cfg, svc.seal(sec)
    svc.db.commit()
    return _out(svc, acc)


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, _a: AdminUser, svc: ServicesDep) -> None:
    acc = _load(svc, account_id)
    if svc.db.scalar(select(Camera.id).where(Camera.account_id == acc.id).limit(1)) is not None:
        raise ApiError(409, "account.in_use")
    svc.db.delete(acc)
    svc.db.commit()


@router.get("/{account_id}/devices")
async def list_devices(account_id: int, _a: AdminUser, svc: ServicesDep) -> list[dict[str, Any]]:
    acc = _load(svc, account_id)
    provider = get_account_provider(acc.provider)
    try:
        devices = await provider.list_devices(svc.stored_account_ctx(acc), svc.rt.http)
    except ProviderError as exc:
        raise from_provider(exc, 502) from exc
    existing = {
        (c.config.get("device_id"), c.config.get("channel_id"))
        for c in svc.db.scalars(select(Camera).where(Camera.account_id == acc.id))
    }
    return [{**d, "added": (d["device_id"], d["channel_id"]) in existing} for d in devices]
