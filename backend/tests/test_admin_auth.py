"""Admin login (#32): first-run setup, login, sessions, password changes, and every admin
route behind it."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from apsui import admin_auth
from apsui.config import Settings
from apsui.main import create_app
from apsui.models import AdminSession

pytestmark = pytest.mark.real_auth

PASSWORD = "correct horse"  # noqa: S105 - a test password


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


def code(response: object) -> str:
    detail = response.json()["detail"]  # type: ignore[attr-defined]
    result: str = detail["code"]
    return result


def test_a_fresh_install_asks_for_a_password_and_locks_admin_routes(client: TestClient) -> None:
    assert client.get("/api/admin/session").json() == {
        "password_set": False,
        "logged_in": False,
        "username": None,
    }
    for method, path in [
        ("GET", "/api/game"),
        ("GET", "/api/settings"),
        ("GET", "/api/health/details"),
        ("GET", "/api/uploads"),
        ("GET", "/api/archives"),
        ("GET", "/api/logs/uploads"),
        ("POST", "/api/game/lock"),
        ("GET", "/api/server"),
    ]:
        response = client.request(method, path)
        assert (response.status_code, code(response)) == (401, "admin-login-required"), path
    # Open to everyone: liveness and the player pages.
    assert client.get("/api/health").status_code == 200
    assert code(client.get("/api/slot")) != "admin-login-required"


def test_whoever_comes_first_sets_the_password(client: TestClient) -> None:
    short = client.post("/api/admin/setup", json={"password": "short"})
    assert (short.status_code, code(short)) == (422, "password-too-short")
    response = client.post("/api/admin/setup", json={"password": PASSWORD})
    assert response.json() == {"password_set": True, "logged_in": True, "username": "admin"}
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/api" in cookie
    assert client.get("/api/game").status_code == 200

    again = TestClient(client.app).post("/api/admin/setup", json={"password": "another one"})
    assert (again.status_code, code(again)) == (409, "already-set")


def test_login_and_logout(client: TestClient) -> None:
    client.post("/api/admin/setup", json={"password": PASSWORD})
    client.post("/api/admin/logout")
    assert client.get("/api/game").status_code == 401
    wrong = client.post("/api/admin/login", json={"password": "not it at all"})
    assert (wrong.status_code, code(wrong)) == (401, "login-refused")
    assert client.post("/api/admin/login", json={"password": PASSWORD}).status_code == 200
    assert client.get("/api/game").status_code == 200
    assert client.get("/api/admin/session").json()["logged_in"] is True


def test_logins_are_rate_limited(client: TestClient) -> None:
    client.post("/api/admin/setup", json={"password": PASSWORD})
    for _ in range(admin_auth.LOGINS_PER_CLIENT):
        client.post("/api/admin/login", json={"password": "wrong password"})
    response = client.post("/api/admin/login", json={"password": PASSWORD})
    assert (response.status_code, code(response)) == (429, "too-many-logins")


def test_login_before_setup_says_so(client: TestClient) -> None:
    response = client.post("/api/admin/login", json={"password": PASSWORD})
    assert (response.status_code, code(response)) == (409, "password-not-set")


def test_changing_the_password_ends_the_other_sessions(client: TestClient) -> None:
    client.post("/api/admin/setup", json={"password": PASSWORD})
    other = TestClient(client.app)
    other.post("/api/admin/login", json={"password": PASSWORD})
    assert other.get("/api/game").status_code == 200

    wrong = client.post("/api/admin/password", json={"current": "nope nope", "new": "new pass 1"})
    assert (wrong.status_code, code(wrong)) == (403, "wrong-password")
    changed = client.post("/api/admin/password", json={"current": PASSWORD, "new": "new pass 1"})
    assert changed.status_code == 200, changed.text
    assert client.get("/api/game").status_code == 200
    assert other.get("/api/game").status_code == 401
    assert other.post("/api/admin/login", json={"password": "new pass 1"}).status_code == 200


def test_setting_the_password_from_the_shell_ends_every_session(client: TestClient) -> None:
    client.post("/api/admin/setup", json={"password": PASSWORD})
    with client.app.state.sessionmaker() as session:  # type: ignore[attr-defined]
        admin_auth.set_password(session, "taken back")
    assert client.get("/api/game").status_code == 401
    assert client.post("/api/admin/login", json={"password": "taken back"}).status_code == 200


def test_a_session_unused_for_a_week_ends(client: TestClient) -> None:
    client.post("/api/admin/setup", json={"password": PASSWORD})
    with client.app.state.sessionmaker() as session:  # type: ignore[attr-defined]
        for row in session.query(AdminSession):
            row.last_seen_at = datetime.now(UTC) - timedelta(days=8)
        session.commit()
    assert client.get("/api/game").status_code == 401


def test_the_feed_needs_the_admin(client: TestClient) -> None:
    feed = "/api/server/feed"
    with pytest.raises(WebSocketDisconnect) as refused, client.websocket_connect(feed):
        pass
    assert refused.value.code == 1008
    client.post("/api/admin/setup", json={"password": PASSWORD})
    with client.websocket_connect("/api/server/feed") as ws:
        assert ws.receive_json()["reset"] is True


def test_password_hashes_are_salted_and_verified() -> None:
    first, second = admin_auth.hash_password("same"), admin_auth.hash_password("same")
    assert first != second and first.startswith("scrypt$")
    assert admin_auth.verify_password("same", first)
    assert not admin_auth.verify_password("other", first)
    assert not admin_auth.verify_password("same", "garbage")
