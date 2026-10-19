"""Backup and restore (#38)."""

import io
import json
import time
import zipfile
from collections.abc import Iterator
from typing import Any

import pytest
from apworld_files import make_apworld
from fastapi.testclient import TestClient
from game_flow import accept_yaml
from worker_sim import worker_finishes

from apsui.config import Settings
from apsui.main import create_app

LOADED = {
    "archipelago_version": "0.6.8",
    "loaded": True,
    "games": ["Sample Game"],
    "replaces_builtin": None,
    "error": None,
    "detail": None,
}


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    settings.job_poll_interval = 3600  # tests collect by hand
    with TestClient(create_app(settings)) as c:
        yield c


def backup(client: TestClient, archives: bool = True) -> dict[str, Any]:
    before = {b["name"] for b in client.get("/api/backups").json()["backups"]}
    assert client.post("/api/backups", json={"archives": archives}).status_code == 202
    for _ in range(250):
        listing = client.get("/api/backups").json()
        new = [b for b in listing["backups"] if b["name"] not in before]
        if new and not listing["making"]:
            [made] = new
            return made
        time.sleep(0.02)
    raise AssertionError("the backup was never made")


def restore(client: TestClient, name: str, status: int = 200) -> dict[str, Any]:
    response = client.post(f"/api/backups/{name}/restore")
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    return body


def approved_apworld(client: TestClient) -> int:
    response = client.post("/api/apworlds", files={"file": ("sample_game.apworld", make_apworld())})
    apworld_id: int = response.json()["id"]
    worker_finishes(client, {"test-apworld": LOADED})
    client.post(f"/api/apworlds/{apworld_id}/approve")
    return apworld_id


def test_a_backup_holds_the_database_library_game_and_archives(
    client: TestClient, settings: Settings
) -> None:
    approved_apworld(client)
    accept_yaml(client, "Knight")
    made = backup(client)
    assert made["readable"] and made["archives"] and made["files"] >= 3
    response = client.get(f"/api/backups/{made['name']}")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("backup.json"))
    assert {"app.db", "backup.json", "game/yamls/1.yaml"} <= names
    assert any(n.startswith("library/") and n.endswith(".apworld") for n in names)
    assert manifest["db_revision"] and manifest["files"]["game/yamls/1.yaml"]["size"] > 0


def test_restore_brings_everything_back(client: TestClient, settings: Settings) -> None:
    accept_yaml(client, "Knight")
    made = backup(client)
    client.post("/api/game/archive")  # the game moves out; a new empty one opens
    assert client.get("/api/uploads").json() == []

    body = restore(client, made["name"])
    assert body["restored"] == made["name"]
    [upload] = client.get("/api/uploads").json()
    assert (upload["filename"], upload["status"]) == ("knight.yaml", "accepted")
    assert (settings.game_dir / "yamls" / f"{upload['id']}.yaml").is_file()
    assert client.get("/api/game").json()["state"] == "open"
    # A safety backup of what was there was made first.
    names = [b["name"] for b in client.get("/api/backups").json()["backups"]]
    assert any(n.endswith("-before-restore.zip") for n in names)


def test_restore_keeps_the_audit_log_from_now(client: TestClient) -> None:
    made = backup(client)
    client.post("/api/game/lock")  # recorded after the backup
    restore(client, made["name"])
    actions = [e["action"] for e in client.get("/api/audit").json()["entries"]]
    assert actions[:2] == ["restore_backup", "lock"]


def test_what_was_under_way_is_settled(client: TestClient) -> None:
    client.post("/api/uploads/yaml", files={"file": ("k.yaml", b"name: K\ngame: APQuest\n")})
    made = backup(client)  # the upload is still being checked
    worker_finishes(client, {"validate-yaml": {"error": None, "documents": []}})
    restore(client, made["name"])
    [upload] = client.get("/api/uploads").json()
    assert (upload["status"], upload["error_code"]) == ("rejected", "interrupted")
    assert client.post("/api/game/lock").status_code == 200  # nothing left pending


def test_restore_waits_for_the_worker_and_generation(client: TestClient) -> None:
    made = backup(client)
    client.post("/api/uploads/yaml", files={"file": ("k.yaml", b"name: K\ngame: APQuest\n")})
    assert restore(client, made["name"], 409)["detail"]["code"] == "worker-busy"
    worker_finishes(client, {"validate-yaml": {"error": None, "documents": []}})
    accept_yaml(client, "Knight")
    client.post("/api/game/lock")
    client.post("/api/game/generate")
    assert restore(client, made["name"], 409)["detail"]["code"] == "generating"


