"""Slot login and the slot view (#30). A stand-in MultiServer speaks the Archipelago
protocol on a Unix socket, where the supervisor's relay would be; the game is hosted
through a real supervisor, as in test_hosting. Real MultiServer runs in
docker/compose-test.sh."""

import asyncio
import contextlib
import io
import json
import threading
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from apsui_server.supervisor import Supervisor
from apsui_server.testing import running_supervisor
from fastapi.testclient import TestClient
from game_flow import accept_yaml, finish_with_zip
from test_hosting import FAKE_MULTISERVER
from websockets.asyncio.server import ServerConnection, unix_serve

from apsui.config import Settings
from apsui.main import create_app

PASSWORD = "room pw"  # noqa: S105 - a test room
GAMES = {
    "APQuest": {
        "item_name_to_id": {"Sword": 100, "Shield": 101, "Key": 102},
        "location_name_to_id": {"Chest A": 10, "Chest B": 11, "Chest C": 12},
    },
    "Other": {"item_name_to_id": {"Rock": 200}, "location_name_to_id": {"Cave": 20}},
}
SLOT_ITEMS = {
    "slots": {
        "1": [
            {"name": "Key", "count": 1, "flags": 1},
            {"name": "Shield", "count": 1, "flags": 2},
            {"name": "Sword", "count": 2, "flags": 1},
        ],
        "2": [{"name": "Rock", "count": 1, "flags": 0}],
    }
}


class FakeAP:
    """Enough of MultiServer for a Tracker connection: slot 1 is Knight (APQuest), slot 2
    Hornet (Other)."""

    def __init__(self) -> None:
        self.logins = 0
        self.client_status = 0

    async def handle(self, ws: ServerConnection) -> None:
        await ws.send(json.dumps([{"cmd": "RoomInfo", "password": True}]))
        async for raw in ws:
            for message in json.loads(raw):
                await self.reply(ws, message)

    async def reply(self, ws: ServerConnection, message: dict[str, Any]) -> None:
        command = message["cmd"]
        if command == "Connect":
            errors = []
            if message["password"] != PASSWORD:
                errors.append("InvalidPassword")
            if message["name"] not in ("Knight", "Hornet"):
                errors.append("InvalidSlot")
            assert message["tags"] == ["Tracker"] and message["game"] == ""
            if errors:
                await ws.send(json.dumps([{"cmd": "ConnectionRefused", "errors": errors}]))
                return
            self.logins += 1
            slot = 1 if message["name"] == "Knight" else 2
            players = [
                {"team": 0, "slot": 1, "alias": "Knight", "name": "Knight"},
                {"team": 0, "slot": 2, "alias": "Hornet", "name": "Hornet"},
            ]
            info = {
                "1": {"name": "Knight", "game": "APQuest", "type": 1},
                "2": {"name": "Hornet", "game": "Other", "type": 1},
            }
            connected = {
                "cmd": "Connected", "team": 0, "slot": slot, "players": players,
                "missing_locations": [11, 12], "checked_locations": [10],
                "slot_info": info, "hint_points": 5,
            }  # fmt: skip
            items = [
                {"item": 100, "location": 20, "player": 2, "flags": 1},
                {"item": 101, "location": -2, "player": 1, "flags": 2},
            ]
            await ws.send(
                json.dumps([connected, {"cmd": "ReceivedItems", "index": 0, "items": items}])
            )
        elif command == "GetDataPackage":
            games = {g: GAMES[g] for g in message["games"]}
            await ws.send(json.dumps([{"cmd": "DataPackage", "data": {"games": games}}]))
        elif command == "Get":
            hint = {
                "receiving_player": 1, "finding_player": 2, "location": 20, "item": 102,
                "found": False, "entrance": "", "item_flags": 1, "status": 30, "class": "Hint",
            }  # fmt: skip
            keys = {"_read_hints_0_1": [hint], "_read_client_status_0_1": self.client_status}
            await ws.send(json.dumps([{"cmd": "Retrieved", "keys": keys}]))
            # What MultiServer tells this client: one item send for everyone, a hint and
            # a tutorial for this slot only.
            send = {
                "cmd": "PrintJSON", "type": "ItemSend", "receiving": 1,
                "item": {"item": 100, "location": 20, "player": 2, "flags": 1},
                "data": [
                    {"type": "player_id", "text": "2"}, {"text": " sent "},
                    {"type": "item_id", "text": "100", "player": 1, "flags": 1},
                    {"text": " to "}, {"type": "player_id", "text": "1"},
                    {"text": " ("}, {"type": "location_id", "text": "20", "player": 2},
                    {"text": ")"},
                ],
            }  # fmt: skip
            hint = {"cmd": "PrintJSON", "type": "Hint", "data": [{"text": "[Hint]: secret"}]}
            tutorial = {"cmd": "PrintJSON", "type": "Tutorial", "data": [{"text": "!help"}]}
            await ws.send(json.dumps([send, hint, tutorial]))


