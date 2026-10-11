"""The settings page (#25): stored, checked, and used where they apply."""

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from apsui_server.supervisor import Supervisor
from apsui_server.testing import running_supervisor
from apsui_worker.protocol import SPEC_FILE, State, read_json_file
from fastapi.testclient import TestClient
from game_flow import accept_yaml, finish_with_zip
from worker_sim import worker_finishes

from apsui import host_settings
from apsui.config import Settings
from apsui.host_settings import HostSettings
from apsui.jobs import JobQueue
from apsui.main import create_app

FAKE_MULTISERVER = """
import sys
from pathlib import Path
print("Hosting game at 0.0.0.0:1", flush=True)
for line in sys.stdin:
    if line.strip() == "/exit":
        sys.exit(0)
    with Path(sys.argv[1]).with_suffix(".console").open("a") as f:
        f.write(line)
"""


@pytest.fixture
def client(settings: Settings, tmp_path: Path) -> Iterator[TestClient]:
    archipelago = tmp_path / "archipelago"
    archipelago.mkdir()
    (archipelago / "MultiServer.py").write_text(FAKE_MULTISERVER)
    settings.job_poll_interval = 3600
    settings.control_socket = tmp_path / "run" / "control.sock"
    supervisor = Supervisor(settings.game_dir, archipelago, port=38999)
    with (
        running_supervisor(settings.control_socket, supervisor),
        TestClient(create_app(settings)) as c,
    ):
        yield c
        c.post("/api/game/stop")


def values(client: TestClient) -> dict[str, Any]:
    result: dict[str, Any] = client.get("/api/settings").json()["values"]
    return result


def put(client: TestClient, **changes: Any) -> dict[str, Any]:
    response = client.put("/api/settings", json=values(client) | changes)
    assert response.status_code == 200, response.text
    saved: dict[str, Any] = response.json()
    return saved


def queued_params(client: TestClient) -> list[dict[str, Any]]:
    jobs: JobQueue = client.app.state.jobs  # type: ignore[attr-defined]
    specs = [
        read_json_file(jobs.dirs.path(State.QUEUE, i) / SPEC_FILE)
        for i in jobs.dirs.ids(State.QUEUE)
    ]
    return [spec["params"] for spec in specs]


def test_the_defaults_and_every_field(client: TestClient, settings: Settings) -> None:
    body = client.get("/api/settings").json()
    assert body["values"] == HostSettings(max_slots=settings.max_slots).model_dump()
    assert body["values"]["disable_item_cheat"] is True  # ours; AP's default is off
    assert [f["key"] for f in body["fields"]] == list(HostSettings.model_fields)
    assert {f["applies"] for f in body["fields"]} == {
        "live",
        "start",
        "generation",
        "upload",
        "archive",
    }


@pytest.mark.parametrize(
    "change",
    [
        {"hint_cost": 101},
        {"release_mode": "sometimes"},
        {"password": "two\nlines"},
        {"plando_options": ["bosses", "everything"]},
        {"unknown": 1},
    ],
)
def test_invalid_settings_are_refused(client: TestClient, change: dict[str, Any]) -> None:
    response = client.put("/api/settings", json=values(client) | change)
    assert response.status_code == 422
    assert values(client) == client.get("/api/settings").json()["values"]


def test_generation_uses_the_generation_settings(client: TestClient) -> None:
    put(client, spoiler=1, race=True, plando_options=["items", "bosses"], panic_method="raise")
    accept_yaml(client, "Knight")
    client.post("/api/game/lock")
    client.post("/api/game/generate")
    [params] = queued_params(client)
    assert params == {
        "spoiler": 1,
        "race": True,
        "plando_options": "items, bosses",
        "panic_method": "raise",
    }


def test_uploads_use_the_upload_settings(client: TestClient) -> None:
    put(client, allow_quantity=True, plando_options=["texts"], max_slots=1)
    client.post(
        "/api/uploads/yaml", files={"file": ("a.yaml", b"name: A\ngame: APQuest\nAPQuest: {}\n")}
    )
    [params] = queued_params(client)
    assert params == {"plando_options": "texts", "allow_quantity": True}


def test_the_slot_limit_comes_from_the_settings(client: TestClient) -> None:
    put(client, max_slots=1)
    accept_yaml(client, "Knight")
    response = client.post(
        "/api/uploads/yaml",
        files={"file": ("h.yaml", b"name: Hornet\ngame: APQuest\nAPQuest: {}\n")},
    )
    upload_id = response.json()["id"]
    doc = {"index": 0, "empty": False, "name": "Hornet", "name_raw": "Hornet", "games": ["APQuest"]}
    worker_finishes(client, {"validate-yaml": {"error": None, "documents": [doc]}})
    upload = next(u for u in client.get("/api/uploads").json() if u["id"] == upload_id)
    assert (upload["status"], upload["error_code"]) == ("rejected", "too-many-slots")
    assert "1-slot limit" in upload["error_message"]


def running(client: TestClient) -> None:
    accept_yaml(client, "Knight")
    client.post("/api/game/lock")
    client.post("/api/game/generate")
    finish_with_zip(client, ["Knight"])
    assert client.post("/api/game/start").status_code == 200
    for _ in range(250):
        if client.get("/api/server").json()["state"] == "running":
            return
        time.sleep(0.02)
    raise AssertionError("the server never came up")


def test_the_server_settings_are_host_yaml_at_start(client: TestClient, settings: Settings) -> None:
    put(client, password="pw x", hint_cost=25, auto_shutdown=600)  # noqa: S106 - a test value
    user_dir = settings.game_dir / "ap" / "Archipelago"
    user_dir.mkdir(parents=True)
    (user_dir / "options.yaml").write_text("server_options: {}\n")  # AP would prefer it
    running(client)
    host_yaml = (user_dir / "host.yaml").read_text()
    assert 'password: "pw x"' in host_yaml
    assert "server_password: null" in host_yaml
    assert "hint_cost: 25" in host_yaml and "auto_shutdown: 600" in host_yaml
    assert "disable_item_cheat: true" in host_yaml
    assert not (user_dir / "options.yaml").exists()


def test_live_settings_reach_the_running_server(client: TestClient, settings: Settings) -> None:
    put(client, password="old")  # noqa: S106 - a test value
    running(client)
    saved = put(
        client,
        hint_cost=30,
        release_mode="auto-enabled",
        disable_item_cheat=False,
        password="",
        spoiler=0,  # not live: applies at the next generation
    )
    assert saved["applied_now"] == ["password", "release_mode", "hint_cost", "disable_item_cheat"]
    console = settings.game_dir / "output" / "AP_12345.console"
    for _ in range(100):
        if console.exists() and console.read_text().count("\n") >= 4:
            break
        time.sleep(0.02)
    assert console.read_text().splitlines() == [
        "/option password none",
        "/option release_mode auto_enabled",
        "/option hint_cost 30",
        "/option item_cheat true",
    ]


def test_nothing_is_live_while_the_server_is_stopped(client: TestClient) -> None:
    assert put(client, hint_cost=30)["applied_now"] == []


def test_a_password_with_a_space_is_quoted() -> None:
    old, new = HostSettings(), HostSettings(password="pw x")  # noqa: S106 - a test value
    assert host_settings.live_commands(old, new) == {"password": "/option password 'pw x'"}
