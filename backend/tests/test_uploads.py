"""YAML uploads through the API. The worker's validate-yaml job needs Archipelago, so here
its results are written straight into done/ (the real job runs in docker/smoke-test.sh)."""

import os
from collections.abc import Iterator
from typing import Any

import pytest
from apsui_worker.protocol import RESULT_FILE, JobResult, State, now, write_json_atomic
from fastapi.testclient import TestClient

from apsui.config import Settings
from apsui.jobs import JobQueue
from apsui.main import create_app

YAML = b"name: Quester\ngame: APQuest\nAPQuest: {}\n"


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    settings.max_slots = 3
    settings.job_poll_interval = 3600  # tests collect by hand
    with TestClient(create_app(settings)) as c:
        yield c


def doc(name: str | None, index: int = 0, error: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "index": index,
        "empty": False,
        "name": name,
        "quantity": 1,
        "games": ["APQuest"],
        "error": error,
        "warnings": [],
    }


def worker_finishes(client: TestClient, output: object, status: str = "ok") -> None:
    """Play the worker for every queued job, then let the web service collect."""
    jobs: JobQueue = client.app.state.jobs  # type: ignore[attr-defined]
    for job_id in jobs.dirs.ids(State.QUEUE):
        os.rename(jobs.dirs.path(State.QUEUE, job_id), jobs.dirs.path(State.DONE, job_id))
        result = JobResult(
            id=job_id,
            type="validate-yaml",
            status=status,  # type: ignore[arg-type]
            started_at=now(),
            finished_at=now(),
            output=output if status == "ok" else None,
        )
        write_json_atomic(jobs.dirs.path(State.DONE, job_id) / RESULT_FILE, result.to_json())
    with client.app.state.sessionmaker() as session:  # type: ignore[attr-defined]
        jobs.collect(session)


def upload(client: TestClient, data: bytes = YAML, name: str = "quester.yaml") -> dict[str, Any]:
    response = client.post("/api/uploads/yaml", files={"file": (name, data, "text/yaml")})
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


def uploads(client: TestClient) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = client.get("/api/uploads").json()
    return result


def test_accepted_yaml_becomes_a_slot(client: TestClient, settings: Settings) -> None:
    pending = upload(client)
    assert pending["status"] == "pending"
    worker_finishes(client, {"error": None, "documents": [doc("Quester")]})

    [accepted] = uploads(client)
    assert (accepted["status"], accepted["slots"]) == ("accepted", ["Quester"])
    assert client.get("/api/slots").json() == [
        {"name": "Quester", "games": ["APQuest"], "upload_id": accepted["id"]}
    ]
    stored = settings.game_dir / "yamls" / f"{accepted['id']}.yaml"
    assert stored.read_bytes() == YAML  # the admin's bytes, not anything from the worker
    assert not list(settings.uploads_dir.iterdir())


def test_worker_error_is_the_short_message(client: TestClient) -> None:
    upload(client)
    error = {
        "code": "option-invalid",
        "message": "Invalid value for option trap_chance",
        "detail": "long traceback",
    }
    worker_finishes(client, {"error": None, "documents": [doc("Quester", error=error)]})
    [rejected] = uploads(client)
    assert (rejected["status"], rejected["error_code"]) == ("rejected", "option-invalid")
    assert rejected["error_message"] == "Invalid value for option trap_chance"
    assert "traceback" not in str(rejected)  # the detail is for the upload log only
    assert client.get("/api/slots").json() == []


def test_names_are_unique_across_the_game_ignoring_case(client: TestClient) -> None:
    upload(client)
    worker_finishes(client, {"error": None, "documents": [doc("Quester")]})
    upload(client, name="again.yaml")
    worker_finishes(client, {"error": None, "documents": [doc("QUESTER")]})
    rejected = uploads(client)[0]
    assert (rejected["error_code"], rejected["error_message"]) == (
        "name-taken",
        "Slot name QUESTER is already taken",
    )