@contextlib.contextmanager
def fake_ap(path: Path) -> Iterator[FakeAP]:
    fake = FakeAP()
    started = threading.Event()
    stop: list[tuple[asyncio.AbstractEventLoop, asyncio.Future[None]]] = []

    async def main() -> None:
        async with unix_serve(fake.handle, str(path)):
            done: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            stop.append((asyncio.get_running_loop(), done))
            started.set()
            await done

    thread = threading.Thread(target=asyncio.run, args=(main(),), daemon=True)
    thread.start()
    assert started.wait(5)
    try:
        yield fake
    finally:
        loop, done = stop[0]
        loop.call_soon_threadsafe(done.set_result, None)
        thread.join(5)


@pytest.fixture
def ap(settings: Settings, tmp_path: Path) -> Iterator[FakeAP]:
    settings.relay_socket = tmp_path / "fake-ap.sock"
    with fake_ap(settings.relay_socket) as fake:
        yield fake


@pytest.fixture
def client(settings: Settings, tmp_path: Path, ap: FakeAP) -> Iterator[TestClient]:
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


def host(
    client: TestClient,
    slot_items: dict[str, Any] | None = SLOT_ITEMS,
    output: bytes | None = None,
) -> None:
    """Generate a game for Knight and Hornet and start it."""
    accept_yaml(client, "Knight")
    accept_yaml(client, "Hornet")
    client.post("/api/game/lock")
    client.post("/api/game/generate")
    extra = {"slot_items.json": json.dumps(slot_items).encode()} if slot_items else None
    finish_with_zip(client, ["Knight", "Hornet"], data=output, extra=extra)
    assert client.post("/api/game/start").status_code == 200
    for _ in range(250):
        if client.get("/api/server").json()["state"] == "running":
            return
        time.sleep(0.02)
    raise AssertionError("the server never came up")


def login(client: TestClient, name: str = "Knight", password: str = PASSWORD) -> Any:
    return client.post("/api/slot/login", json={"name": name, "password": password})


def set_remaining(client: TestClient, mode: str) -> None:
    values = client.get("/api/settings").json()["values"]
    assert client.put("/api/settings", json=values | {"remaining_mode": mode}).status_code == 200


def test_no_login_while_the_server_is_stopped(client: TestClient) -> None:
    response = login(client)
    assert (response.status_code, response.json()["detail"]["code"]) == (503, "server-stopped")
    response = client.get("/api/slot")
    assert (response.status_code, response.json()["detail"]["code"]) == (401, "not-logged-in")


@pytest.mark.parametrize(("name", "password"), [("Knight", "wrong"), ("Nobody", PASSWORD)])
def test_the_server_refuses_a_wrong_name_or_password(
    client: TestClient, name: str, password: str
) -> None:
    host(client)
    response = login(client, name, password)
    assert (response.status_code, response.json()["detail"]["code"]) == (401, "login-refused")
    assert "apsui_slot" not in response.cookies


