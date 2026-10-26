from collections.abc import Callable

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import Settings
from app.crypto import SecretBox


def test_rejects_invalid_encryption_key(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValidationError):
        make_settings(encryption_key="not-a-key")


def test_rejects_short_admin_password(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValidationError):
        make_settings(admin_password="short")


def test_cookie_name_depends_on_secure(make_settings: Callable[..., Settings]) -> None:
    assert make_settings().session_cookie_name.startswith("__Host-")
    assert not make_settings(cookie_secure=False).session_cookie_name.startswith("__Host-")


def test_secretbox_roundtrip_and_ciphertext_hides_plaintext() -> None:
    box = SecretBox(Fernet.generate_key().decode())
    token = box.encrypt("camera-pass")
    assert "camera-pass" not in token
    assert box.decrypt(token) == "camera-pass"


def test_secretbox_wrong_key_fails() -> None:
    token = SecretBox(Fernet.generate_key().decode()).encrypt("x")
    with pytest.raises(ValueError):
        SecretBox(Fernet.generate_key().decode()).decrypt(token)
