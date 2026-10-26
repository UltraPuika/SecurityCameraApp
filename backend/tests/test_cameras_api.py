"""Camera/account API: CRUD, write-only secrets, test-before-save, authorization."""

import asyncio
import threading
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.logredact import redact
from app.main import create_app
from app.models import Role, User
from app.security import hash_password
from tests.conftest import login
from tests.fakes import FakeOnvif, FakeRtsp, PermissiveGuard, h264_sps, h265_sps, sdp_for


class RtspThread:
    """Runs the fake RTSP server in its own loop (TestClient uses a separate loop)."""

    def __init__(self, streams: dict[str, str]) -> None:
        self.fake = FakeRtsp(streams)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)

    def __enter__(self) -> FakeRtsp:
        self.thread.start()
        asyncio.run_coroutine_threadsafe(self.fake.start(), self.loop).result(5)
        return self.fake

    def __exit__(self, *_: object) -> None:
        asyncio.run_coroutine_threadsafe(self.fake.stop(), self.loop).result(5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


@pytest.fixture
def onvif() -> FakeOnvif:
    return FakeOnvif(channels=4)


@pytest.fixture
def api(make_settings: Callable[..., Settings], onvif: FakeOnvif) -> Iterator[tuple[TestClient, str]]:
    app = create_app(make_settings(), http_transport=httpx.MockTransport(onvif.handler))
    with TestClient(app, base_url="https://testserver") as c:
        app.state.runtime.guard = PermissiveGuard()
        app.state.runtime.timeout = 3
        yield c, login(c)


def _generic(port: int, **cfg: Any) -> dict[str, Any]:
    return {
        "name": "Driveway",
        "location": "Home",
        "provider": "generic",
        "config": {"host": "127.0.0.1", "rtsp_port": port, "use_onvif": False,
                   "main_path": "/ch01/0", "sub_path": "/ch01/1", **cfg},
        "secrets": {"username": "admin", "password": "s3cret-pass"},
    }


def test_providers_listing_exposes_schemas(api: tuple[TestClient, str]) -> None:
    c, _ = api
    body = c.get("/api/providers").json()
    ids = {p["id"] for p in body["cameras"]}
    assert {"generic", "bitvision", "imou"} <= ids
    imou = next(p for p in body["cameras"] if p["id"] == "imou")
    assert imou["transport"] == "cloud" and imou["account_provider"] == "imou"
    assert body["accounts"][0]["id"] == "imou"


def test_test_then_save_generic_camera_and_secrets_never_returned(api: tuple[TestClient, str]) -> None:
    c, csrf = api
    h = {"X-CSRF-Token": csrf}
    streams = {"/ch01/0": sdp_for("H265", h265_sps(2560, 1440)),
               "/ch01/1": sdp_for("H264", h264_sps(40, 30, 0), fps=15)}
    with RtspThread(streams) as fake:
        body = _generic(fake.port)
        diag = c.post("/api/cameras/test", json=body, headers=h).json()
        assert diag["ok"], diag
        names = [s["name"] for s in diag["steps"]]
        assert names == ["dns", "tcp", "auth", "stream_main", "stream_sub"]
        main = diag["steps"][3]["detail"]
        assert (main["codec"], main["width"], main["height"]) == ("H265", 2560, 1440)
        assert "codec.h265_limited_browser_support" in main["warnings"]

        r = c.post("/api/cameras", json=body, headers=h)
        assert r.status_code == 201, r.text
        cam = r.json()
        assert cam["status"] == "online" and cam["verified"] is False
        assert cam["secrets_set"] == ["password", "username"]
        assert cam["probe"]["sub_probe"]["width"] == 640

        listing = c.get("/api/cameras")
        assert "s3cret-pass" not in listing.text and "s3cret-pass" not in r.text

        # Update without resending secrets keeps them (write-only fields).
        body["name"] = "Driveway 2"
        body["secrets"] = {"username": "", "password": None}
        r = c.put(f"/api/cameras/{cam['id']}", json=body, headers=h)
        assert r.status_code == 200 and r.json()["name"] == "Driveway 2"
        r = c.post(f"/api/cameras/{cam['id']}/test", headers=h)
        assert r.json()["ok"], r.json()


def test_wrong_password_sets_needs_setup(api: tuple[TestClient, str]) -> None:
    c, csrf = api
    with RtspThread({"/ch01/0": sdp_for("H264", h264_sps(40, 30, 0))}) as fake:
        body = _generic(fake.port, sub_path="")
        body["secrets"]["password"] = "nope"
        cam = c.post("/api/cameras", json=body, headers={"X-CSRF-Token": csrf}).json()
        assert cam["status"] == "needs_setup"
        assert cam["status_code"] == "rtsp.auth_failed"


def test_unreachable_after_seen_is_offline(api: tuple[TestClient, str]) -> None:
    c, csrf = api
    h = {"X-CSRF-Token": csrf}
    with RtspThread({"/ch01/0": sdp_for("H264", h264_sps(40, 30, 0))}) as fake:
        cam = c.post("/api/cameras", json=_generic(fake.port, sub_path=""), headers=h).json()
        assert cam["status"] == "online"
    r = c.post(f"/api/cameras/{cam['id']}/test", headers=h).json()
    assert r["camera"]["status"] == "offline"
    assert r["camera"]["status_code"] == "net.tcp_refused"


def test_bitvision_via_onvif_channel(api: tuple[TestClient, str], onvif: FakeOnvif) -> None:
    c, csrf = api
    streams = {"/ch03/0": sdp_for("H264", h264_sps(160, 90, 0)),
               "/ch03/1": sdp_for("H264", h264_sps(40, 23, 4))}
    with RtspThread(streams) as fake:
        body = {
            "name": "Garden", "provider": "bitvision",
            "config": {"host": "127.0.0.1", "channel": 3, "rtsp_port": fake.port},
            "secrets": {"password": "s3cret-pass"},
        }
        diag = c.post("/api/cameras/test", json=body, headers={"X-CSRF-Token": csrf}).json()
        assert diag["ok"], diag
        assert diag["discovered"]["main_path"] == "/ch03/0"
        assert diag["discovered"]["sub_path"] == "/ch03/1"
        assert "SerialNumber" not in diag["discovered"]["device_info"]


def test_bitvision_default_password_refused(api: tuple[TestClient, str]) -> None:
    c, csrf = api
    body = {"name": "x", "provider": "bitvision",
            "config": {"host": "192.168.1.68", "channel": 1},
            "secrets": {"password": "12345"}}
    r = c.post("/api/cameras/test", json=body, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 422
    assert r.json()["error"] == {"code": "bitvision.default_password", "field": "password"}


def test_ssrf_host_rejected_with_real_guard(
    make_settings: Callable[..., Settings],
) -> None:
    app = create_app(make_settings())
    with TestClient(app, base_url="https://testserver") as c:
        h = {"X-CSRF-Token": login(c)}
        for host, code in (("127.0.0.1", "net.forbidden_address"),
                           ("169.254.169.254", "net.forbidden_address"),
                           ("1.1.1.1", "net.not_private")):
            body = _generic(554, host=host)
            diag = c.post("/api/cameras/test", json=body, headers=h).json()
            assert diag["steps"] == [{"name": "dns", "status": "fail", "code": code, "detail": {}}]


@pytest.mark.parametrize(
    ("config", "code"),
    [
        ({"host": "10.0.0.1", "use_onvif": False, "main_path": "rtsp://evil/x"},
         "validation.invalid_path"),
        ({"host": "10.0.0.1@evil", "use_onvif": True}, "net.invalid_host"),
        ({"host": "10.0.0.1", "rtsp_port": 70000}, "validation.out_of_range"),
        ({"host": "10.0.0.1", "unknown": 1}, "validation.unknown_field"),
        ({"host": "10.0.0.1", "use_onvif": False}, "validation.required"),
    ],
)
def test_config_validation(api: tuple[TestClient, str], config: dict[str, Any], code: str) -> None:
    c, csrf = api
    body = {"name": "x", "provider": "generic", "config": config}
    r = c.post("/api/cameras", json=body, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == code


def test_viewer_cannot_manage_but_can_list(api: tuple[TestClient, str]) -> None:
    c, csrf = api
    app = c.app
    with app.state.db.sessionmaker() as s:  # type: ignore[attr-defined]
        s.add(User(username="viewer", password_hash=hash_password("viewerpass123"),
                   role=Role.viewer))
        s.commit()
    c.cookies.clear()
    r = c.post("/api/auth/login", json={"username": "viewer", "password": "viewerpass123"})
    vh = {"X-CSRF-Token": r.json()["csrf_token"]}
    assert c.get("/api/cameras").status_code == 200
    assert c.post("/api/cameras", json=_generic(554), headers=vh).status_code == 403
    assert c.post("/api/cameras/test", json=_generic(554), headers=vh).status_code == 403
    assert c.get("/api/accounts").status_code == 403


def test_imou_camera_requires_account(api: tuple[TestClient, str]) -> None:
    c, csrf = api
    body = {"name": "Gate", "provider": "imou", "config": {"device_id": "BASE1"}}
    r = c.post("/api/cameras", json=body, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 422 and r.json()["error"]["code"] == "camera.account_required"


def test_account_secrets_write_only_and_in_use_protection(api: tuple[TestClient, str]) -> None:
    c, csrf = api
    h = {"X-CSRF-Token": csrf}
    acc = c.post("/api/accounts", headers=h, json={
        "name": "Imou", "provider": "imou",
        "config": {"data_center": "fk"},
        "secrets": {"app_id": "lcAPPID", "app_secret": "SUPERSECRET"},
    })
    assert acc.status_code == 201
    out = acc.json()
    assert out["secrets_set"] == ["app_id", "app_secret"]
    assert "SUPERSECRET" not in acc.text and "lcAPPID" not in acc.text
    assert "SUPERSECRET" not in c.get("/api/accounts").text

    cam = c.post("/api/cameras", headers=h, json={
        "name": "Gate", "provider": "imou", "account_id": out["id"],
        "config": {"device_id": "BASE1", "channel_id": "0"},
    })
    assert cam.status_code == 201
    # The mocked transport is the ONVIF fake, so the Imou cloud call fails -> needs setup.
    assert cam.json()["status"] == "needs_setup"
    assert c.delete(f"/api/accounts/{out['id']}", headers=h).status_code == 409
    assert c.delete(f"/api/cameras/{cam.json()['id']}", headers=h).status_code == 204
    assert c.delete(f"/api/accounts/{out['id']}", headers=h).status_code == 204


def test_cameras_survive_restart(make_settings: Callable[..., Settings]) -> None:
    with TestClient(create_app(make_settings()), base_url="https://testserver") as c:
        h = {"X-CSRF-Token": login(c)}
        body = _generic(554, host="10.255.255.1")
        c.app.state.runtime.timeout = 0.5  # type: ignore[attr-defined]
        assert c.post("/api/cameras", json=body, headers=h).status_code == 201
    with TestClient(create_app(make_settings()), base_url="https://testserver") as c:
        login(c)
        cams = c.get("/api/cameras").json()
        assert [x["name"] for x in cams] == ["Driveway"]
        assert cams[0]["secrets_set"] == ["password", "username"]


def test_log_redaction() -> None:
    assert redact("pull rtsp://admin:pa55@10.0.0.2:554/x") == "pull rtsp://***:***@10.0.0.2:554/x"
    assert "SECRET" not in redact('{"app_secret": "SECRET", "token":"At_1"}')
    assert "At_1" not in redact('{"app_secret": "SECRET", "token":"At_1"}')
    encoded = "PUT /api/streams?name=c&src=rtsp%3A%2F%2Fadmin%3As3cret%4010.0.0.9 x"
    assert "s3cret" not in redact(encoded)
    assert "s3cret" not in redact("x rtsp%3A%2F%2Fadmin%3As3cret%4010.0.0.9")
