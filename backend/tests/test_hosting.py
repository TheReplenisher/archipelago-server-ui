"""Start / Stop / Save (#24), through a real supervisor on a socket, with a stand-in for
MultiServer that behaves like its console. The real MultiServer runs in
docker/compose-test.sh."""

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from apsui_server.supervisor import Supervisor
from apsui_server.testing import running_supervisor
from apworld_files import make_apworld
from fastapi.testclient import TestClient
from game_flow import accept_yaml, finish_with_zip, generated_game
from worker_sim import worker_finishes

from apsui.config import Settings
from apsui.main import create_app

FAKE_MULTISERVER = """
import sys
from pathlib import Path
print("Hosting game at 0.0.0.0:1", flush=True)
for line in sys.stdin:
    if line.strip() == "/save":
        Path(sys.argv[1]).with_suffix(".apsave").write_text("saved")
    elif line.strip() == "/exit":
        sys.exit(0)
    elif line.strip() == "idle":  # as auto_shutdown does
        print("Shutting down due to inactivity.", flush=True)
        sys.exit(0)
    else:
        with Path(sys.argv[1]).with_suffix(".console").open("a") as f:
            f.write(line)
"""


@pytest.fixture
def client(settings: Settings, tmp_path: Path) -> Iterator[TestClient]:
    archipelago = tmp_path / "archipelago"
    archipelago.mkdir()
    (archipelago / "MultiServer.py").write_text(FAKE_MULTISERVER)
    settings.job_poll_interval = 3600  # tests collect by hand
    settings.control_socket = tmp_path / "run" / "control.sock"
    supervisor = Supervisor(settings.game_dir, archipelago, port=38999)
    with (
        running_supervisor(settings.control_socket, supervisor),
        TestClient(create_app(settings)) as c,
    ):
        yield c
        c.post("/api/game/stop")


def server(client: TestClient) -> dict[str, Any]:
    status: dict[str, Any] = client.get("/api/server").json()
    return status


def until(client: TestClient, state: str) -> dict[str, Any]:
    for _ in range(250):
        status = server(client)
        if status["state"] == state:
            return status
        time.sleep(0.02)
    raise AssertionError(f"server never {state}: {server(client)}")


def test_start_save_stop(client: TestClient, settings: Settings) -> None:
    generated_game(client, "Knight")
    started = client.post("/api/game/start")
    assert started.status_code == 200, started.text
    assert (started.json()["state"], started.json()["actions"]) == ("running", ["stop"])
    status = until(client, "running")
    assert (status["multidata"], status["port"]) == ("AP_12345.zip", 38999)

    assert client.post("/api/server/save").status_code == 200
    save_file = settings.game_dir / "output" / "AP_12345.apsave"
    for _ in range(100):
        if save_file.exists():
            break
        time.sleep(0.02)
    assert save_file.read_text() == "saved"

    stopped = client.post("/api/game/stop")
    assert (stopped.status_code, stopped.json()["state"]) == (200, "generated")
    assert server(client)["state"] == "stopped"


def test_a_console_command_reaches_multiserver(client: TestClient, settings: Settings) -> None:
    response = client.post("/api/server/command", json={"text": "/players"})
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "not-running")
    generated_game(client, "Knight")
    client.post("/api/game/start")
    until(client, "running")

    response = client.post("/api/server/command", json={"text": "/players"})
    assert (response.status_code, response.json()["state"]) == (200, "running")
    response = client.post("/api/server/command", json={"text": "/players\n/exit"})
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "bad-command")
    console = settings.game_dir / "output" / "AP_12345.console"
    for _ in range(100):
        if console.exists():
            break
        time.sleep(0.02)
    assert console.read_text() == "/players\n"
    assert server(client)["state"] == "running"


def test_start_resumes_an_idle_server_without_leaving_running(client: TestClient) -> None:
    """#97: no Stop then Start; and a second Start while it runs is refused (#94)."""
    generated_game(client, "Knight")
    client.post("/api/game/start")
    until(client, "running")
    response = client.post("/api/game/start")
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "already-running")

    client.post("/api/server/command", json={"text": "idle"})
    until(client, "idle")
    resumed = client.post("/api/game/start")
    assert (resumed.status_code, resumed.json()["state"]) == (200, "running")
    until(client, "running")


def test_start_needs_a_generated_game(client: TestClient) -> None:
    response = client.post("/api/game/start")
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "not-generated")
    assert client.post("/api/server/save").json()["detail"]["code"] == "not-running"


def test_only_locked_apworlds_reach_the_server(client: TestClient, settings: Settings) -> None:
    for version in ("1.0.0", "2.0.0"):  # two in the library, one locked
        data = make_apworld(manifest={"game": "Sample Game", "world_version": version})
        apworld = client.post("/api/apworlds", files={"file": ("sample_game.apworld", data)}).json()
        loaded = {"archipelago_version": "0.6.8", "loaded": True, "games": ["Sample Game"]}
        worker_finishes(
            client,
            {"test-apworld": loaded | {"replaces_builtin": None, "error": None, "detail": None}},
        )
        client.post(f"/api/apworlds/{apworld['id']}/approve")
    accept_yaml(client, "Knight", game="Sample Game", apworld_ids=[apworld["id"]])
    client.post("/api/game/lock")
    client.post("/api/game/generate")
    finish_with_zip(client, ["Knight"])
    assert client.post("/api/game/start").status_code == 200
    worlds = settings.game_dir / "ap" / "Archipelago" / "worlds"
    assert [p.name for p in worlds.iterdir()] == ["sample_game.apworld"]
    assert (worlds / "sample_game.apworld").read_bytes() == data


def test_an_unreachable_server_service_is_503(client: TestClient, settings: Settings) -> None:
    generated_game(client, "Knight")
    settings.control_socket = settings.control_socket.with_name("missing.sock")
    response = client.post("/api/game/start")
    assert (response.status_code, response.json()["detail"]["code"]) == (503, "server-unreachable")
    assert client.get("/api/game").json()["state"] == "generated"
