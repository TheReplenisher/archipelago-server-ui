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

An apworld for a built-in game is loaded the way validation, generation and the server
load it (apsui_worker.builtin_worlds, #77): the built-in world is hidden first. Generation's
own modules are imported too, since a hidden built-in that one of them imports would be
loaded after all.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apsui_worker.jobs import JobContext


def run(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    from apsui_worker.archipelago import custom_worlds_dir
    from apsui_worker.builtin_worlds import builtins, load_worlds, manifest_game
    from apsui_worker.jobs import JobFailure

    module = params["module"]
    source = ctx.input_dir / f"{module}.apworld"
    if not source.is_file():
        raise JobFailure("input-missing", f"{module}.apworld was not supplied")
    custom = custom_worlds_dir()
    target = custom / source.name
    shutil.copy2(source, target)

    # AP 0.6.8 loads a world with an incomplete manifest anyway
    game = manifest_game(target) or params.get("game")
    known = builtins().get(game or "")
    hidden = load_worlds(custom, ctx.archipelago_dir)

    import Generate  # noqa: F401
    import Main  # noqa: F401
    import Utils
    import worlds
    from worlds.AutoWorld import AutoWorldRegister

    def from_this_file() -> list[str]:
        return sorted(
            name
            for name, cls in AutoWorldRegister.world_types.items()
            if str(target) in str(getattr(cls, "__file__", "") or "")
        )

    games = from_this_file()
    replaces_builtin = known["version"] if known else None
    builtin = AutoWorldRegister.world_types.get(game) if game and game not in games else None
    if replaces_builtin is None and builtin is not None:
        # A built-in world missing from the image's map must still be flagged, so the
        # apworld can never be approved without the admin.
        replaces_builtin = builtin.world_version.as_simple_string()
    reason = worlds.failed_world_loads.get(module) or worlds.failed_world_loads.get(game or "")
    error = None
    if reason:
        error = reason.strip().splitlines()[-1]
    elif builtin is not None:
        error = (
            f"Archipelago loads its built-in {game} anyway"
            if game in hidden
            else f"The built-in {game} can't be replaced in this install"
        )
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
