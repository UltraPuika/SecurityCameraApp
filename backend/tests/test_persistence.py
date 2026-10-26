from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import ADMIN_PASSWORD, login


def test_data_survives_restart(make_settings: Callable[..., Settings]) -> None:
    with TestClient(create_app(make_settings()), base_url="https://testserver") as c:
        csrf = login(c)
        c.put("/api/me/preferences", json={"language": "lv"}, headers={"X-CSRF-Token": csrf})

    # Restart with a different env password: the existing admin must not be overwritten.
    restarted = create_app(make_settings(admin_password="another-password-123"))
    with TestClient(restarted, base_url="https://testserver") as c:
        r = c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
        assert r.status_code == 200
        assert r.json()["language"] == "lv"


def test_session_survives_restart(make_settings: Callable[..., Settings]) -> None:
    with TestClient(create_app(make_settings()), base_url="https://testserver") as c:
        login(c)
        cookies = dict(c.cookies)
    with TestClient(create_app(make_settings()), base_url="https://testserver") as c:
        c.cookies.update(cookies)
        assert c.get("/api/auth/me").status_code == 200


def test_first_start_without_admin_password_fails(
    make_settings: Callable[..., Settings],
) -> None:
    with (
        pytest.raises(RuntimeError, match="CAMDASH_ADMIN_PASSWORD"),
        TestClient(create_app(make_settings(admin_password=None))),
    ):
        pass
