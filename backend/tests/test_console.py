"""The admin console's command catalog and names (#26)."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from game_flow import accept_yaml, finish_with_zip

from apsui.config import Settings
from apsui.main import create_app

CATALOG = {
    "commands": [
        {
            "name": "send",
            "help": "Sends an item to the specified player",
            "raw": False,
            "args": [
                {"name": "player_name", "kind": "player", "required": True, "rest": False},
                {"name": "item_name", "kind": "item", "required": True, "rest": True},
            ],
        },
        {
            "name": "countdown",
            "help": "Start a countdown in seconds",
            "raw": False,
            "args": [
                {
                    "name": "seconds",
                    "kind": "number",
                    "required": False,
                    "rest": False,
                    "default": "10",
                }
            ],
        },
    ]
}

NAMES: dict[str, Any] = {
    "players": [
        {"slot": 1, "name": "Knight", "game": "APQuest"},
        {"slot": 2, "name": "Hornet", "game": "APQuest"},
    ],
    "games": {"APQuest": {"items": ["Hammer", "Sword"], "locations": ["Top Left Room Chest"]}},
}


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    settings.job_poll_interval = 3600
    with TestClient(create_app(settings)) as c:
        yield c


def generate(client: TestClient, names: bytes | None) -> None:
    accept_yaml(client, "Knight")
    accept_yaml(client, "Hornet")
    client.post("/api/game/lock")
    client.post("/api/game/generate")
    extra = {} if names is None else {"names.json": names}
    finish_with_zip(client, ["Knight", "Hornet"], extra=extra)
    assert client.get("/api/game").json()["state"] == "generated"


def test_the_catalog_is_served(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    settings.command_catalog = tmp_path / "commands.json"
    settings.command_catalog.write_text(json.dumps(CATALOG))
    commands = client.get("/api/console/commands").json()
    assert [c["name"] for c in commands] == ["send", "countdown"]
    assert commands[0]["args"][1] == {
        "name": "item_name",
        "kind": "item",
        "required": True,
        "rest": True,
        "default": None,
        "choices": [],
    }
    assert commands[1]["args"][0]["default"] == "10"


def test_no_catalog_means_free_text_only(client: TestClient, settings: Settings) -> None:
    settings.command_catalog = None
    assert client.get("/api/console/commands").json() == []


def test_the_generations_names_are_kept(client: TestClient) -> None:
    generate(client, json.dumps(NAMES).encode())
    response = client.get("/api/console/names")
    assert response.status_code == 200
    assert response.json() == NAMES


@pytest.mark.parametrize(
    "names",
    [
        b"not json",
        json.dumps(NAMES | {"extra": 1}).encode(),
        json.dumps(
            NAMES | {"players": [{"slot": 1, "name": "x" * 257, "game": "APQuest"}]}
        ).encode(),
        json.dumps(
            NAMES | {"players": [{"slot": 0, "name": "Knight", "game": "APQuest"}]}
        ).encode(),
    ],
    ids=["not-json", "extra-field", "long-name", "bad-slot"],
)
def test_names_that_dont_parse_are_dropped(client: TestClient, names: bytes) -> None:
    """The generation still succeeds; the console just has no lists."""
    generate(client, names)
    response = client.get("/api/console/names")
    assert (response.status_code, response.json()["detail"]["code"]) == (404, "no-names")


def test_no_names_without_them_or_before_generation(client: TestClient) -> None:
    response = client.get("/api/console/names")
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "no-output")
    generate(client, None)
    response = client.get("/api/console/names")
    assert (response.status_code, response.json()["detail"]["code"]) == (404, "no-names")


def test_discarding_the_output_drops_the_names(client: TestClient) -> None:
    generate(client, json.dumps(NAMES).encode())
    client.post("/api/game/discard-output")
    response = client.get("/api/console/names")
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "no-output")
    client.post("/api/game/generate")
    finish_with_zip(client, ["Knight", "Hornet"])
    assert client.get("/api/console/names").status_code == 404
