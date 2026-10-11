"""Hiding a built-in world that an apworld replaces (#77), against a stand-in for AP's
worlds package that scans its folder the way AP 0.6.8's does. Real AP runs in
docker/smoke-test.sh and docker/compose-test.sh."""

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from apsui_worker.builtin_worlds import manifest_game, replaced

FAKE_WORLDS = """
import os
scanned = sorted(
    entry.name for entry in os.scandir(os.path.dirname(__file__))
    if not entry.name.startswith(("_", "."))
)
"""


def apworld(path: Path, manifest: object, module: str | None = None) -> Path:
    module = module or path.stem
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{module}/__init__.py", "")
        zf.writestr(f"{module}/archipelago.json", json.dumps(manifest))
    return path


@pytest.fixture
def ap(tmp_path: Path) -> Path:
    """An Archipelago folder with two built-in worlds, and the image's map of them."""
    root = tmp_path / "archipelago"
    for folder in ("apquest", "other"):
        (root / "worlds" / folder).mkdir(parents=True)
        (root / "worlds" / folder / "__init__.py").write_text("")
    (root / "worlds" / "__init__.py").write_text(FAKE_WORLDS)
    (tmp_path / "map.json").write_text(
        json.dumps(
            {
                "APQuest": {"folder": "apquest", "version": "2.0.0"},
                "Other": {"folder": "other", "version": "1.0.0"},
            }
        )
    )
    (tmp_path / "custom").mkdir()
    return root


def load(ap: Path) -> dict[str, object]:
    """load_worlds() in a fresh process, as a job's child process runs it."""
    script = f"""
import json, os, sys
from pathlib import Path
sys.path.insert(0, {str(ap)!r})
from apsui_worker.builtin_worlds import load_worlds
real = os.scandir
hidden = load_worlds(Path({str(ap.parent / "custom")!r}), Path({str(ap)!r}),
                     Path({str(ap.parent / "map.json")!r}))
worlds = sys.modules.get("worlds")
print(json.dumps({{"hidden": hidden, "scanned": getattr(worlds, "scanned", None),
                   "restored": os.scandir is real}}))
"""
    done = subprocess.run(  # noqa: S603 - this test's own script
        [sys.executable, "-c", script], capture_output=True, text=True, check=True, timeout=30
    )
    result: dict[str, object] = json.loads(done.stdout)
    return result


def test_the_replaced_built_in_is_hidden_from_the_scan(ap: Path) -> None:
    apworld(ap.parent / "custom" / "my_quest.apworld", {"game": "APQuest"})
    result = load(ap)
    assert result["hidden"] == {"APQuest": "apquest"}
    assert result["scanned"] == ["other"]
    assert result["restored"] is True


def test_an_apworld_with_the_built_in_folder_name_is_hidden_too(ap: Path) -> None:
    (ap / "worlds" / "apquest.apworld").write_bytes(b"")  # a zipped built-in
    apworld(ap.parent / "custom" / "apquest.apworld", {"game": "APQuest"})
    assert load(ap)["scanned"] == ["other"]


def test_nothing_is_imported_without_a_replacement(ap: Path) -> None:
    apworld(ap.parent / "custom" / "new_game.apworld", {"game": "New Game"})
    result = load(ap)
    assert result["hidden"] == {}
    assert result["scanned"] is None  # AP imports its worlds later, as usual


def test_the_game_comes_from_the_manifest_without_running_code(tmp_path: Path) -> None:
    good = apworld(tmp_path / "quest.apworld", {"game": "APQuest", "world_version": "9.9.0"})
    assert manifest_game(good) == "APQuest"
    assert manifest_game(apworld(tmp_path / "list.apworld", ["APQuest"])) is None
    assert manifest_game(apworld(tmp_path / "wrong.apworld", {"game": 3})) is None
    assert manifest_game(apworld(tmp_path / "moved.apworld", {"game": "X"}, "elsewhere")) is None
    (tmp_path / "junk.apworld").write_bytes(b"not a zip")
    assert manifest_game(tmp_path / "junk.apworld") is None


def test_only_built_in_games_count_as_replaced(tmp_path: Path) -> None:
    apworld(tmp_path / "a.apworld", {"game": "APQuest"})
    apworld(tmp_path / "b.apworld", {"game": "Brand New"})
    known = {"APQuest": {"folder": "apquest", "version": "2.0.0"}}
    assert replaced(tmp_path, known) == {"APQuest": "apquest"}
    assert replaced(tmp_path, {}) == {}
