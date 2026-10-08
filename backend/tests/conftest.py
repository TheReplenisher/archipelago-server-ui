from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apsui.config import Settings
from apsui.main import create_app


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    static = tmp_path / "dist"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><div id=root></div>")
    (static / "assets" / "app.js").write_text("console.log('app')")
    return static


@pytest.fixture
def settings(tmp_path: Path, static_dir: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", static_dir=static_dir)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
