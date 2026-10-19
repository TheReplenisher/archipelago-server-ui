"""apsui-admin (#32): the password from a shell."""

import io
from pathlib import Path

import pytest

from apsui import admin_auth, admin_cli
from apsui.config import Settings
from apsui.db import make_engine, make_sessionmaker


@pytest.fixture
def data_dir(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Path:
    settings.data_dir.mkdir(parents=True)
    monkeypatch.setenv("APSUI_DATA_DIR", str(settings.data_dir))
    return settings.data_dir


def test_set_password_from_stdin(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert admin_cli.main(["status"]) == 0
    assert "isn't set" in capsys.readouterr().out
    monkeypatch.setattr("sys.stdin", io.StringIO("from the shell\n"))
    assert admin_cli.main(["set-password", "--password-stdin"]) == 0
    with make_sessionmaker(make_engine(f"sqlite:///{data_dir / 'app.db'}"))() as session:
        admin = admin_auth.get_admin(session)
        assert admin is not None
        assert admin_auth.verify_password("from the shell", admin.password_hash)


def test_a_short_password_is_refused(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert admin_cli.main(["set-password", "--password-stdin"]) == 1
    assert "at least 8" in capsys.readouterr().err
