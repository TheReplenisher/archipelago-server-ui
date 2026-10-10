"""Level-1 checks for one uploaded YAML file (DESIGN.md §4).

Every document is checked on its own: the name (present, fixed, at most 16 characters),
the game (a world Archipelago can load), and every option value that could be rolled.
A name problem is reported separately (name_error) and the other checks still run, so the
admin can rename the slot instead of asking for a re-upload.
Archipelago's own roll_settings() then runs a few times, which also exercises triggers,
linked options and `requires`. No generation happens: a YAML that only works inside a
full multiworld must not be rejected here.

Checks across files (unique names, the slot limit) need the rest of the game, so the web
service does them.

Input: upload.yaml, plus any library apworlds chosen for it (<module>.apworld).
Params: plando_options (str, default AP's "bosses, connections, texts"),
        allow_quantity (bool, default false), rolls (int, default 5).
Output: {"error": <file-level error or null>, "documents": [<per document>],
         "custom_games": [games whose world came from a supplied apworld]}
"""

from __future__ import annotations

import copy
import random
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apsui_worker.jobs import JobContext

MAX_NAME_LENGTH = 16
MAX_DETAIL = 4000


class DocumentError(Exception):
    def __init__(self, code: str, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.code, self.message, self.detail = code, message, detail[:MAX_DETAIL]

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "detail": self.detail}


