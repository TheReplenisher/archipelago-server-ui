from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apsui import admin_auth
from apsui.config import Settings
from apsui.main import create_app
from apsui.models import Admin


@pytest.fixture(autouse=True)
def logged_in_admin(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test is logged in as the admin (#32), except those marked `real_auth`."""
    if request.node.get_closest_marker("real_auth"):
        return
    real = admin_auth.authenticate
    now = datetime.now(UTC)
    admin = Admin(id=0, username="admin", password_hash="", created_at=now, password_changed_at=now)

    def authenticate(session: Session, token: str | None) -> Admin | None:
        return real(session, token) or admin

    monkeypatch.setattr(admin_auth, "authenticate", authenticate)


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    static = tmp_path / "dist"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><div id=root></div>")
    (static / "assets" / "app.js").write_text("console.log('app')")
    return static


@pytest.fixture
def settings(tmp_path: Path, static_dir: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        static_dir=static_dir,
        control_socket=tmp_path / "no-supervisor.sock",
        # TestClient's host name. Like any name that isn't local-only, it must be listed.
        allowed_hosts=["testserver"],
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
