"""The audit log of admin actions (#37)."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from game_flow import accept_yaml

from apsui import audit
from apsui.config import Settings
from apsui.main import create_app


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    settings.job_poll_interval = 3600  # tests collect by hand
    with TestClient(create_app(settings)) as c:
        yield c


def entries(client: TestClient, **params: Any) -> list[dict[str, Any]]:
    response = client.get("/api/audit", params=params)
    assert response.status_code == 200, response.text
    result: list[dict[str, Any]] = response.json()["entries"]
    return result


def test_each_admin_action_is_recorded_with_who_and_how_it_went(client: TestClient) -> None:
    client.get("/api/game")  # reading isn't an action
    assert client.post("/api/game/lock").status_code == 200
    assert client.post("/api/game/lock").status_code == 409  # refused: already locked
    newest, oldest = entries(client)
    assert (oldest["action"], oldest["label"], oldest["actor"], oldest["ok"]) == (
        "lock",
        "Locked uploads",
        "admin",
        True,
    )
    assert (newest["status"], newest["ok"]) == (409, False)
    assert oldest["client"] == "testclient"
    assert [e["action"] for e in entries(client, failed=True)] == ["lock"]


def test_targets_and_details_but_never_a_password(client: TestClient) -> None:
    upload_id = accept_yaml(client, "Knight")
    client.delete(f"/api/uploads/{upload_id}")
    values = client.get("/api/settings").json()["values"]
    client.put("/api/settings", json=values | {"password": "hunter2!", "hint_cost": 25})

    changed, removed, uploaded = entries(client)
    assert (uploaded["action"], uploaded["detail"]) == ("upload_yaml", {"filename": "knight.yaml"})
    assert (removed["action"], removed["target"]) == ("delete_upload", f"upload {upload_id}")
    assert changed["detail"] == {"changed": {"password": "changed", "hint_cost": [10, 25]}}
    assert "hunter2" not in str(entries(client))


def test_filters_and_pages(client: TestClient) -> None:
    for _ in range(3):
        client.post("/api/game/lock")
        client.post("/api/game/unlock")
    assert len(entries(client, action="unlock")) == 3
    assert len(entries(client, action=["lock", "unlock"])) == 6
    page = client.get("/api/audit", params={"limit": 4}).json()
    assert len(page["entries"]) == 4 and page["next_before"]
    rest = client.get("/api/audit", params={"limit": 4, "before": page["next_before"]}).json()
    assert len(rest["entries"]) == 2 and rest["next_before"] is None
    assert page["actions"]["lock"] == "Locked uploads"
    accept_yaml(client, "Knight")
    assert [e["action"] for e in entries(client, q="knight")] == ["upload_yaml"]


def test_console_passwords_are_redacted() -> None:
    assert audit.redact_command("/option password secret") == "/option password ••••"
    assert audit.redact_command("/OPTION server_password a b") == "/OPTION server_password ••••"
    assert audit.redact_command("/option hint_cost 5") == "/option hint_cost 5"


def test_old_entries_are_pruned(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit, "KEEP_AT_MOST", 5)
    monkeypatch.setattr(audit, "PRUNE_EVERY", 1)
    for _ in range(5):
        client.post("/api/game/lock")
        client.post("/api/game/unlock")
    assert len(entries(client, limit=100)) == 5


@pytest.mark.real_auth
def test_logins_are_recorded_and_refused_ones_too(client: TestClient) -> None:
    client.post("/api/admin/setup", json={"password": "the password"})
    client.post("/api/admin/logout")
    client.post("/api/admin/login", json={"password": "wrong one!"})
    client.post("/api/slot/login", json={"name": "Knight", "password": ""})  # a player's
    client.post("/api/admin/login", json={"password": "the password"})
    login, refused, logout, setup = entries(client)
    assert (setup["action"], setup["actor"], setup["ok"]) == ("setup", "admin", True)
    assert (logout["action"], logout["actor"]) == ("logout", "admin")
    assert (refused["actor"], refused["status"], refused["detail"]) == (
        None,
        401,
        {"refused": "login-refused"},
    )
    assert (login["action"], login["ok"]) == ("login", True)


@pytest.mark.real_auth
def test_the_audit_log_is_the_admins(client: TestClient) -> None:
    assert client.get("/api/audit").status_code == 401
