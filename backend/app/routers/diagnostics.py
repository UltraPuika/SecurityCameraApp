from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from app import logbuffer, sysinfo
from app.deps import AdminUser, ServicesDep
from app.models import Camera, ProviderAccount
from app.streams import StreamManager

router = APIRouter(tags=["diagnostics"])

MANIFEST_TEXT = {
    "en": {"name": "Camera dashboard", "short_name": "Cameras",
           "description": "Private dashboard for your security cameras"},
    "lv": {"name": "Kameru panelis", "short_name": "Kameras",
           "description": "Privāts jūsu drošības kameru panelis"},
}


@router.get("/api/diagnostics")
async def diagnostics(request: Request, _a: AdminUser, svc: ServicesDep) -> dict[str, Any]:
    streams: StreamManager = request.app.state.streams
    try:
        svc.db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    cams = svc.db.scalars(select(Camera).order_by(Camera.name)).all()
    accounts = svc.db.scalars(select(ProviderAccount).order_by(ProviderAccount.name)).all()
    return {
        "backend": "ok",
        "db": "ok" if db_ok else "error",
        "go2rtc": "ok" if await streams.healthy() else "error",
        "streams": {
            "max": streams.max_streams,
            "idle_seconds": streams.idle_seconds,
            "active": [
                {"camera_id": s.camera_id, "quality": s.quality, "viewers": s.viewers,
                 "transport": s.transport, "started_at": s.started_at}
                for s in streams.active.values()
            ],
        },
        "cameras": [
            {"id": c.id, "name": c.name, "provider": c.provider, "status": c.status,
             "status_code": c.status_code, "verified": c.verified,
             "last_checked_at": c.last_checked_at, "last_seen_at": c.last_seen_at}
            for c in cams
        ],
        "accounts": [{"id": a.id, "name": a.name, "provider": a.provider} for a in accounts],
        "system": await sysinfo.snapshot(),
        "logs": list(logbuffer.install().records)[-100:],
    }


@router.get("/manifest.webmanifest", include_in_schema=False)
def manifest(request: Request) -> JSONResponse:
    accept = request.headers.get("accept-language", "").lower()
    lang = "lv" if any(p.strip().startswith("lv") for p in accept.split(",")) else "en"
    body = {
        **MANIFEST_TEXT[lang],
        "lang": lang,
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "background_color": "#0b0f14",
        "theme_color": "#0b0f14",
        "icons": [
            {"src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png",
             "purpose": "maskable"},
        ],
    }
    return JSONResponse(
        body,
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache", "Vary": "Accept-Language"},
    )
