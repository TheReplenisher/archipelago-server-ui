"""Load one uploaded apworld in isolation and report what happened (DESIGN.md §4,
Apworlds step 4).

Params: {"module": "<name>", "game": "<game from archipelago.json>"}; input/<name>.apworld
is the file.
Output: {
  "archipelago_version",
  "loaded": bool,                 the world registered its game
  "games": [str],                 the games classes from this file registered
  "replaces_builtin": str | null, the built-in world's version, if the game is built in
  "error": str | null,            one line; the whole traceback is in "detail" and log.txt
  "detail": str | null,
}

Archipelago skips a custom apworld whose game is already loaded, and built-in worlds
always load first. So when the game is built in, the built-in is unregistered here (this
child process exits afterwards) and the apworld is loaded the way AP would load it.
"""

from __future__ import annotations

import shutil
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apsui_worker.jobs import JobContext


def run(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    from apsui_worker.archipelago import custom_worlds_dir
    from apsui_worker.jobs import JobFailure

    module = params["module"]
    source = ctx.input_dir / f"{module}.apworld"
    if not source.is_file():
        raise JobFailure("input-missing", f"{module}.apworld was not supplied")
    target = custom_worlds_dir() / source.name
    shutil.copy2(source, target)

    import Utils
    import worlds
    from worlds.AutoWorld import AutoWorldRegister
    from worlds.Files import APWorldContainer

    container = APWorldContainer(str(target))
    try:
        container.read()
    except Exception:  # AP 0.6.8 loads a world with an incomplete manifest anyway
        container.game = params.get("game")
    game = container.game

    def from_this_file() -> list[str]:
        return sorted(
            name
            for name, cls in AutoWorldRegister.world_types.items()
            if str(target) in str(getattr(cls, "__file__", "") or "")
        )

    replaces_builtin = None
    builtin = AutoWorldRegister.world_types.get(game) if game else None
    if builtin is not None and str(target) not in str(builtin.__file__):
        replaces_builtin = builtin.world_version.as_simple_string()
        # Hide the built-in world, then load this one the way worlds/__init__.py does.
        del AutoWorldRegister.world_types[game]
        prefix = f"worlds.{module}"
        for name in [m for m in sys.modules if m == prefix or m.startswith(prefix + ".")]:
            del sys.modules[name]
        world_source = worlds.WorldSource(str(target), is_zip=True, relative=False)
        worlds.add_apworld_spec(world_source, container)
        world_source.load()

    games = from_this_file()
    reason = worlds.failed_world_loads.get(module) or worlds.failed_world_loads.get(game or "")
    error = None
    if reason:
        error = reason.strip().splitlines()[-1]
    elif not games:
        error = "The apworld loaded but registered no game"
    elif game not in games:
        error = f"archipelago.json says {game!r} but the world registers {', '.join(games)}"

    return {
        "archipelago_version": Utils.__version__,
        "loaded": error is None,
        "games": games,
        "replaces_builtin": replaces_builtin,
        "error": error,
        "detail": reason,
    }