def test_duplicate_names_inside_one_file(client: TestClient) -> None:
    upload(client)
    worker_finishes(client, {"error": None, "documents": [doc("A"), doc("a", index=1)]})
    assert uploads(client)[0]["error_code"] == "name-duplicate"


def test_slot_limit(client: TestClient) -> None:  # max_slots = 3
    upload(client)
    worker_finishes(client, {"error": None, "documents": [doc("A"), doc("B", 1)]})
    upload(client)
    worker_finishes(client, {"error": None, "documents": [doc("C"), doc("D", 1)]})
    assert uploads(client)[0]["error_code"] == "too-many-slots"
    assert len(client.get("/api/slots").json()) == 2


@pytest.mark.parametrize(
    "output",
    [
        {"documents": "not a list"},
        {"error": None, "documents": [{"index": "x"}]},
        None,
    ],
)
def test_malformed_worker_output_is_rejected_not_trusted(
    client: TestClient, output: object
) -> None:
    upload(client)
    worker_finishes(client, output)
    assert uploads(client)[0]["error_code"] == "check-failed"


def test_failed_job_is_rejected(client: TestClient) -> None:
    upload(client)
    worker_finishes(client, None, status="timeout")
    assert uploads(client)[0]["error_code"] == "check-failed"


def test_uploads_only_while_open(client: TestClient) -> None:
    assert client.post("/api/game/lock").status_code == 200
    response = client.post("/api/uploads/yaml", files={"file": ("a.yaml", YAML)})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "uploads-closed"


def test_lock_waits_for_pending_checks(client: TestClient) -> None:
    upload(client)
    response = client.post("/api/game/lock")
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "uploads-pending")
    worker_finishes(client, {"error": None, "documents": [doc("Quester")]})
    assert client.post("/api/game/lock").status_code == 200


def test_size_and_empty_limits(client: TestClient) -> None:
    big = client.post("/api/uploads/yaml", files={"file": ("big.yaml", b"x" * 600_000)})
    assert big.status_code == 413
    empty = client.post("/api/uploads/yaml", files={"file": ("e.yaml", b"  \n")})
    assert empty.json()["detail"]["code"] == "empty"


def test_remove_an_accepted_upload(client: TestClient, settings: Settings) -> None:
    upload(client)
    worker_finishes(client, {"error": None, "documents": [doc("Quester")]})
    upload_id = uploads(client)[0]["id"]
    removed = client.delete(f"/api/uploads/{upload_id}").json()
    assert (removed["status"], removed["slots"]) == ("removed", [])
    assert client.get("/api/slots").json() == []
    assert not (settings.game_dir / "yamls" / f"{upload_id}.yaml").exists()
    # the name is free again
    upload(client)
    worker_finishes(client, {"error": None, "documents": [doc("Quester")]})
    assert uploads(client)[0]["status"] == "accepted"


def test_a_pending_upload_cannot_be_removed(client: TestClient) -> None:
    upload_id = upload(client)["id"]
    assert client.delete(f"/api/uploads/{upload_id}").status_code == 409


def test_accepting_across_filesystems(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under Compose, uploads/ and game/ are different volumes: rename fails with EXDEV."""
    import errno

    real_rename = os.rename

    def rename(src: object, dst: object) -> None:
        if str(settings.game_dir) in str(dst):
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        real_rename(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "rename", rename)
    upload(client)
    worker_finishes(client, {"error": None, "documents": [doc("Quester")]})
    assert uploads(client)[0]["status"] == "accepted"


def test_a_storage_failure_rejects_instead_of_leaving_it_pending(
    client: TestClient, settings: Settings
) -> None:
    settings.game_dir.mkdir(parents=True, exist_ok=True)
    (settings.game_dir / "yamls").write_text("a file where the folder should be")
    upload(client)
    worker_finishes(client, {"error": None, "documents": [doc("Quester")]})
    [rejected] = uploads(client)
    assert (rejected["status"], rejected["error_code"]) == ("rejected", "store-failed")
    assert client.get("/api/slots").json() == []
    assert client.post("/api/game/lock").status_code == 200  # nothing left pending
