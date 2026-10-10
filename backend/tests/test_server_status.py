from collections.abc import Iterator
from pathlib import Path

import pytest
from apsui_server.testing import running_supervisor
from fastapi.testclient import TestClient

from apsui.config import Settings
from apsui.main import create_app


@pytest.fixture
def supervisor_socket(tmp_path: Path) -> Iterator[Path]:
    with running_supervisor(tmp_path / "run" / "control.sock") as path:
        yield path


def test_reports_the_supervisor_state(
    settings: Settings, supervisor_socket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARCHIPELAGO_VERSION", "0.6.8")
    settings.control_socket = supervisor_socket
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/server")
    assert response.json() | {"port": None} == response.json() | {
        "reachable": True,
        "state": "stopped",
        "archipelago_version": "0.6.8",
        "multidata": None,
        "exit_code": None,
        "log_tail": [],
        "port": None,
    }


def test_unreachable_supervisor(client: TestClient) -> None:
    status = client.get("/api/server").json()
    assert (status["reachable"], status["state"], status["archipelago_version"]) == (
        False,
        None,
        None,
    )
