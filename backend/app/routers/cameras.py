from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps import AdminUser, CurrentUser, ServicesDep
from app.errors import ApiError, from_provider
from app.models import Camera, ProviderAccount, Role
from app.netguard import AddressRejected
from app.providers import ACCOUNT_PROVIDERS, PROVIDERS
from app.providers.base import Provider, ProviderError
from app.providers.onvif import ws_discover
from app.services import Services, get_provider, merge_secrets

router = APIRouter(prefix="/api", tags=["cameras"])

ConfigValue = str | int | bool | None


class CameraIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    location: str = Field(default="", max_length=100)
    group: str = Field(default="", max_length=100)
    provider: str = Field(min_length=1, max_length=32)
    account_id: int | None = None
    favourite: bool = False
    config: dict[str, ConfigValue] = Field(default_factory=dict, max_length=32)
    secrets: dict[str, str | None] = Field(default_factory=dict, max_length=16)


class CameraTestIn(CameraIn):
    name: str = Field(default="test", max_length=100)
    camera_id: int | None = None


class CameraOut(BaseModel):
    id: int
    name: str
    location: str
    group: str
    provider: str
    account_id: int | None
    favourite: bool
    transport: str
    capabilities: dict[str, Any]
    status: str
    status_code: str | None
    last_seen_at: datetime | None
    last_checked_at: datetime | None
    verified: bool
    probe: dict[str, Any]
    # Admin-only: non-secret settings and which secret fields are stored.
    config: dict[str, Any] | None = None
    secrets_set: list[str] | None = None


def _out(svc: Services, cam: Camera, admin: bool) -> CameraOut:
    provider = PROVIDERS.get(cam.provider)
    discovered = cam.discovered or {}
    caps: dict[str, Any] = {}
    if provider is not None:
        caps = provider.get_capabilities(svc.camera_ctx(cam.config, {}, discovered, None)).as_dict()
    probe = {k: discovered[k] for k in ("main_probe", "sub_probe") if k in discovered}
    out = CameraOut(
        id=cam.id,
        name=cam.name,
        location=cam.location,
        group=cam.group,
        provider=cam.provider,
        account_id=cam.account_id,
        favourite=cam.favourite,
        transport=provider.transport if provider else "local",
        capabilities=caps,
        status=cam.status,
        status_code=cam.status_code,
        last_seen_at=cam.last_seen_at,
        last_checked_at=cam.last_checked_at,
        verified=cam.verified,
        probe=probe,
    )
    if admin:
        out.config = cam.config
        out.secrets_set = sorted(k for k, v in svc.unseal(cam.secrets_enc).items() if v)
    return out


def _load(svc: Services, camera_id: int) -> Camera:
    cam = svc.db.get(Camera, camera_id)
    if cam is None:
        raise ApiError(404, "camera.not_found")
    return cam


def _account(svc: Services, provider: Provider, account_id: int | None) -> ProviderAccount | None:
    if provider.account_provider is None:
        return None
    acc = svc.db.get(ProviderAccount, account_id) if account_id is not None else None
    if acc is None or acc.provider != provider.account_provider:
        raise ApiError(422, "camera.account_required", detail={"field": "account_id"})
    return acc


def _prepare(
    svc: Services, body: CameraIn, stored: Camera | None
) -> tuple[Provider, dict[str, Any], dict[str, Any], ProviderAccount | None]:
    try:
        provider = get_provider(body.provider)
    except ProviderError as exc:
        raise from_provider(exc) from exc
    if stored is not None and stored.provider != body.provider:
        raise ApiError(422, "camera.provider_immutable")
    secrets = merge_secrets(svc.unseal(stored.secrets_enc) if stored else {}, body.secrets)
    try:
        cfg, sec = provider.register(dict(body.config), secrets)
    except ProviderError as exc:
        raise from_provider(exc) from exc
    return provider, cfg, sec, _account(svc, provider, body.account_id)


