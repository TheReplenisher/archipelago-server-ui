"""Archive, restore, delete and retention (#19). Running games are archived through a
real supervisor with a stand-in MultiServer, as in test_hosting."""

import io
import json
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from apsui_server.supervisor import Supervisor
from apsui_server.testing import running_supervisor
from fastapi.testclient import TestClient
from game_flow import accept_yaml, generated_game
from test_hosting import FAKE_MULTISERVER

from apsui.config import Settings
from apsui.main import create_app


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


def game(client: TestClient) -> dict[str, Any]:
    result: dict[str, Any] = client.get("/api/game").json()
    return result


def archive(client: TestClient, status: int = 200) -> dict[str, Any]:
    response = client.post("/api/game/archive")
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    return body


def listing(client: TestClient) -> dict[str, Any]:
    result: dict[str, Any] = client.get("/api/archives").json()
    return result


def set_retention(client: TestClient, **values: Any) -> None:
    current = client.get("/api/settings").json()["values"]
    response = client.put("/api/settings", json=current | values)
    assert response.status_code == 200, response.text


def wait_running(client: TestClient) -> None:
    for _ in range(250):
        if client.get("/api/server").json()["state"] == "running":
            return
        time.sleep(0.02)
    raise AssertionError("the server never came up")


def test_archive_moves_the_game_out_and_opens_a_new_one(
    client: TestClient, settings: Settings
) -> None:
    generated_game(client, "Knight", "Hornet")
    first = game(client)["id"]
    new = archive(client)
    assert new["state"] == "open" and new["id"] != first
    assert list(settings.game_dir.iterdir()) == []

    [entry] = listing(client)["archives"]
    assert (entry["id"], entry["archived_from"], entry["seed_name"]) == (
        first,
        "generated",
        "12345",
    )
    assert entry["slots"] == ["Knight", "Hornet"] and entry["size"] > 0
    detail = client.get(f"/api/archives/{first}").json()
    paths = {f["path"] for f in detail["files"]}
    assert {"archive.json", "output/AP_12345.zip", "yamls/1.yaml", "yamls/2.yaml"} <= paths
    assert [g["status"] for g in detail["generations"]] == ["ok"]
    assert {u["filename"] for u in detail["uploads"]} == {"knight.yaml", "hornet.yaml"}


def test_archiving_a_running_game_saves_and_stops_it_first(
    client: TestClient, settings: Settings
) -> None:
    generated_game(client, "Knight")
    assert client.post("/api/game/start").status_code == 200
    wait_running(client)
    first = game(client)["id"]
    archive(client)
    assert client.get("/api/server").json()["state"] == "stopped"
    [entry] = listing(client)["archives"]
    assert entry["archived_from"] == "generated"
    paths = {f["path"] for f in client.get(f"/api/archives/{first}").json()["files"]}
    assert "output/AP_12345.apsave" in paths  # Stop saved first


def test_an_open_or_locked_game_can_be_archived_but_not_an_empty_one(client: TestClient) -> None:
    body = archive(client, 409)
    assert body["detail"]["code"] == "nothing-to-archive"
    accept_yaml(client, "Knight")
    client.post("/api/game/lock")
    archive(client)
    assert listing(client)["archives"][0]["archived_from"] == "locked"


def test_archive_waits_for_generation(client: TestClient) -> None:
    accept_yaml(client, "Knight")
    client.post("/api/game/lock")
    client.post("/api/game/generate")
    assert archive(client, 409)["detail"]["code"] == "generating"


def test_restore_into_an_empty_game(client: TestClient, settings: Settings) -> None:
    generated_game(client, "Knight")
    first = game(client)["id"]
    archive(client)
    response = client.post(f"/api/archives/{first}/restore", json={})
    assert response.status_code == 200, response.text
    assert (response.json()["id"], response.json()["state"]) == (first, "generated")
    assert (settings.game_dir / "output" / "AP_12345.zip").is_file()
    assert (settings.game_dir / "yamls" / "1.yaml").is_file()
    assert listing(client)["archives"] == []
    assert not (settings.data_dir / "archives" / str(first)).exists()
    assert [s["name"] for s in client.get("/api/slots").json()] == ["Knight"]
    # and it can be started again
    assert client.post("/api/game/start").status_code == 200


def test_restore_returns_to_the_state_it_was_archived_from(client: TestClient) -> None:
    accept_yaml(client, "Knight")
    first = game(client)["id"]
    archive(client)
    restored = client.post(f"/api/archives/{first}/restore", json={}).json()
    assert restored["state"] == "open"
    assert restored["actions"] == ["lock"]


