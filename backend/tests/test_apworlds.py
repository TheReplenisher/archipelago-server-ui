"""Apworld uploads through the API. The worker's import test needs Archipelago, so here its
results are written straight into done/ (the real job runs in docker/smoke-test.sh)."""

import os
from collections.abc import Iterator
from typing import Any

import pytest
from apsui_worker.protocol import (
    INPUT_DIR,
    RESULT_FILE,
    SPEC_FILE,
    JobResult,
    State,
    now,
    read_json_file,
    write_json_atomic,
)
from apworld_files import MANIFEST, make_apworld
from fastapi.testclient import TestClient

from apsui.config import Settings
from apsui.jobs import JobQueue
from apsui.main import create_app


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    settings.job_poll_interval = 3600  # tests collect by hand
    settings.archipelago_version = "0.6.8"
    with TestClient(create_app(settings)) as c:
        yield c


def loaded(replaces_builtin: str | None = None) -> dict[str, Any]:
    return {
        "archipelago_version": "0.6.8",
        "loaded": True,
        "games": ["Sample Game"],
        "replaces_builtin": replaces_builtin,
        "error": None,
        "detail": None,
    }


FAILED = loaded() | {
    "loaded": False,
    "games": [],
    "error": "ModuleNotFoundError: No module named 'x'",
    "detail": "Traceback (most recent call last):\n...",
}


def worker_finishes(client: TestClient, output: object, status: str = "ok") -> list[dict[str, Any]]:
    """Play the worker for every queued job, then let the web service collect. Returns the
    specs it was given."""
    jobs: JobQueue = client.app.state.jobs  # type: ignore[attr-defined]
    specs = []
    for job_id in jobs.dirs.ids(State.QUEUE):
        done = jobs.dirs.path(State.DONE, job_id)
        os.rename(jobs.dirs.path(State.QUEUE, job_id), done)
        spec = read_json_file(done / SPEC_FILE)
        spec["inputs"] = sorted(p.name for p in (done / INPUT_DIR).iterdir())
        specs.append(spec)
        result = JobResult(
            id=job_id,
            type="test-apworld",
            status=status,  # type: ignore[arg-type]
            started_at=now(),
            finished_at=now(),
            output=output if status == "ok" else None,
        )
        write_json_atomic(done / RESULT_FILE, result.to_json())
    with client.app.state.sessionmaker() as session:  # type: ignore[attr-defined]
        jobs.collect(session)
    return specs


def upload(
    client: TestClient, data: bytes | None = None, name: str = "sample_game.apworld"
) -> dict[str, Any]:
    response = client.post(
        "/api/apworlds", files={"file": (name, data or make_apworld(), "application/zip")}
    )
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


def apworlds(client: TestClient) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = client.get("/api/apworlds").json()
    return result


def test_an_apworld_is_checked_then_approved_into_the_library(
    client: TestClient, settings: Settings
) -> None:
    checking = upload(client)
    assert checking["status"] == "checking"
    assert checking["label"] == f"Sample Game · custom · v1.2.0 · {checking['sha256'][:6]}"

    [spec] = worker_finishes(client, loaded())
    assert spec["type"] == "test-apworld"
    assert spec["params"] == {"module": "sample_game", "game": "Sample Game"}
    assert spec["inputs"] == ["sample_game.apworld"]

    [pending] = apworlds(client)
    assert pending["status"] == "pending"
    review = client.get(f"/api/apworlds/{pending['id']}").json()
    assert review["manifest"]["game"] == "Sample Game"
    assert review["authors"] == ["Someone"]
    assert [f["name"] for f in review["files"]] == [
        "sample_game/__init__.py",
        "sample_game/archipelago.json",
    ]
    assert review["uploaded_by"] == "admin"
    assert review["import_test"]["loaded"] is True

    approved = client.post(f"/api/apworlds/{pending['id']}/approve").json()
    assert approved["status"] == "approved"
    assert (settings.library_dir / f"{approved['sha256']}.apworld").read_bytes() == make_apworld()
    assert not list((settings.uploads_dir / "apworlds").iterdir())


def test_the_admin_can_turn_an_apworld_down(client: TestClient, settings: Settings) -> None:
    pending = upload(client)
    worker_finishes(client, loaded())
    rejected = client.post(f"/api/apworlds/{pending['id']}/reject").json()
    assert (rejected["status"], rejected["error_code"]) == ("rejected", "rejected-by-admin")
    assert not list((settings.uploads_dir / "apworlds").iterdir())
    again = client.post(f"/api/apworlds/{pending['id']}/approve")
    assert (again.status_code, again.json()["detail"]["code"]) == (409, "not-pending")


def test_a_bad_file_is_rejected_without_running_anything(client: TestClient) -> None:
    data = make_apworld(manifest=MANIFEST | {"minimum_ap_version": "0.7.0"})
    rejected = upload(client, data)
    assert (rejected["status"], rejected["error_code"]) == ("rejected", "ap-too-old")
    assert worker_finishes(client, loaded()) == []


def test_an_apworld_that_fails_to_load_is_rejected(client: TestClient) -> None:
    pending = upload(client)
    worker_finishes(client, FAILED)
    review = client.get(f"/api/apworlds/{pending['id']}").json()
    assert (review["status"], review["error_code"]) == ("rejected", "import-failed")
    assert "No module named 'x'" in review["error_message"]
    assert review["import_test"]["detail"].startswith("Traceback")


def test_a_failed_job_rejects_with_its_error(client: TestClient) -> None:
    pending = upload(client)
    worker_finishes(client, None, status="timeout")
    review = client.get(f"/api/apworlds/{pending['id']}").json()
    assert (review["status"], review["error_code"]) == ("rejected", "check-failed")
    assert review["import_test"]["loaded"] is False


def test_unreadable_worker_output_rejects(client: TestClient) -> None:
    upload(client)
    worker_finishes(client, {"loaded": "yes"})
    assert apworlds(client)[0]["error_code"] == "check-failed"


def test_replacing_a_built_in_world_is_flagged(client: TestClient) -> None:
    upload(client)
    worker_finishes(client, loaded(replaces_builtin="2.0.0"))
    [pending] = apworlds(client)
    assert (pending["status"], pending["replaces_builtin"]) == ("pending", "2.0.0")


def test_auto_approval_skips_the_admin(client: TestClient, settings: Settings) -> None:
    settings.apworld_approval = "auto"
    upload(client)
    worker_finishes(client, loaded())
    assert apworlds(client)[0]["status"] == "approved"


def test_auto_approval_still_waits_for_a_built_in_replacement(
    client: TestClient, settings: Settings
) -> None:
    settings.apworld_approval = "auto"
    upload(client)
    worker_finishes(client, loaded(replaces_builtin="2.0.0"))
    assert apworlds(client)[0]["status"] == "pending"


def test_the_same_file_is_only_taken_once(client: TestClient) -> None:
    first = upload(client)
    response = client.post(
        "/api/apworlds", files={"file": ("sample_game.apworld", make_apworld(), "application/zip")}
    )
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "already-uploaded")

    # Once turned down, the same file may be tried again.
    worker_finishes(client, FAILED)
    assert apworlds(client)[0]["id"] == first["id"]
    assert upload(client)["status"] == "checking"


def test_an_unknown_apworld_is_404(client: TestClient) -> None:
    assert client.get("/api/apworlds/99").status_code == 404
    assert client.post("/api/apworlds/99/approve").status_code == 404
