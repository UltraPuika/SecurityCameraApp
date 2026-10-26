from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.providers.base import ProviderError


class ApiError(Exception):
    """Error returned to the client as a stable code; the frontend translates it."""

    def __init__(
        self,
        status: int,
        code: str,
        headers: dict[str, str] | None = None,
        detail: dict[str, object] | None = None,
    ) -> None:
        self.status = status
        self.code = code
        self.headers = headers
        self.detail = detail or {}


def from_provider(exc: ProviderError, status: int = 422) -> ApiError:
    return ApiError(status, exc.code, detail=dict(exc.detail))


async def api_error_handler(_req: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return JSONResponse(
        {"error": {**exc.detail, "code": exc.code}}, status_code=exc.status, headers=exc.headers
    )


async def validation_error_handler(_req: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    fields = [".".join(str(p) for p in e["loc"][1:]) for e in exc.errors()]
    return JSONResponse(
        {"error": {"code": "validation.invalid", "fields": fields}}, status_code=422
    )
