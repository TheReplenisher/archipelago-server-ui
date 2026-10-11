"""Library apworlds picked for YAML uploads, and per-game version locking (DESIGN.md §4).
The worker's results are written straight into done/, as in test_uploads."""

from collections.abc import Iterator
from typing import Any

import pytest
from apworld_files import MANIFEST, make_apworld
from fastapi.testclient import TestClient
from worker_sim import worker_finishes

from apsui.config import Settings
from apsui.main import create_app
from apsui.worlds import LOCKED_MESSAGE

YAML = b"name: %s\ngame: Sample Game\nSample Game: {}\n"
OFFICIAL_YAML = b"name: Quester\ngame: APQuest\nAPQuest: {}\n"


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    settings.job_poll_interval = 3600  # tests collect by hand
    settings.archipelago_version = "0.6.8"
    with TestClient(create_app(settings)) as c:
        yield c


def checked(game: str = "Sample Game", custom: bool = True, name: str = "Knight") -> dict[str, Any]:
    """A validate-yaml result: every document accepted, named from the YAML."""

    def output(spec: dict[str, Any]) -> dict[str, Any]:
        return {
            "error": None,
            "documents": [
                {
                    "index": 0,
                    "empty": False,
                    "name": name,
                    "name_raw": name,
                    "games": [game],
                    "error": None,
                }
            ],
            "custom_games": [game] if custom else [],
        }

    return {"validate-yaml": output}


def library_apworld(
    client: TestClient, version: str = "1.0.0", replaces_builtin: str | None = None
) -> int:
    data = make_apworld(manifest=MANIFEST | {"world_version": version})
    response = client.post(
        "/api/apworlds", files={"file": ("sample_game.apworld", data, "application/zip")}
    )
    assert response.status_code == 202, response.text
    apworld_id: int = response.json()["id"]
    worker_finishes(
        client,
        {
            "test-apworld": {
                "archipelago_version": "0.6.8",
                "loaded": True,
                "games": ["Sample Game"],
                "replaces_builtin": replaces_builtin,
                "error": None,
                "detail": None,
            }
        },
    )
    client.post(f"/api/apworlds/{apworld_id}/approve")
    return apworld_id


def upload(
    client: TestClient,
    apworld_ids: list[int] | None = None,
    data: bytes | None = None,
    status: int = 202,
) -> dict[str, Any]:
    response = client.post(
        "/api/uploads/yaml",
        files={"file": ("p.yaml", data or YAML % b"Knight", "text/yaml")},
        data={"apworld_ids": [str(i) for i in apworld_ids or []]},
    )
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    return body


def worlds(client: TestClient) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = client.get("/api/worlds").json()
    return result


def statuses(client: TestClient) -> dict[int, tuple[str, str | None]]:
    return {u["id"]: (u["status"], u["error_code"]) for u in client.get("/api/uploads").json()}


def test_a_game_without_a_pick_uses_and_locks_the_official_world(client: TestClient) -> None:
    upload(client, data=OFFICIAL_YAML)
    [spec] = worker_finishes(client, checked("APQuest", custom=False))
    assert spec["inputs"] == ["upload.yaml"]
    assert worlds(client) == [
        {
            "world": "APQuest",
            "label": "APQuest · official · AP 0.6.8",
            "apworld_id": None,
            "upload_id": 1,
        }
    ]


def test_a_picked_apworld_is_checked_with_and_locks_the_game(client: TestClient) -> None:
    v1 = library_apworld(client)
    first = upload(client, [v1])
    [spec] = worker_finishes(client, checked())
    assert spec["inputs"] == ["sample_game.apworld", "upload.yaml"]
    assert statuses(client)[first["id"]] == ("accepted", None)
    [lock] = worlds(client)
    assert (lock["world"], lock["apworld_id"]) == ("Sample Game", v1)
    assert lock["label"].startswith("Sample Game · custom · v1.0.0 · ")


def test_later_uploads_get_the_locked_apworld_without_picking(client: TestClient) -> None:
    v1 = library_apworld(client)
    upload(client, [v1])
    worker_finishes(client, checked())
    second = upload(client, data=YAML % b"Hornet")
    [spec] = worker_finishes(client, checked(name="Hornet"))
    assert spec["inputs"] == ["sample_game.apworld", "upload.yaml"]
    assert statuses(client)[second["id"]] == ("accepted", None)


def test_a_different_version_is_refused_once_the_game_is_locked(client: TestClient) -> None:
    v1, v2 = library_apworld(client, "1.0.0"), library_apworld(client, "2.0.0")
    first = upload(client, [v1])
    second = upload(client, [v2], data=YAML % b"Hornet")
    worker_finishes(client, checked())  # both were checked before either locked the game
    assert statuses(client)[first["id"]] == ("accepted", None)
    assert statuses(client)[second["id"]] == ("rejected", "version-locked")
    rejected = next(u for u in client.get("/api/uploads").json() if u["id"] == second["id"])
    assert rejected["error_message"] == LOCKED_MESSAGE


def test_a_pick_the_worker_did_not_load_is_rejected(client: TestClient) -> None:
    v1 = library_apworld(client)
    first = upload(client, [v1])
    worker_finishes(client, checked(custom=False))
    assert statuses(client)[first["id"]] == ("rejected", "world-not-loaded")
    assert worlds(client) == []


def test_removing_the_last_yaml_for_a_game_unlocks_it(client: TestClient) -> None:
    v1 = library_apworld(client)
    first = upload(client, [v1])
    worker_finishes(client, checked())
    assert client.delete(f"/api/uploads/{first['id']}").status_code == 200
    assert worlds(client) == []


@pytest.mark.parametrize("case", ["pending", "builtin", "twice", "unknown"])
def test_bad_picks_are_refused_at_upload(client: TestClient, case: str) -> None:
    if case == "pending":
        data = make_apworld(manifest=MANIFEST | {"world_version": "3.0.0"})
        picks = [
            client.post("/api/apworlds", files={"file": ("sample_game.apworld", data)}).json()["id"]
        ]
        code = "apworld-unavailable"
    elif case == "builtin":
        picks, code = (
            [library_apworld(client, replaces_builtin="2.0.0")],
            "builtin-replacement-unsupported",
        )
    elif case == "twice":
        picks, code = (
            [library_apworld(client, "1.0.0"), library_apworld(client, "2.0.0")],
            "two-versions",
        )
    else:
        picks, code = [99], "apworld-unavailable"
    body = upload(client, picks, status=400)
    assert body["detail"]["code"] == code