@router.get("/providers")
def list_providers(_u: CurrentUser) -> dict[str, Any]:
    return {
        "cameras": [
            {
                "id": p.id,
                "transport": p.transport,
                "account_provider": p.account_provider,
                "fields": [f.as_dict() for f in p.fields],
            }
            for p in PROVIDERS.values()
        ],
        "accounts": [
            {"id": p.id, "fields": [f.as_dict() for f in p.fields]}
            for p in ACCOUNT_PROVIDERS.values()
        ],
    }


@router.get("/cameras")
def list_cameras(user: CurrentUser, svc: ServicesDep) -> list[CameraOut]:
    cams = svc.db.scalars(select(Camera).order_by(Camera.sort_order, Camera.name)).all()
    return [_out(svc, c, user.role == Role.admin) for c in cams]


@router.post("/cameras/test")
async def test_camera(body: CameraTestIn, _a: AdminUser, svc: ServicesDep) -> dict[str, Any]:
    stored = _load(svc, body.camera_id) if body.camera_id is not None else None
    provider, cfg, sec, acc = _prepare(svc, body, stored)
    discovered = stored.discovered if stored else {}
    diag = await svc.run_test(provider, svc.camera_ctx(cfg, sec, discovered or {}, acc))
    return diag.as_dict()


@router.post("/cameras", status_code=201)
async def create_camera(body: CameraIn, _a: AdminUser, svc: ServicesDep) -> CameraOut:
    provider, cfg, sec, acc = _prepare(svc, body, None)
    cam = Camera(
        name=body.name,
        location=body.location.strip(),
        group=body.group.strip(),
        provider=provider.id,
        account_id=acc.id if acc else None,
        favourite=body.favourite,
        config=cfg,
        secrets_enc=svc.seal(sec),
        discovered={},
        status="unknown",
    )
    svc.db.add(cam)
    svc.db.flush()
    svc.apply_result(cam, await svc.run_test(provider, svc.camera_ctx(cfg, sec, {}, acc)))
    svc.db.commit()
    return _out(svc, cam, True)


@router.put("/cameras/{camera_id}")
async def update_camera(
    camera_id: int, body: CameraIn, request: Request, _a: AdminUser, svc: ServicesDep
) -> CameraOut:
    cam = _load(svc, camera_id)
    provider, cfg, sec, acc = _prepare(svc, body, cam)
    connection_changed = cfg != cam.config or sec != svc.unseal(cam.secrets_enc)
    cam.name = body.name
    cam.location = body.location.strip()
    cam.group = body.group.strip()
    cam.favourite = body.favourite
    cam.account_id = acc.id if acc else None
    if connection_changed:
        await request.app.state.streams.drop(cam.id)
        cam.config = cfg
        cam.secrets_enc = svc.seal(sec)
        cam.discovered = {}
        cam.verified = False
        svc.apply_result(cam, await svc.run_test(provider, svc.camera_ctx(cfg, sec, {}, acc)))
    svc.db.commit()
    return _out(svc, cam, True)


@router.delete("/cameras/{camera_id}", status_code=204)
async def delete_camera(
    camera_id: int, request: Request, _a: AdminUser, svc: ServicesDep
) -> None:
    cam = _load(svc, camera_id)
    await request.app.state.streams.drop(cam.id)
    svc.db.delete(cam)
    svc.db.commit()


@router.post("/cameras/{camera_id}/test")
async def retest_camera(camera_id: int, _a: AdminUser, svc: ServicesDep) -> dict[str, Any]:
    cam = _load(svc, camera_id)
    try:
        provider = get_provider(cam.provider)
    except ProviderError as exc:
        raise from_provider(exc) from exc
    diag = await svc.run_test(provider, svc.stored_camera_ctx(cam))
    svc.apply_result(cam, diag)
    svc.db.commit()
    return {**diag.as_dict(), "camera": _out(svc, cam, True).model_dump(mode="json")}


@router.post("/onvif/discover")
async def discover(_a: AdminUser, svc: ServicesDep) -> list[dict[str, Any]]:
    found = []
    for dev in await ws_discover():
        try:
            await svc.rt.guard.resolve(dev["ip"], dev["onvif_port"])
        except AddressRejected:
            continue
        found.append(dev)
    return found