def test_the_slot_view(client: TestClient) -> None:
    host(client)
    response = login(client)
    assert response.status_code == 200, response.text
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/api/slot" in cookie

    view = client.get("/api/slot").json()
    assert view["slot"] == {"name": "Knight", "game": "APQuest", "team": 0, "slot": 1}
    assert view["received"] == [
        {"item": "Sword", "player": "Hornet", "location": "Cave", "flags": 1},
        {"item": "Shield", "player": "Knight", "location": "Starting inventory", "flags": 2},
    ]
    assert view["unchecked"] == ["Chest B", "Chest C"]
    assert (view["checked"], view["locations"], view["hint_points"]) == (1, 3, 5)
    assert view["hints"] == [
        {
            "item": "Key", "receiving": "Knight", "finding": "Hornet", "location": "Cave",
            "entrance": "", "found": False, "status": "priority", "flags": 1,
        }
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("mode", "goal", "shown"),
    [("enabled", 0, True), ("goal", 0, False), ("goal", 30, True), ("disabled", 30, False)],
)
def test_unreceived_items_follow_remaining(
    client: TestClient, ap: FakeAP, mode: str, goal: int, shown: bool
) -> None:
    ap.client_status = goal
    host(client)
    set_remaining(client, mode)
    login(client)
    view = client.get("/api/slot").json()
    assert (view["unreceived_rule"], view["goal"]) == (mode, goal == 30)
    expected = [{"item": "Key", "count": 1, "flags": 1}, {"item": "Sword", "count": 1, "flags": 1}]
    assert view["unreceived"] == (expected if shown else None)


def test_without_the_items_file_unreceived_is_unavailable(client: TestClient) -> None:
    host(client, slot_items=None)
    set_remaining(client, "enabled")
    login(client)
    view = client.get("/api/slot").json()
    assert (view["unreceived"], view["unreceived_rule"]) == (None, "unavailable")


def test_stopping_the_server_shows_it_stopped(client: TestClient) -> None:
    host(client)
    login(client)
    assert client.get("/api/slot").status_code == 200
    client.post("/api/game/stop")
    response = client.get("/api/slot")
    assert (response.status_code, response.json()["detail"]["code"]) == (503, "server-stopped")


def test_one_connection_per_slot(client: TestClient, ap: FakeAP) -> None:
    host(client)
    login(client)
    login(client)
    client.get("/api/slot")
    assert ap.logins == 1


def test_logout(client: TestClient) -> None:
    host(client)
    login(client)
    assert client.post("/api/slot/logout").status_code == 200
    assert client.get("/api/slot").status_code == 401


def test_logins_are_rate_limited(client: TestClient) -> None:
    host(client)
    codes = [login(client, "Knight", "wrong").status_code for _ in range(11)]
    assert codes == [401] * 10 + [429]


def test_a_player_downloads_only_their_own_patch(client: TestClient) -> None:
    """#36: from the slot view, while logged in to that slot."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(zipfile.ZipInfo("AP_12345.archipelago", (2026, 1, 1, 0, 0, 0)), b"multidata")
        zf.writestr("AP_12345_P1_Knight.apz5", b"knight patch")
        zf.writestr("AP_12345_P2_Hornet.aplttp", b"hornet patch")
    host(client, output=buffer.getvalue())
    assert client.get("/api/slot/patches").status_code == 401
    login(client)
    [patch] = client.get("/api/slot/patches").json()
    assert (patch["file"], patch["slot"]) == ("AP_12345_P1_Knight.apz5", "Knight")
    response = client.get("/api/slot/patches/AP_12345_P1_Knight.apz5")
    assert (response.status_code, response.content) == (200, b"knight patch")
    other = client.get("/api/slot/patches/AP_12345_P2_Hornet.aplttp")
    assert (other.status_code, other.json()["detail"]["code"]) == (404, "not-found")


def test_the_player_feed_shows_what_everyone_sees_and_no_hints(client: TestClient) -> None:
    """#35: from one observer connection, never the admin's feed."""
    host(client)
    values = client.get("/api/settings").json()["values"]
    client.put("/api/settings", json=values | {"password": PASSWORD})
    assert client.get("/api/slot/feed").status_code == 401
    login(client, "Hornet")
    body: dict[str, Any] = {"entries": []}
    for _ in range(100):
        body = client.get("/api/slot/feed").json()
        if body["entries"]:
            break
        time.sleep(0.02)
    [entry] = body["entries"]
    assert entry["type"] == "ItemSend"
    assert [(p["kind"], p["text"]) for p in entry["parts"]] == [
        ("player", "Hornet"),
        ("text", " sent "),
        ("item", "Sword"),
        ("text", " to "),
        ("player", "Knight"),
        ("text", " ("),
        ("location", "Cave"),
        ("text", ")"),
    ]
    assert entry["parts"][2]["flags"] == 1
    assert client.get("/api/slot/feed", params={"after": body["last"]}).json()["entries"] == []
