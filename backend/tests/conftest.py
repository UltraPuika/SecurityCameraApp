from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

ADMIN_PASSWORD = "correct horse battery"


@pytest.fixture
def make_settings(tmp_path: Path) -> Callable[..., Settings]:
    key = Fernet.generate_key().decode()

    def _make(**overrides: object) -> Settings:
        values: dict[str, object] = {
            "database_url": f"sqlite:///{tmp_path / 'test.db'}",
            "encryption_key": key,
            "admin_username": "admin",
            "admin_password": ADMIN_PASSWORD,
            "static_dir": str(tmp_path / "no-static"),
            "login_max_failures": 3,
        }
        values.update(overrides)
        return Settings(**values)  # type: ignore[arg-type]

    return _make


@pytest.fixture
def app(make_settings: Callable[..., Settings]) -> FastAPI:
    return create_app(make_settings())


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def login(client: TestClient, password: str = ADMIN_PASSWORD) -> str:
    r = client.post("/api/auth/login", json={"username": "admin", "password": password})
    assert r.status_code == 200, r.text
    csrf: str = r.json()["csrf_token"]
    return csrf
