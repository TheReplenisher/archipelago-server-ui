"""Using an approved apworld in place of a built-in world (#77, DESIGN.md §4).

Archipelago 0.6.8 loads its built-in worlds first and skips a custom apworld whose game
is already loaded. So before anything imports `worlds`, the built-in folder of every game
that a supplied apworld replaces is hidden from AP's scan of its worlds folder. AP then
loads the apworld as it loads any custom world, and builds its data package from it.

Which folder holds which built-in game is only known by importing them all, so the image
records it when it is built:

    python -m apsui_worker.builtin_worlds <archipelago dir> <output json>

A hidden built-in can still be imported directly by code that names it (three worlds import
`worlds.alttp`), and AP then loads it and skips the apworld. not_replaced() finds that.

Used by the worker's jobs and, through apsui_server.multiserver, by the server service.
"""

from __future__ import annotations

import json
import os
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path
from types import TracebackType
from typing import Any

MAP_FILE = Path(os.environ.get("APSUI_BUILTIN_WORLDS", "/opt/apsui/builtin-worlds.json"))
"""{game: {"folder", "version"}} for every built-in world, written when the image is built."""

MAX_MANIFEST_BYTES = 64 * 1024


def builtins(map_file: Path = MAP_FILE) -> dict[str, dict[str, str]]:
    """The built-in worlds by game, or nothing if the map is missing."""
    try:
        data = json.loads(map_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


def manifest_game(apworld: Path) -> str | None:
    """The game named in an apworld's archipelago.json (<module>/archipelago.json), without
    running any of its code."""
    try:
        with zipfile.ZipFile(apworld) as zf:
            info = zf.getinfo(f"{apworld.stem}/archipelago.json")
            if info.file_size > MAX_MANIFEST_BYTES:
                return None
            manifest = json.loads(zf.read(info).decode("utf-8-sig"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None
    game = manifest.get("game") if isinstance(manifest, dict) else None
    return game if isinstance(game, str) else None


def replaced(custom_dir: Path, known: dict[str, dict[str, str]]) -> dict[str, str]:
    """{game: built-in folder} for each apworld in custom_dir whose game is built in."""
    found = {}
    for apworld in sorted(custom_dir.glob("*.apworld")):
        game = manifest_game(apworld)
        if game is not None and game in known:
            found[game] = known[game]["folder"]
    return found


def load_worlds(
    custom_dir: Path, archipelago_dir: Path, map_file: Path = MAP_FILE
) -> dict[str, str]:
    """Import AP's worlds with the built-in world of every game an apworld in custom_dir
    replaces hidden, and return those {game: folder}. Does nothing if none is replaced, so
    AP imports its worlds as usual. Call it before anything imports `worlds`."""
    hidden = replaced(custom_dir, builtins(map_file))
    if not hidden:
        return {}
    if "worlds" in sys.modules:
        raise RuntimeError("Archipelago's worlds were imported before the built-ins were hidden")
    local = (archipelago_dir / "worlds").resolve()
    folders = set(hidden.values())
    real_scandir = os.scandir

    def scandir(path: Any = ".") -> Any:
        entries = real_scandir(path)
        if isinstance(path, (str, os.PathLike)) and Path(path).resolve() == local:
            return _Without(entries, folders)
        return entries

    os.scandir = scandir
    try:
        import worlds  # noqa: F401
    finally:
        os.scandir = real_scandir
    return hidden


def not_replaced(hidden: dict[str, str], custom_dir: Path) -> list[str]:
    """The games in `hidden` whose world didn't come from an apworld in custom_dir: the
    built-in was loaded anyway, or the apworld failed to load."""
    from worlds.AutoWorld import AutoWorldRegister

    custom = str(custom_dir.resolve())
    return sorted(
        game
        for game in hidden
        if custom not in str(getattr(AutoWorldRegister.world_types.get(game), "__file__", ""))
    )


class _Without:
    """A scandir iterator without some entries (folders, or zipped .apworld files)."""

    def __init__(self, entries: Any, names: set[str]) -> None:
        self._entries, self._names = entries, names

    def __iter__(self) -> Iterator[os.DirEntry[str]]:
        return (e for e in self._entries if Path(e.name).stem not in self._names)

    def __enter__(self) -> _Without:
        return self

    def __exit__(
        self, exc: type[BaseException] | None, value: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    def close(self) -> None:
        self._entries.close()


def build(archipelago_dir: Path) -> dict[str, dict[str, str]]:
    sys.path.insert(0, str(archipelago_dir))
    import worlds

    if worlds.failed_world_loads:
        raise SystemExit(f"worlds failed to load: {sorted(worlds.failed_world_loads)}")
    result = {}
    for game, cls in sorted(worlds.AutoWorldRegister.world_types.items()):
        folder = cls.__module__.split(".")[1]
        result[game] = {"folder": folder, "version": cls.world_version.as_simple_string()}
    folders = [entry["folder"] for entry in result.values()]
    if len(set(folders)) != len(folders):  # hiding a folder would hide another game too
        shared = sorted({f for f in folders if folders.count(f) > 1})
        raise SystemExit(f"built-in folders with more than one game: {shared}")
    return result


def main() -> None:
    archipelago_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    result = build(archipelago_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(result)} built-in worlds recorded in {out}")


if __name__ == "__main__":
    main()
