"""Generate the multiworld (DESIGN.md §3, #18): Archipelago's own Generate and Main, run
on the game's accepted YAMLs with its locked custom apworlds.

Input: <upload id>.yaml for every accepted YAML, and <module>.apworld for every game
locked to a library apworld.
Params: plando_options (str, default AP's), spoiler (int 0-3, default 3), race (bool),
        seed (int or null).
Output: {"archipelago_version", "seed", "seed_name", "zip", "players": [slot names]},
        output/<zip>, the file MultiServer hosts, and output/names.json: each slot's
        number, name and game, and each game's item and location names (its data
        package), for the admin console's searchable lists (#26).
"""

from __future__ import annotations

import json
import logging
import shutil
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apsui_worker.jobs import JobContext


def run(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    from apsui_worker.archipelago import custom_worlds_dir
    from apsui_worker.jobs import JobFailure

    custom = custom_worlds_dir()
    for apworld in sorted(ctx.input_dir.glob("*.apworld")):
        shutil.copy2(apworld, custom / apworld.name)
    # The job folder is writable; AP reads player files from a folder of its own.
    players = ctx.input_dir.parent / "players"
    players.mkdir()
    for yaml_file in sorted(ctx.input_dir.glob("*.yaml")):
        shutil.copy2(yaml_file, players / yaml_file.name)
    if not any(players.iterdir()):
        raise JobFailure("no-players", "There are no YAMLs to generate with")
    work = ctx.input_dir.parent / "generated"

    # AP logs its progress and the detail of player-file errors; the worker keeps the
    # job's stderr as log.txt.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", force=True)

    import Generate
    import Main
    import Utils

    argv = [
        "--player_files_path", str(players),
        "--outputpath", str(work),
        "--spoiler", str(int(params.get("spoiler", 3))),
        "--plando", str(params.get("plando_options", "bosses, connections, texts")),
    ]  # fmt: skip
    if params.get("race"):
        argv.append("--race")
    if params.get("seed") is not None:
        argv += ["--seed", str(int(params["seed"]))]
    erargs, seed = Generate.main(Generate.mystery_argparse(argv))
    multiworld = Main.main(erargs, seed)

    zips = sorted(work.glob("AP_*.zip"))
    if len(zips) != 1:
        raise JobFailure("no-output", "Generation finished without an output file")
    shutil.move(zips[0], ctx.output_dir / zips[0].name)
    names = json.dumps(console_names(multiworld), ensure_ascii=False)
    (ctx.output_dir / "names.json").write_text(names, encoding="utf-8")
    return {
        "archipelago_version": Utils.__version__,
        "seed": seed,
        "seed_name": multiworld.seed_name,
        "zip": zips[0].name,
        "players": [multiworld.player_name[p] for p in multiworld.player_ids],
    }


def console_names(multiworld: Any) -> dict[str, Any]:
    """The slots, and each game's item and location names."""
    players = []
    games: dict[str, dict[str, list[str]]] = {}
    for slot in multiworld.player_ids:
        world = multiworld.worlds[slot]
        players.append({"slot": slot, "name": multiworld.player_name[slot], "game": world.game})
        if world.game not in games:
            games[world.game] = {
                "items": sorted(world.item_name_to_id),
                "locations": sorted(world.location_name_to_id),
            }
    return {"players": players, "games": games}
