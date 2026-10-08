from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apsui.config import Settings
from apsui.main import create_app


@pytest.mark.parametrize("path", ["/", "/admin", "/player/some/deep/route"])
def test_client_routes_get_the_app_shell(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert "<div id=root>" in response.text


def test_assets_are_served(client: TestClient) -> None:
    response = client.get("/assets/app.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


@pytest.mark.parametrize("path", ["/api", "/api/does-not-exist"])
def test_unknown_api_paths_are_404_not_the_app_shell(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 404
    assert "<div id=root>" not in response.text


def test_without_a_built_frontend_the_api_still_works(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", static_dir=tmp_path / "missing")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/").status_code == 404