def test_upload_a_backup_in_pieces_and_restore_it(client: TestClient, settings: Settings) -> None:
    accept_yaml(client, "Knight")
    made = backup(client)
    data = client.get(f"/api/backups/{made['name']}").content
    client.delete(f"/api/backups/{made['name']}")
    upload_id = client.post("/api/backups/incoming").json()["id"]
    half = len(data) // 2
    assert client.put(
        f"/api/backups/incoming/{upload_id}", params={"offset": 0}, content=data[:half]
    ).json() == {"size": half}
    wrong = client.put(f"/api/backups/incoming/{upload_id}", params={"offset": 5}, content=b"x")
    assert (wrong.status_code, wrong.json()["detail"]["code"]) == (409, "wrong-offset")
    client.put(f"/api/backups/incoming/{upload_id}", params={"offset": half}, content=data[half:])
    finished = client.post(
        f"/api/backups/incoming/{upload_id}/finish", json={"filename": "my backup.zip"}
    )
    assert finished.status_code == 200, finished.text
    assert finished.json()["name"] == "my_backup.zip" and finished.json()["readable"]
    client.post("/api/game/archive")
    restore(client, "my_backup.zip")
    assert [u["filename"] for u in client.get("/api/uploads").json()] == ["knight.yaml"]


def test_a_file_that_isnt_a_backup_is_refused(client: TestClient) -> None:
    upload_id = client.post("/api/backups/incoming").json()["id"]
    client.put(f"/api/backups/incoming/{upload_id}", params={"offset": 0}, content=b"not a zip")
    response = client.post(f"/api/backups/incoming/{upload_id}/finish", json={})
    assert (response.status_code, response.json()["detail"]["code"]) == (422, "bad-backup")


def test_a_backup_from_a_newer_version_is_refused(client: TestClient, settings: Settings) -> None:
    made = backup(client)
    path = settings.data_dir / "backups" / made["name"]
    with zipfile.ZipFile(path) as zf:
        entries = {n: zf.read(n) for n in zf.namelist()}
    manifest = json.loads(entries["backup.json"])
    manifest["db_revision"] = "9999"
    entries["backup.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    assert restore(client, made["name"], 409)["detail"]["code"] == "newer-backup"


def test_a_damaged_file_in_the_backup_stops_the_restore(
    client: TestClient, settings: Settings
) -> None:
    accept_yaml(client, "Knight")
    made = backup(client)
    path = settings.data_dir / "backups" / made["name"]
    with zipfile.ZipFile(path) as zf:
        entries = {n: zf.read(n) for n in zf.namelist()}
    entries["game/yamls/1.yaml"] = b"tampered"
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    assert restore(client, made["name"], 422)["detail"]["code"] == "bad-backup"
    assert client.get("/api/uploads").json()[0]["status"] == "accepted"  # nothing changed


def test_symlinks_in_the_game_folder_are_left_out(client: TestClient, settings: Settings) -> None:
    accept_yaml(client, "Knight")
    (settings.game_dir / "logs").mkdir(parents=True, exist_ok=True)
    (settings.game_dir / "logs" / "evil.log").symlink_to(settings.data_dir / "app.db")
    made = backup(client)
    with zipfile.ZipFile(settings.data_dir / "backups" / made["name"]) as zf:
        assert "game/logs/evil.log" not in zf.namelist()


def test_backup_names_cant_reach_other_files(client: TestClient, settings: Settings) -> None:
    for name in ("..%2Fapp.db", "app.db", ".x.zip"):
        assert client.get(f"/api/backups/{name}").status_code == 404


@pytest.mark.real_auth
def test_restore_keeps_the_admins_password(client: TestClient, settings: Settings) -> None:
    client.post("/api/admin/setup", json={"password": "first password"})
    made = backup(client)
    client.post("/api/admin/password", json={"current": "first password", "new": "second one"})
    restore(client, made["name"])
    assert client.get("/api/game").status_code == 200  # still logged in
    client.post("/api/admin/logout")
    assert client.post("/api/admin/login", json={"password": "second one"}).status_code == 200
