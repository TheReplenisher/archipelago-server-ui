"""Patch file downloads (#29), from a generated output zip built here."""

import io
import zipfile
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from game_flow import accept_yaml, finish_with_zip

from apsui.config import Settings
from apsui.main import create_app

KNIGHT = b"knight patch " * 1000
HORNET = b"hornet patch"


def output_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("AP_12345.archipelago", b"multidata")
        zf.writestr("AP_12345_Spoiler.txt", b"spoilers")
        zf.writestr("AP_12345_P1_Knight.apz5", KNIGHT)
        zf.writestr("AP_12345_P2_Hornet.aplttp", HORNET)
        zf.writestr("AP-12345-P2-Hornet_1.0.0.zip", b"factorio-style mod")
        zf.writestr("AP_99999_P1_Other.apz5", b"another seed")
        zf.writestr("sub/AP_12345_P1_Knight.apz5", b"in a folder")
    return buffer.getvalue()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    settings.job_poll_interval = 3600
    with TestClient(create_app(settings)) as c:
        yield c


def generate(client: TestClient) -> None:
    accept_yaml(client, "Knight")
    accept_yaml(client, "Hornet")
    client.post("/api/game/lock")
    client.post("/api/game/generate")
    finish_with_zip(client, ["Knight", "Hornet"], data=output_zip())


def test_each_slots_patch_is_listed(client: TestClient) -> None:
    generate(client)
    assert client.get("/api/game/patches").json() == [
        {"file": "AP_12345_P1_Knight.apz5", "player": 1, "slot": "Knight", "size": len(KNIGHT)},
        {"file": "AP-12345-P2-Hornet_1.0.0.zip", "player": 2, "slot": "Hornet", "size": 18},
        {"file": "AP_12345_P2_Hornet.aplttp", "player": 2, "slot": "Hornet", "size": len(HORNET)},
    ]


def test_one_patch_downloads(client: TestClient) -> None:
    generate(client)
    response = client.get("/api/game/patches/AP_12345_P1_Knight.apz5")
    assert response.status_code == 200
    assert response.content == KNIGHT
    assert (
        response.headers["content-disposition"] == 'attachment; filename="AP_12345_P1_Knight.apz5"'
    )


@pytest.mark.parametrize(
    "name", ["AP_12345_Spoiler.txt", "AP_12345.archipelago", "AP_99999_P1_Other.apz5"]
)
def test_only_listed_patches_download(client: TestClient, name: str) -> None:
    generate(client)
    response = client.get(f"/api/game/patches/{name}")
    assert (response.status_code, response.json()["detail"]["code"]) == (404, "not-found")


def test_all_patches_download_as_one_zip(client: TestClient) -> None:
    generate(client)
    response = client.get("/api/game/patches-all.zip")
    assert response.status_code == 200
    assert 'filename="AP_12345_patches.zip"' in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        assert zf.namelist() == [
            "AP_12345_P1_Knight.apz5",
            "AP-12345-P2-Hornet_1.0.0.zip",
            "AP_12345_P2_Hornet.aplttp",
        ]
        assert zf.read("AP_12345_P1_Knight.apz5") == KNIGHT


def test_nothing_before_generation(client: TestClient) -> None:
    response = client.get("/api/game/patches")
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "no-output")
