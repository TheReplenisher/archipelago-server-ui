"""The admin's upload log: every upload with who, when, hash, each check and the worker's
full error (DESIGN.md §4)."""

from collections.abc import Iterator
from typing import Any

import pytest
from apsui_worker.protocol import JobError
from apworld_files import MANIFEST, make_apworld
from fastapi.testclient import TestClient
from worker_sim import worker_finishes

from apsui.config import Settings
from apsui.main import create_app

YAML = b"name: Knight\ngame: APQuest\nAPQuest: {}\n"


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    settings.job_poll_interval = 3600  # tests collect by hand
    with TestClient(create_app(settings)) as c:
        yield c


def doc(name: str | None = "Knight", **extra: Any) -> dict[str, Any]:
    return {
        "index": 0,
        "empty": False,
        "name": name,
        "name_raw": name,
        "games": ["APQuest"],
    } | extra


def validated(*documents: dict[str, Any]) -> dict[str, Any]:
    return {"validate-yaml": {"error": None, "documents": list(documents)}}


def upload_yaml(client: TestClient) -> int:
    response = client.post("/api/uploads/yaml", files={"file": ("knight.yaml", YAML)})
    assert response.status_code == 202, response.text
    upload_id: int = response.json()["id"]
    return upload_id


def log(client: TestClient, kind: str, item_id: int) -> dict[str, Any]:
    response = client.get(f"/api/logs/uploads/{kind}/{item_id}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def checks(entry: dict[str, Any]) -> list[tuple[str, str]]:
    return [(c["name"], c["status"]) for c in entry["checks"]]


def test_an_accepted_yaml_shows_who_when_hash_and_each_check(client: TestClient) -> None:
    upload_id = upload_yaml(client)
    worker_finishes(client, validated(doc()))
    entry = log(client, "yaml", upload_id)
    assert (entry["key"], entry["uploaded_by"], entry["status"]) == (
        f"yaml-{upload_id}",
        "admin",
        "accepted",
    )
    assert len(entry["sha256"]) == 64 and entry["uploaded_at"]
    assert checks(entry) == [
        ("Stored", "ok"),
        ("Parse", "ok"),
        ("Document 1 (Knight)", "ok"),
        ("Result", "ok"),
    ]
    assert entry["job"]["type"] == "validate-yaml" and entry["job"]["status"] == "ok"


def test_a_rejected_yaml_keeps_the_full_detail(client: TestClient) -> None:
    upload_id = upload_yaml(client)
    error = {
        "code": "option-invalid",
        "message": "Invalid value",
        "detail": "APQuest option x = 9: too big",
    }
    worker_finishes(client, validated(doc(error=error)))
    entry = log(client, "yaml", upload_id)
    failed = next(c for c in entry["checks"] if c["status"] == "failed")
    assert failed["detail"] == "APQuest option x = 9: too big"
    assert entry["checks"][-1]["message"] == "option-invalid: Invalid value"


def test_a_crashed_worker_job_shows_its_traceback(client: TestClient) -> None:
    upload_id = upload_yaml(client)
    worker_finishes(
        client, {}, error=JobError("exception", "KeyError: 'x'", "Traceback ...\nKeyError: 'x'")
    )
    entry = log(client, "yaml", upload_id)
    assert ("Worker check", "failed") in checks(entry)
    assert entry["job"]["traceback"].startswith("Traceback")
    assert entry["job"]["log_tail"] == "worker log tail"
    # The uploader only sees the short error.
    upload = client.get("/api/uploads").json()[0]
    assert "Traceback" not in str(upload)


def test_a_renamed_slot_is_in_the_log(client: TestClient) -> None:
    upload_id = upload_yaml(client)
    name_error = {"code": "name-not-fixed", "message": "Slot name must be one fixed name"}
    worker_finishes(client, validated(doc(name=None, name_raw=["A", "B"], name_error=name_error)))
    assert ("Slot name", "waiting") in checks(log(client, "yaml", upload_id))

    client.post(
        f"/api/uploads/{upload_id}/rename", json={"names": [{"document": 0, "name": "Alice"}]}
    )
    worker_finishes(client, validated(doc(name="Alice")))
    entry = log(client, "yaml", upload_id)
    renamed = next(c for c in entry["checks"] if c["name"] == "Slot name")
    assert (renamed["status"], renamed["message"]) == (
        "ok",
        "Slot name must be one fixed name; renamed to Alice",
    )


def test_apworld_entries_show_inspection_import_test_and_built_in_warning(
    client: TestClient,
) -> None:
    bad = client.post(
        "/api/apworlds",
        files={
            "file": (
                "sample_game.apworld",
                make_apworld(manifest=MANIFEST | {"compatible_version": 9}),
            )
        },
    ).json()
    assert checks(log(client, "apworld", bad["id"])) == [
        ("Static inspection", "failed"),
        ("Result", "failed"),
    ]

    good = client.post(
        "/api/apworlds", files={"file": ("sample_game.apworld", make_apworld())}
    ).json()
    worker_finishes(
        client,
        {
            "test-apworld": {
                "archipelago_version": "0.6.8",
                "loaded": False,
                "games": [],
                "replaces_builtin": "2.0.0",
                "error": "ImportError: nope",
                "detail": "Traceback ...",
            }
        },
    )
    entry = log(client, "apworld", good["id"])
    assert checks(entry) == [
        ("Static inspection", "ok"),
        ("Import test", "failed"),
        ("Built-in world", "warning"),
        ("Result", "failed"),
    ]
    assert entry["checks"][1]["detail"] == "Traceback ..."


def test_the_list_has_every_kind_newest_first(client: TestClient) -> None:
    upload_yaml(client)
    client.post("/api/apworlds", files={"file": ("sample_game.apworld", make_apworld())})
    entries = client.get("/api/logs/uploads").json()
    assert [e["kind"] for e in entries] == ["apworld", "yaml"]


def test_an_unknown_entry_is_404(client: TestClient) -> None:
    assert client.get("/api/logs/uploads/yaml/99").status_code == 404
    assert client.get("/api/logs/uploads/rom/1").status_code == 422
