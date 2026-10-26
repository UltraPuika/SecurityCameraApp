import hmac
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import ApiError
from app.models import Role, User, UserSession
from app.security import token_digest
from app.services import Services

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "X-CSRF-Token"


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_db(request: Request) -> Iterator[Session]:
    yield from request.app.state.db.session()


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
DbDep = Annotated[Session, Depends(get_db)]


def _as_aware(dt: datetime) -> datetime:
    # SQLite drops tzinfo; values are always written in UTC.
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def session_from_token(db: Session, token: str | None) -> UserSession | None:
    if not token:
        return None
    sess = db.get(UserSession, token_digest(token))
    if sess is None or _as_aware(sess.expires_at) <= datetime.now(UTC):
        return None
    return sess


def get_current_session(request: Request, db: DbDep, settings: SettingsDep) -> UserSession:
    sess = session_from_token(db, request.cookies.get(settings.session_cookie_name))
    if sess is None:
        raise ApiError(401, "auth.not_authenticated")
    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not hmac.compare_digest(sent, sess.csrf_token):
            raise ApiError(403, "auth.csrf_failed")
    return sess


SessionDep = Annotated[UserSession, Depends(get_current_session)]


def get_current_user(sess: SessionDep) -> User:
    return sess.user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role != Role.admin:
        raise ApiError(403, "auth.forbidden")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def get_services(request: Request, db: DbDep) -> Services:
    return Services(db, request.app.state.runtime)


ServicesDep = Annotated[Services, Depends(get_services)]
