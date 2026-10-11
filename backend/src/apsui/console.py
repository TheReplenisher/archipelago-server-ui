"""What the admin console's command assistance needs (DESIGN.md §5, admin console; #26).

- **The command catalog**, built into the image from the pinned MultiServer's command
  handlers (`apsui_server.commands`), read from `Settings.command_catalog`. Without one
  (a development setup), the console offers free text only.
- **The names** for its searchable lists: the slots, and each game's item and location
  names, written by the generate job as `names.json`. It comes from the worker, so it is
  parsed strictly and only the parsed copy is kept, beside the output zip, so it goes
  when the output does.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from apsui.config import Settings

log = logging.getLogger(__name__)

NAMES_FILE = "names.json"
MAX_NAMES_BYTES = 64 * 1024 * 1024

Name = Annotated[str, StringConstraints(min_length=1, max_length=256)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CommandArg(Strict):
    name: str
    kind: str
    """player, item, location, number, option or text."""
    required: bool
    rest: bool
    """Takes the rest of the line (the handler joins the words)."""
    default: str | None = None
    choices: list[str] = []


class Command(Strict):
    name: str
    help: str
    raw: bool
    """The handler takes everything after the command as one text, unquoted."""
    args: list[CommandArg]


class Catalog(Strict):
    commands: list[Command]


class Slot(Strict):
    slot: int = Field(ge=1)
    name: Name
    game: Name


class GameNames(Strict):
    items: list[Name] = Field(max_length=100_000)
    locations: list[Name] = Field(max_length=100_000)


class Names(Strict):
    players: list[Slot] = Field(max_length=1000)
    games: dict[Name, GameNames] = Field(max_length=1000)


def commands(settings: Settings) -> list[Command]:
    path = settings.command_catalog
    if path is None or not path.is_file():
        return []
    return Catalog.model_validate_json(path.read_bytes()).commands


def store_names(source: Path, target_dir: Path) -> None:
    """Keep the generate job's names.json, if it parses; the game works without it."""
    try:
        if source.stat().st_size > MAX_NAMES_BYTES:
            raise ValueError("too large")
        names = Names.model_validate_json(source.read_bytes())
    except (OSError, ValueError) as exc:  # a ValidationError is a ValueError
        log.warning("Ignoring the generation's console names: %s", str(exc)[:500])
        return
    (target_dir / NAMES_FILE).write_text(names.model_dump_json(), encoding="utf-8")
