"""Generate the multiworld (DESIGN.md §3, #18): Archipelago's own Generate and Main, run
on the game's accepted YAMLs with its locked custom apworlds.

Input: <upload id>.yaml for every accepted YAML, and <module>.apworld for every game
locked to a library apworld; one for a built-in game is used in place of the built-in
world (apsui_worker.builtin_worlds, #77).
Params: plando_options (str, default AP's), spoiler (int 0-3, default 3), race (bool),
        panic_method (swap, raise or start_inventory; default swap), seed (int or null).
Output: {"archipelago_version", "seed", "seed_name", "zip", "players": [slot names],
        "custom_worlds": {game: world version} for the worlds that came from apworlds},
        output/<zip>, the file MultiServer hosts, and output/names.json: each slot's
        number, name and game, and each game's item and location names (its data
        package), for the admin console's searchable lists (#26); and
        output/slot_items.json: every item each slot receives in the whole multiworld, by
        name, with its count and flags, never where it is. The slot view (#30) subtracts
        what the slot has received to show what is still out there.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apsui_worker.jobs import JobContext


PANIC_METHODS = ("swap", "raise", "start_inventory")


def run(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    from apsui_worker.archipelago import custom_worlds_dir
    from apsui_worker.builtin_worlds import load_worlds, not_replaced
    from apsui_worker.jobs import JobFailure

    custom = custom_worlds_dir()
    panic_method = str(params.get("panic_method", "swap"))
    if panic_method not in PANIC_METHODS:
        raise JobFailure("bad-params", f"Unknown panic_method {panic_method!r}")
    # AP reads this one only from host.yaml, in its user folder (this job's, here).
    host_yaml = f"generator:\n  panic_method: {json.dumps(panic_method)}\n"
    (custom.parent / "host.yaml").write_text(host_yaml, encoding="utf-8")
    for apworld in sorted(ctx.input_dir.glob("*.apworld")):
        shutil.copy2(apworld, custom / apworld.name)
    hidden = load_worlds(custom, ctx.archipelago_dir)
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

    if missing := not_replaced(hidden, custom):
        raise JobFailure(
            "builtin-not-replaced",
            f"Archipelago loaded its built-in {missing[0]} instead of the custom apworld",
        )

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
    items = json.dumps(slot_items(multiworld), ensure_ascii=False)
    (ctx.output_dir / "slot_items.json").write_text(items, encoding="utf-8")
    return {
        "archipelago_version": Utils.__version__,
        "seed": seed,
        "seed_name": multiworld.seed_name,
        "zip": zips[0].name,
        "players": [multiworld.player_name[p] for p in multiworld.player_ids],
        "custom_worlds": custom_worlds(multiworld, custom),
    }


def custom_worlds(multiworld: Any, custom: Path) -> dict[str, str]:
    """The games in this multiworld whose world came from a library apworld, and its
    version."""
    found = {}
    for world in multiworld.worlds.values():
        if str(custom.resolve()) in str(getattr(type(world), "__file__", "")):
            found[world.game] = world.world_version.as_simple_string()
    return found


def slot_items(multiworld: Any) -> dict[str, Any]:
    """{"slots": {slot: [{"name", "count", "flags"}]}}: the items placed for each slot
    anywhere in the multiworld, and its starting items. Events (no item id) are left out.
    flags are AP's network flags: 1 progression, 2 useful, 4 trap."""
    found: dict[int, dict[str, list[int]]] = {slot: {} for slot in multiworld.player_ids}

    def add(item: Any) -> None:
        if item is None or item.code is None or item.player not in found:
            return
        entry = found[item.player].setdefault(item.name, [0, int(item.flags)])
        entry[0] += 1

    for location in multiworld.get_locations():
        add(location.item)
    for slot in multiworld.player_ids:
        for item in multiworld.precollected_items[slot]:
            add(item)
    return {
        "slots": {
            str(slot): [
                {"name": name, "count": count, "flags": flags}
                for name, (count, flags) in sorted(items.items())
            ]
            for slot, items in found.items()
        }
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
