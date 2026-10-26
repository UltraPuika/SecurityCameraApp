import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Role, User
from app.security import hash_password

log = logging.getLogger(__name__)


def ensure_admin(db: Session, settings: Settings) -> None:
    """Create the initial admin from env on first run; never overwrite an existing user."""
    if db.scalar(select(User.id).limit(1)) is not None:
        return
    if settings.admin_password is None:
        raise RuntimeError(
            "No users exist yet: set CAMDASH_ADMIN_USERNAME and CAMDASH_ADMIN_PASSWORD "
            "for the first start."
        )
    db.add(
        User(
            username=settings.admin_username,
            password_hash=hash_password(settings.admin_password.get_secret_value()),
            role=Role.admin,
        )
    )
    db.commit()
    log.info("Created initial admin user %r", settings.admin_username)
