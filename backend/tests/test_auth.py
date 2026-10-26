from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.deps import AdminUser
from app.main import create_app
from app.models import Role, User, UserSession
from app.security import hash_password
from tests.conftest import ADMIN_PASSWORD, login


def test_login_sets_hardened_cookie(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "admin" and body["role"] == "admin"
    assert "password" not in r.text
    cookie = r.headers["set-cookie"].lower()
    assert cookie.startswith("__host-camdash_session=")
    for attr in ("httponly", "secure", "samesite=strict", "path=/"):
        assert attr in cookie


def test_session_token_is_stored_hashed(client: TestClient, app: FastAPI) -> None:
    login(client)
    raw = next(iter(client.cookies.values()))
    with app.state.db.sessionmaker() as s:
        ids = s.scalars(select(UserSession.id)).all()
    assert ids and raw not in ids


def test_me_requires_auth(client: TestClient) -> None:
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "auth.not_authenticated"}}


def test_wrong_password_and_unknown_user_look_identical(client: TestClient) -> None:
    a = client.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    b = client.post("/api/auth/login", json={"username": "ghost", "password": "nope"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {"error": {"code": "auth.invalid_credentials"}}


def test_login_rate_limited(client: TestClient) -> None:
    for _ in range(3):
        client.post("/api/auth/login", json={"username": "admin", "password": "bad"})
    r = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "auth.rate_limited"
    assert int(r.headers["retry-after"]) > 0


def test_login_rejects_non_json_body(client: TestClient) -> None:
    r = client.post(
        "/api/auth/login",
        content=f'{{"username":"admin","password":"{ADMIN_PASSWORD}"}}',
        headers={"content-type": "text/plain"},
    )
    assert r.status_code == 422


def test_csrf_required_for_state_change(client: TestClient) -> None:
    csrf = login(client)
    r = client.put("/api/me/preferences", json={"language": "lv"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "auth.csrf_failed"
    r = client.put("/api/me/preferences", json={"language": "lv"}, headers={"X-CSRF-Token": "x"})
    assert r.status_code == 403
    r = client.put(
        "/api/me/preferences", json={"language": "lv"}, headers={"X-CSRF-Token": csrf}
    )
    assert r.status_code == 200
    assert r.json()["language"] == "lv"


def test_cross_origin_post_rejected(client: TestClient) -> None:
    r = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "auth.bad_origin"


def test_invalid_language_rejected(client: TestClient) -> None:
    csrf = login(client)
    r = client.put(
        "/api/me/preferences", json={"language": "de"}, headers={"X-CSRF-Token": csrf}
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation.invalid"


def test_logout_invalidates_session(client: TestClient) -> None:
    csrf = login(client)
    old = dict(client.cookies)
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    client.cookies.update(old)
    assert client.get("/api/auth/me").status_code == 401


def test_viewer_cannot_use_admin_routes(make_settings: Callable[..., Settings]) -> None:
    app = create_app(make_settings())

    @app.get("/api/test-admin-only")
    def admin_only(_u: AdminUser) -> dict[str, bool]:
        return {"ok": True}

    # Registered after the /api catch-all, so move it to the front.
    app.router.routes.insert(0, app.router.routes.pop())

    with TestClient(app, base_url="https://testserver") as c:
        with app.state.db.sessionmaker() as s:
            s.add(User(username="viewer", password_hash=hash_password("viewerpass123"),
                       role=Role.viewer))
            s.commit()
        login(c)
        assert c.get("/api/test-admin-only").status_code == 200
        c.cookies.clear()
        r = c.post("/api/auth/login", json={"username": "viewer", "password": "viewerpass123"})
        assert r.status_code == 200
        r = c.get("/api/test-admin-only")
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "auth.forbidden"


def test_security_headers_present(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_unknown_api_route_is_json_404(client: TestClient) -> None:
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found"}}
