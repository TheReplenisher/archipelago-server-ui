"""Player uploads from the Player tab (#33)."""

from collections.abc import Iterator
from typing import Any

import pytest
from apworld_files import make_apworld
from fastapi.testclient import TestClient
from worker_sim import worker_finishes

from apsui import player_uploads
from apsui.config import Settings
from apsui.main import create_app

YAML = b"name: Knight\ngame: APQuest\nAPQuest: {}\n"
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


def doc(name: str | None = "Knight", **extra: Any) -> dict[str, Any]:
    return {
        "index": 0,
        "empty": False,
        "name": name,
        "name_raw": name,
        "games": ["APQuest"],
    } | extra


def checked(*documents: dict[str, Any]) -> dict[str, Any]:
    return {"validate-yaml": {"error": None, "documents": list(documents)}}


def upload_yaml(client: TestClient, data: bytes = YAML, status: int = 202) -> dict[str, Any]:
    response = client.post("/api/player/yaml", files={"file": ("knight.yaml", data)})
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    return body


def mine(client: TestClient, *uploaded: dict[str, Any]) -> list[dict[str, Any]]:
    receipts = [
        {"kind": u["upload"]["kind"], "id": u["upload"]["id"], "receipt": u["receipt"]}
        for u in uploaded
    ]
    response = client.post("/api/player/receipts", json={"receipts": receipts})
    assert response.status_code == 200, response.text
    found: list[dict[str, Any]] = response.json()
    return found


def put_settings(client: TestClient, **changes: Any) -> None:
    values = client.get("/api/settings").json()["values"]
    assert client.put("/api/settings", json=values | changes).status_code == 200


def test_a_player_uploads_a_yaml_and_follows_it_with_the_receipt(client: TestClient) -> None:
    game = client.get("/api/player/game").json()
    assert (game["state"], game["uploads_open"], game["taken_names"]) == ("open", True, [])
    uploaded = upload_yaml(client)
    assert uploaded["upload"]["status"] == "pending" and len(uploaded["receipt"]) > 20
    worker_finishes(client, checked(doc()))
    [view] = mine(client, uploaded)
    assert (view["status"], view["slots"], view["current_game"]) == ("accepted", ["Knight"], True)
    assert client.get("/api/player/game").json()["taken_names"] == ["Knight"]
    # The admin sees who sent it and from where.
    [admin_view] = client.get("/api/uploads").json()
    assert (admin_view["uploaded_by"], admin_view["uploaded_from"]) == ("player", "testclient")


def test_a_receipt_only_opens_its_own_upload(client: TestClient) -> None:
    first, second = upload_yaml(client), upload_yaml(client)
    forged = {"upload": first["upload"], "receipt": second["receipt"]}
    assert mine(client, forged) == []
    withdraw = client.post(
        f"/api/player/yaml/{first['upload']['id']}/withdraw", json={"receipt": second["receipt"]}
    )
    assert (withdraw.status_code, withdraw.json()["detail"]["code"]) == (404, "not-found")


def test_the_player_never_sees_the_workers_detail(client: TestClient) -> None:
    uploaded = upload_yaml(client)
    error = {"code": "option-invalid", "message": "Invalid value", "detail": "Traceback secret"}
    worker_finishes(client, checked(doc(error=error)))
    [view] = mine(client, uploaded)
    assert (view["status"], view["error_code"], view["error_message"]) == (
        "rejected",
        "option-invalid",
        "Invalid value",
    )
    assert "Traceback" not in str(view)


def test_a_player_renames_their_own_slot_and_withdraws(client: TestClient) -> None:
    uploaded = upload_yaml(client)
    name_error = {"code": "name-not-fixed", "message": "Slot name must be one fixed name"}
    worker_finishes(client, checked(doc(name=None, name_raw=["A", "B"], name_error=name_error)))
    [view] = mine(client, uploaded)
    assert view["status"] == "needs-name"
    assert view["name_problems"][0]["suggestion"] == "A"

    upload_id, receipt = uploaded["upload"]["id"], uploaded["receipt"]
    renamed = client.post(
        f"/api/player/yaml/{upload_id}/rename",
        json={"receipt": receipt, "names": [{"document": 0, "name": "Alice"}]},
    )
    assert renamed.status_code == 202, renamed.text
    worker_finishes(client, checked(doc(name="Alice")))
    assert mine(client, uploaded)[0]["slots"] == ["Alice"]

    withdrawn = client.post(f"/api/player/yaml/{upload_id}/withdraw", json={"receipt": receipt})
    assert withdrawn.json()["status"] == "removed"
    assert client.get("/api/player/game").json()["taken_names"] == []


def test_uploads_close_with_the_game_or_the_setting(client: TestClient) -> None:
    put_settings(client, player_uploads=False)
    assert client.get("/api/player/game").json()["uploads_open"] is False
    body = upload_yaml(client, status=403)
    assert body["detail"]["code"] == "player-uploads-off"
    put_settings(client, player_uploads=True)
    client.post("/api/game/lock")
    assert upload_yaml(client, status=409)["detail"]["code"] == "uploads-closed"


def test_yaml_uploads_are_rate_limited(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(player_uploads.LIMITS, "yaml", player_uploads.Window(2, 600))
    upload_yaml(client)
    upload_yaml(client)
    assert upload_yaml(client, status=429)["detail"]["code"] == "too-many-uploads"


def test_a_players_apworld_waits_for_the_admin_even_in_auto_mode(client: TestClient) -> None:
    put_settings(client, apworld_approval="auto")  # the admin's own uploads
    response = client.post(
        "/api/player/apworld", files={"file": ("sample_game.apworld", make_apworld())}
    )
    assert response.status_code == 202, response.text
    uploaded = response.json()
    worker_finishes(client, {"test-apworld": LOADED})
    [view] = mine(client, uploaded)
    assert view["status"] == "pending"
    [admin_view] = client.get("/api/apworlds").json()
    assert (admin_view["uploaded_by"], admin_view["status"]) == ("player", "pending")


def test_players_apworlds_can_be_approved_automatically(client: TestClient) -> None:
    put_settings(client, player_apworld_approval="auto")
    response = client.post(
        "/api/player/apworld", files={"file": ("sample_game.apworld", make_apworld())}
    )
    uploaded = response.json()
    worker_finishes(client, {"test-apworld": LOADED})
    assert mine(client, uploaded)[0]["status"] == "approved"
    library = client.get("/api/player/library").json()
    assert [a["game"] for a in library["apworlds"]] == ["Sample Game"]


def test_waiting_player_apworlds_are_capped(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(player_uploads, "MAX_PENDING_APWORLDS", 1)
    files = {"file": ("sample_game.apworld", make_apworld())}
    assert client.post("/api/player/apworld", files=files).status_code == 202
    other = {"file": ("sample_game.apworld", make_apworld(manifest={"game": "Other Game"}))}
    response = client.post("/api/player/apworld", files=other)
    assert (response.status_code, response.json()["detail"]["code"]) == (429, "too-many-waiting")


@pytest.mark.real_auth
def test_player_routes_need_no_admin_login(client: TestClient) -> None:
    assert client.get("/api/player/game").status_code == 200
    assert client.get("/api/player/library").status_code == 200
    assert upload_yaml(client)["receipt"]
