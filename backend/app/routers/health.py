from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.deps import DbDep

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(db: DbDep) -> JSONResponse:
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "error", "db": "error"}, status_code=503)
    return JSONResponse({"status": "ok", "db": "ok"})