@pytest.mark.parametrize("choice", ["archive", "delete"])
def test_a_current_game_with_uploads_is_archived_or_deleted_first(
    client: TestClient, choice: str
) -> None:
    generated_game(client, "Knight")
    first = game(client)["id"]
    archive(client)
    accept_yaml(client, "Hornet")
    second = game(client)["id"]

    refused = client.post(f"/api/archives/{first}/restore", json={})
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["code"] == "current-game"
    assert detail["current"] == {"id": second, "state": "open", "slots": 1}

    response = client.post(f"/api/archives/{first}/restore", json={"current": choice})
    assert response.status_code == 200, response.text
    assert game(client)["id"] == first
    archived = [a["id"] for a in listing(client)["archives"]]
    assert archived == ([second] if choice == "archive" else [])
    if choice == "delete":
        log = client.get("/api/logs/uploads").json()
        assert [e["filename"] for e in log] == ["knight.yaml"]


def test_delete_an_archive(client: TestClient, settings: Settings) -> None:
    generated_game(client, "Knight")
    first = game(client)["id"]
    archive(client)
    assert client.delete(f"/api/archives/{first}").status_code == 200
    assert listing(client)["archives"] == []
    assert not (settings.data_dir / "archives" / str(first)).exists()
    assert client.get(f"/api/archives/{first}").status_code == 404
    assert client.get("/api/logs/uploads").json() == []


def test_retention_by_count_deletes_the_oldest(client: TestClient) -> None:
    set_retention(client, archive_limit="count", archive_max_count=2)
    ids = []
    for name in ("One", "Two", "Three"):
        accept_yaml(client, name)
        ids.append(game(client)["id"])
        archive(client)
    assert [a["id"] for a in listing(client)["archives"]] == [ids[2], ids[1]]


def test_retention_by_size_keeps_at_least_the_newest(client: TestClient) -> None:
    set_retention(client, archive_limit="size", archive_max_size_mb=1)
    accept_yaml(client, "One")
    archive(client)
    big = listing(client)["archives"][0]["size"]
    assert big < 1024 * 1024  # these archives are small: both fit
    accept_yaml(client, "Two")
    newest = game(client)["id"]
    archive(client)
    assert len(listing(client)["archives"]) == 2
    retention = listing(client)["retention"]
    assert (retention["limit"], retention["count"]) == ("size", 2)
    set_retention(client, archive_limit="count", archive_max_count=1)
    accept_yaml(client, "Three")
    archive(client)
    assert newest not in [a["id"] for a in listing(client)["archives"]]


def test_download_the_whole_archive_and_single_files(client: TestClient) -> None:
    generated_game(client, "Knight")
    first = game(client)["id"]
    archive(client)
    response = client.get(f"/api/archives/{first}/download")
    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith(f'archive-{first}-AP_12345.zip"')
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        names = set(zf.namelist())
        meta = json.loads(zf.read("archive.json"))
    assert {"archive.json", "output/AP_12345.zip", "yamls/1.yaml"} <= names
    assert meta["slots"] == [{"name": "Knight", "games": ["APQuest"]}]

    one = client.get(f"/api/archives/{first}/files/yamls/1.yaml")
    assert one.status_code == 200 and b"name: Knight" in one.content
    assert one.headers["cache-control"] == "no-store"
    # Encoded, so the client doesn't resolve the dots itself and the server sees them.
    for bad in ("%2E%2E/%2E%2E/app.db", "yamls/%2E%2E/%2E%2E/%2E%2E/app.db", "missing.txt"):
        assert client.get(f"/api/archives/{first}/files/{bad}").status_code == 404, bad


def test_symlinks_in_the_game_folder_are_never_followed(
    client: TestClient, settings: Settings
) -> None:
    """The server service can write to the game folder; it must not get app.db archived."""
    generated_game(client, "Knight")
    first = game(client)["id"]
    (settings.game_dir / "output" / "evil.zip").symlink_to(settings.data_dir / "app.db")
    (settings.game_dir / "logs").symlink_to(settings.data_dir)
    archive(client)
    paths = {f["path"] for f in client.get(f"/api/archives/{first}").json()["files"]}
    assert not any("evil" in p or "app.db" in p or p.startswith("logs/") for p in paths)


def test_what_the_web_service_may_not_remove_in_ap_is_left(
    client: TestClient, settings: Settings
) -> None:
    """MultiServer's copies of AP's default files can carry a label the web service can't
    open (SELinux); they aren't the game's, so they don't stop ARCHIVE."""
    generated_game(client, "Knight")
    locked = settings.game_dir / "ap" / "Archipelago" / "data" / "lua"
    locked.mkdir(parents=True)
    (locked / "connector.lua").write_text("--")
    locked.chmod(0)
    try:
        archive(client)
        assert {p.name for p in settings.game_dir.iterdir()} == {"ap"}
    finally:
        locked.chmod(0o755)
