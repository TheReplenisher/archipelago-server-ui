"""Manual generation (#18). The worker's generate job needs Archipelago, so its results
are written straight into done/; the real job runs in docker/compose-test.sh."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from apsui_worker.protocol import JobError
from apworld_files import make_apworld
from fastapi.testclient import TestClient
from game_flow import accept_yaml, finish_with_zip, output_zip
from worker_sim import worker_finishes

from apsui.config import Settings
from apsui.main import create_app


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    settings.job_poll_interval = 3600  # tests collect by hand
    with TestClient(create_app(settings)) as c:
        yield c


def game(client: TestClient) -> dict[str, Any]:
    result: dict[str, Any] = client.get("/api/game").json()
    return result


def test_generation_runs_from_locked_and_stores_the_output(
    client: TestClient, settings: Settings
) -> None:
    first, second = accept_yaml(client, "Knight"), accept_yaml(client, "Hornet")
    assert client.post("/api/game/lock").status_code == 200
    assert "generate" in game(client)["actions"]

    response = client.post("/api/game/generate")
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "running"
    assert game(client)["state"] == "generating"

    [spec] = finish_with_zip(client, ["Knight", "Hornet"])
    assert spec["type"] == "generate"
    assert spec["inputs"] == [f"{first}.yaml", f"{second}.yaml"]
    assert game(client)["state"] == "generated"
    assert game(client)["actions"] == ["discard-output", "start"]
    [entry] = client.get("/api/game/generations").json()
    assert (entry["status"], entry["seed_name"], entry["players"]) == (
        "ok",
        "12345",
        ["Knight", "Hornet"],
    )
    assert (settings.game_dir / "output" / "AP_12345.zip").read_bytes() == output_zip()


def test_locked_custom_apworlds_are_given_to_generation(client: TestClient) -> None:
    response = client.post("/api/apworlds", files={"file": ("sample_game.apworld", make_apworld())})
    apworld_id = response.json()["id"]
    loaded = {"archipelago_version": "0.6.8", "loaded": True, "games": ["Sample Game"]}
    worker_finishes(
        client, {"test-apworld": loaded | {"replaces_builtin": None, "error": None, "detail": None}}
    )
    client.post(f"/api/apworlds/{apworld_id}/approve")
    accept_yaml(client, "Knight", game="Sample Game", apworld_ids=[apworld_id])
    client.post("/api/game/lock")
    client.post("/api/game/generate")
    [spec] = finish_with_zip(client, ["Knight"])
    assert "sample_game.apworld" in spec["inputs"]


def test_a_failure_returns_to_locked_and_names_the_culprit(client: TestClient) -> None:
    accept_yaml(client, "Knight")
    hornet = accept_yaml(client, "Hornet")
    client.post("/api/game/lock")
    client.post("/api/game/generate")
    traceback = f"Traceback ...\nValueError: File {hornet}.yaml is invalid. Please fix your yaml."
    worker_finishes(
        client, {}, error=JobError("exception", "ValueError: Encountered 1 error(s)", traceback)
    )

    assert game(client)["state"] == "locked"
    [entry] = client.get("/api/game/generations").json()
    assert (entry["status"], entry["error_code"]) == ("failed", "exception")
    assert entry["culprits"] == [
        {"upload_id": hornet, "filename": "hornet.yaml", "slots": ["Hornet"]}
    ]
    assert entry["traceback"].startswith("Traceback")


def test_a_slot_name_in_the_error_also_names_the_culprit(client: TestClient) -> None:
    knight = accept_yaml(client, "Knight")
    accept_yaml(client, "Hornet")
    client.post("/api/game/lock")
    client.post("/api/game/generate")
    worker_finishes(
        client,
        {},
        error=JobError("exception", "Exception: Knight's world could not be filled", None),
    )
    [entry] = client.get("/api/game/generations").json()
    assert [c["upload_id"] for c in entry["culprits"]] == [knight]


def test_output_that_is_missing_or_not_a_zip_fails(client: TestClient) -> None:
    accept_yaml(client, "Knight")
    client.post("/api/game/lock")
    client.post("/api/game/generate")
    finish_with_zip(client, ["Knight"], data=b"not a zip")
    assert game(client)["state"] == "locked"
    assert client.get("/api/game/generations").json()[0]["error_code"] == "no-output"


def test_generate_needs_locked_uploads_and_a_slot(client: TestClient) -> None:
    response = client.post("/api/game/generate")
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "not-locked")
    client.post("/api/game/lock")
    response = client.post("/api/game/generate")
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "no-slots")


def test_discarding_the_output_returns_to_locked(client: TestClient, settings: Settings) -> None:
    accept_yaml(client, "Knight")
    client.post("/api/game/lock")
    client.post("/api/game/generate")
    finish_with_zip(client, ["Knight"])
    response = client.post("/api/game/discard-output")
    assert (response.status_code, response.json()["state"]) == (200, "locked")
    assert not Path(settings.game_dir / "output").exists()