def run(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    from apsui_worker.archipelago import custom_worlds_dir

    yaml_file = ctx.input_dir / "upload.yaml"
    if not yaml_file.is_file():
        from apsui_worker.jobs import JobFailure

        raise JobFailure("bad-input", "Expected upload.yaml")
    # Library apworlds chosen for this upload become this job's custom worlds, before
    # anything imports worlds.
    custom = custom_worlds_dir()
    supplied = []
    for apworld in sorted(ctx.input_dir.glob("*.apworld")):
        shutil.copy2(apworld, custom / apworld.name)
        supplied.append(str(custom / apworld.name))

    import Utils
    from BaseClasses import PlandoOptions

    plando = PlandoOptions.from_option_string(
        str(params.get("plando_options", "bosses, connections, texts"))
    )
    allow_quantity = bool(params.get("allow_quantity", False))
    rolls = max(1, min(int(params.get("rolls", 5)), 50))

    try:
        documents = list(Utils.parse_yamls(_read_text(yaml_file)))
    except Exception as exc:  # malformed YAML, duplicate keys, bad encoding
        return {
            "error": DocumentError(
                "yaml-invalid", "File is not valid YAML", Utils.get_all_causes(exc)
            ).as_dict(),
            "documents": [],
        }

    results = []
    for index, document in enumerate(documents):
        result: dict[str, Any] = {"index": index, "empty": document is None, "warnings": []}
        if document is not None:
            try:
                result |= check_document(document, plando, allow_quantity, rolls, result)
                result["error"] = None
            except DocumentError as exc:
                result["error"] = exc.as_dict()
        results.append(result)
    if not any(not r["empty"] for r in results):
        return {
            "error": DocumentError("yaml-empty", "File has no player settings").as_dict(),
            "documents": results,
        }
    return {"error": None, "documents": results, "custom_games": custom_games(supplied)}


def custom_games(supplied: list[str]) -> list[str]:
    """The games whose world came from one of the supplied apworlds. Archipelago skips an
    apworld whose game is already loaded, so the web service checks its choice was used."""
    from worlds.AutoWorld import AutoWorldRegister

    return sorted(
        game
        for game, cls in AutoWorldRegister.world_types.items()
        if any(path in str(getattr(cls, "__file__", "") or "") for path in supplied)
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("File is not UTF-8 text") from exc


def check_document(
    doc: object, plando: Any, allow_quantity: bool, rolls: int, result: dict[str, Any]
) -> dict[str, Any]:
    import Utils
    from worlds import AutoWorldRegister, failed_world_loads

    if not isinstance(doc, dict):
        raise DocumentError("not-a-mapping", "Document is not a YAML mapping")

    quantity = doc.get("quantity", 1)
    if not isinstance(quantity, int) or quantity < 1:
        raise DocumentError("quantity-invalid", "Quantity must be a whole number, 1 or more")
    if quantity > 1 and not allow_quantity:
        raise DocumentError("quantity-disabled", "Quantity above 1 is turned off")

    # A name problem doesn't stop the other checks: the admin can fix the name on the spot
    # (the web service edits it), so the rest of the document must already be known good.
    raw = doc.get("name")
    result["name_raw"] = name_raw(raw)
    try:
        name = check_name(raw)
        result |= {"name": name, "name_error": None}
    except DocumentError as exc:
        name = PLACEHOLDER_NAME
        result |= {"name": None, "name_error": exc.as_dict()}
    result["quantity"] = quantity

    games = candidates(doc.get("game"))
    if not games or not all(isinstance(g, str) for g in games):
        raise DocumentError("game-missing", "No game is set")
    result["games"] = games
    for game in games:
        if game not in AutoWorldRegister.world_types:
            known = list(AutoWorldRegister.world_types) + list(failed_world_loads)
            guess, certainty = Utils.get_fuzzy_results(game, known, limit=1)[0]
            raise DocumentError(
                "game-unknown",
                f"Unknown game: {game}"[:80],
                f"No world handles {game!r}. Closest match: {guess!r} ({certainty}% sure).",
            )
        section = doc.get(game)
        if not isinstance(section, dict):
            raise DocumentError("game-section-missing", f"No options for {game}"[:80])
        result["warnings"] += check_options(
            AutoWorldRegister.world_types[game], section, name, plando
        )

    import Generate

    for roll in range(rolls):
        random.seed(roll)
        try:
            Generate.roll_settings(copy.deepcopy(doc), plando)
        except Exception as exc:
            raise DocumentError(
                "roll-failed", "Options could not be rolled", Utils.get_all_causes(exc)
            ) from exc
    return result


PLACEHOLDER_NAME = "Player"
"""Stands in for a broken name while the options are checked (verify() takes a name)."""


def name_raw(value: object) -> str | list[str] | None:
    """What the file has as its name, for the admin to see and pick from: the string, the
    names a weighted entry could roll, or None."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return [str(v)[:100] for v in candidates(value)][:20]
    return str(value)[:100]


def check_name(name: object) -> str:
    if name is None:
        raise DocumentError("name-missing", "Slot name is missing")
    if not isinstance(name, str):
        # Weighted or random names can't be logged in to (DESIGN.md §6).
        raise DocumentError("name-not-fixed", "Slot name must be one fixed name")
    if "%" in name:
        raise DocumentError(
            "name-template", "Name templates like %number% aren't supported", f"name: {name!r}"
        )
    name = name.strip()
    if not name:
        raise DocumentError("name-missing", "Slot name is missing")
    if len(name) > MAX_NAME_LENGTH:
        raise DocumentError(
            "name-too-long", "Slot name is longer than 16 characters", f"name: {name!r}"
        )
    if name == "Archipelago":
        raise DocumentError("name-reserved", "Slot name can't be Archipelago")
    return name


def candidates(value: object) -> list[Any]:
    """Every value a weighted entry could roll: dict keys with a non-zero weight, list
    items, or the value itself."""
    if isinstance(value, dict):
        return [key for key, weight in value.items() if weight]
    if isinstance(value, list):
        return list(value)
    return [] if value is None else [value]


def check_options(world: Any, section: dict[str, Any], name: str, plando: Any) -> list[str]:
    """Raise for the first illegal value; return warnings for unknown option names."""
    import Utils

    hints = world.options_dataclass.type_hints
    for key, option in hints.items():
        if key not in section:
            continue
        value = section[key]
        values = candidates(value) if option.supports_weighting else [value]
        for candidate in values:
            try:
                option.from_any(candidate).verify(world, name, plando)
            except Exception as exc:
                raise DocumentError(
                    "option-invalid",
                    f"Invalid value for option {key}"[:80],
                    f"{world.game} option {key} = {candidate!r}: {Utils.get_all_causes(exc)}",
                ) from exc
    allowed = set(hints) | {"triggers"}
    if world.game == "A Link to the Past":  # not yet on AP's options system
        allowed |= {"sprite_pool", "sprite", "random_sprite_on_event"}
    return [
        f"{key} is not an option of {world.game}; Archipelago will ignore it"
        for key in section
        if key not in allowed
    ]
