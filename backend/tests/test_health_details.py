from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from apsui_server.testing import running_supervisor
from apsui_worker.protocol import JobDirs
from fastapi.testclient import TestClient

from apsui.config import Settings
from apsui.main import create_app


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    settings.job_poll_interval = 3600
    settings.archipelago_version = "0.6.8"
    with TestClient(create_app(settings)) as c:
        yield c


def details(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/health/details")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def services(client: TestClient) -> dict[str, tuple[bool, str]]:
    return {s["name"]: (s["up"], s["detail"]) for s in details(client)["services"]}


def test_a_fresh_development_setup(client: TestClient) -> None:
    body = details(client)
    assert body["archipelago_version"] == "0.6.8"
    assert body["isolation"] == "none" and "aren't isolated" in body["isolation_warning"]
    found = services(client)
    assert found["web"][0] is True
    assert found["worker"] == (False, "Never seen; 0 queued, 0 running")
    assert found["server"] == (False, "Not answering")
    assert [d["name"] for d in body["disks"]] == ["Data", "Job queue", "Current game"]
    assert all(d["total"] >= d["free"] > 0 for d in body["disks"])


def test_worker_and_server_up(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    JobDirs(settings.resolved_jobs_dir).beat()
    settings.control_socket = tmp_path / "run" / "control.sock"
    with running_supervisor(settings.control_socket):
        found = services(client)
    assert found["worker"][0] is True and found["worker"][1].startswith("Heartbeat")
    assert found["server"] == (True, "MultiServer stopped")


def test_compose_settings_are_shown(client: TestClient, settings: Settings) -> None:
    settings.isolation, settings.public_web_port, settings.public_game_port = "compose", 8000, 38281
    body = details(client)
    assert body["isolation_warning"] is None
    assert [p["port"] for p in body["ports"]] == [8000, 38281]
