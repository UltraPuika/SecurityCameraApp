from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.deps import CurrentUser, DbDep, SessionDep, SettingsDep
from app.errors import ApiError
from app.models import User, UserSession
from app.security import (
    LoginRateLimiter,
    hash_password,
    needs_rehash,
    new_token,
    token_digest,
    verify_password,
)

router = APIRouter(prefix="/api", tags=["auth"])

Language = Literal["lv", "en"]


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class MeOut(BaseModel):
    username: str
    role: str
    language: Language | None
    csrf_token: str


class PreferencesIn(BaseModel):
    language: Language


def _me(user: User, sess: UserSession) -> MeOut:
    lang = user.language if user.language in ("lv", "en") else None
    return MeOut(
        username=user.username,
        role=user.role.value,
        language=lang,
        csrf_token=sess.csrf_token,
    )


def _limiter(request: Request) -> LoginRateLimiter:
    limiter: LoginRateLimiter = request.app.state.login_limiter
    return limiter


@router.post("/auth/login")
def login(
    body: LoginIn, request: Request, response: Response, db: DbDep, settings: SettingsDep
) -> MeOut:
    limiter = _limiter(request)
    ip = request.client.host if request.client else "unknown"
    keys = (f"ip:{ip}", f"user:{body.username.lower()}")
    wait = limiter.retry_after(*keys)
    if wait:
        raise ApiError(429, "auth.rate_limited", headers={"Retry-After": str(wait)})

    user = db.scalar(select(User).where(User.username == body.username))
    if not verify_password(user.password_hash if user else None, body.password) or user is None:
        limiter.record_failure(*keys)
        raise ApiError(401, "auth.invalid_credentials")
    limiter.reset(*keys)

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    now = datetime.now(UTC)
    db.execute(delete(UserSession).where(UserSession.expires_at <= now))
    token = new_token()
    sess = UserSession(
        id=token_digest(token),
        user=user,
        csrf_token=new_token(),
        created_at=now,
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(sess)
    db.commit()

    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_hours * 3600,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )
    return _me(user, sess)


@router.post("/auth/logout", status_code=204)
def logout(sess: SessionDep, response: Response, db: DbDep, settings: SettingsDep) -> None:
    db.delete(sess)
    db.commit()
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


@router.get("/auth/me")
def me(sess: SessionDep) -> MeOut:
    return _me(sess.user, sess)


@router.put("/me/preferences")
def set_preferences(body: PreferencesIn, user: CurrentUser, sess: SessionDep, db: DbDep) -> MeOut:
    user.language = body.language
    db.commit()
    return _me(user, sess)
