"""The spoiler log (#28), from a generated output zip built here."""

import io
import zipfile
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from game_flow import accept_yaml, finish_with_zip

from apsui.config import Settings
from apsui.main import create_app

# AP writes the spoiler as UTF-8 with a byte-order mark.
SPOILER = "﻿Archipelago Version 0.6.8  -  Seed: 12345\n\nKnight's Hookshot: Hornet's Shop\n"


def output_zip(*extra: tuple[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("AP_12345.archipelago", b"multidata")
        zf.writestr("AP_12345_P1_Knight.apz5", b"knight patch")
        for name, text in extra:
            zf.writestr(name, text.encode("utf-8"))
    return buffer.getvalue()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    settings.job_poll_interval = 3600
    with TestClient(create_app(settings)) as c:
        yield c


def generate(client: TestClient, data: bytes) -> None:
    accept_yaml(client, "Knight")
    client.post("/api/game/lock")
    client.post("/api/game/generate")
    finish_with_zip(client, ["Knight"], data=data)


def test_the_spoiler_is_found(client: TestClient) -> None:
    generate(client, output_zip(("AP_12345_Spoiler.txt", SPOILER)))
    assert client.get("/api/game/spoiler").json() == {
        "file": "AP_12345_Spoiler.txt",
        "size": len(SPOILER.encode("utf-8")),
    }


def test_the_spoiler_downloads_and_is_never_cached(client: TestClient) -> None:
    generate(client, output_zip(("AP_12345_Spoiler.txt", SPOILER)))
    response = client.get("/api/game/spoiler.txt")
    assert response.status_code == 200
    assert response.content == SPOILER.encode("utf-8")
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="AP_12345_Spoiler.txt"'
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "extra",
    [
        (),
        (("AP_99999_Spoiler.txt", "another seed's spoiler"),),
        (("sub/AP_12345_Spoiler.txt", "in a folder"),),
    ],
    ids=["none", "other-seed", "in-a-folder"],
)
def test_no_spoiler_without_this_seeds_file(
    client: TestClient, extra: tuple[tuple[str, str], ...]
) -> None:
    generate(client, output_zip(*extra))
    for path in ("/api/game/spoiler", "/api/game/spoiler.txt"):
        response = client.get(path)
        assert (response.status_code, response.json()["detail"]["code"]) == (404, "no-spoiler")


def test_nothing_before_generation(client: TestClient) -> None:
    for path in ("/api/game/spoiler", "/api/game/spoiler.txt"):
        response = client.get(path)
        assert (response.status_code, response.json()["detail"]["code"]) == (409, "no-output")
