import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import logbuffer, logredact
from app.bootstrap import ensure_admin
from app.config import Settings, get_settings
from app.crypto import SecretBox
from app.db import Database
from app.deps import SAFE_METHODS, origin_allowed
from app.errors import ApiError, api_error_handler, validation_error_handler
from app.netguard import NetGuard, parse_networks
from app.routers import accounts, auth, cameras, diagnostics, health, live
from app.security import LoginRateLimiter
from app.services import Runtime
from app.streams import StreamManager

BACKEND_DIR = Path(__file__).resolve().parent.parent

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
    "media-src 'self' blob:; connect-src 'self'; worker-src 'self'; manifest-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


def run_migrations(database_url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


def create_app(
    settings: Settings | None = None, http_transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    settings = settings or get_settings()
    db = Database(settings.database_url)
    logredact.install()
    logbuffer.install()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        run_migrations(settings.database_url)
        with db.sessionmaker() as s:
            ensure_admin(s, settings)
        async with httpx.AsyncClient(
            transport=http_transport, verify=True, follow_redirects=False,
            headers={"User-Agent": "camdash"},
        ) as http:
            _app.state.runtime = Runtime(
                box=SecretBox(settings.encryption_key.get_secret_value()),
                guard=NetGuard(parse_networks(settings.allowed_camera_networks)),
                http=http,
                timeout=settings.probe_timeout_seconds,
            )
            _app.state.streams = StreamManager(
                http, settings.go2rtc_url, settings.stream_idle_seconds, settings.max_streams
            )
            try:
                yield
            finally:
                await _app.state.streams.close()
        db.engine.dispose()

    app = FastAPI(
        title="camdash", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.settings = settings
    app.state.db = db
    app.state.login_limiter = LoginRateLimiter(
        settings.login_max_failures, settings.login_window_seconds
    )
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    @app.middleware("http")
    async def security_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None and not origin_allowed(
                origin, request.headers.get("host"), settings
            ):
                return JSONResponse({"error": {"code": "auth.bad_origin"}}, status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(cameras.router)
    app.include_router(accounts.router)
    app.include_router(live.router)
    app.include_router(diagnostics.router)

    @app.api_route("/api/{_rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def api_not_found(_rest: str) -> JSONResponse:
        return JSONResponse({"error": {"code": "not_found"}}, status_code=404)

    _mount_spa(app, Path(settings.static_dir))
    return app


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    index = static_dir / "index.html"
    if not index.is_file():
        logging.getLogger(__name__).warning("No frontend build at %s; serving API only", static_dir)
        return
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")
    root = static_dir.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            headers = {"Cache-Control": "no-cache"} if path == "sw.js" else None
            return FileResponse(candidate, headers=headers)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
