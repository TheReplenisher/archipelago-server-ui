"""Every item each slot receives in the multiworld, by name, written by the generate job
as `slot_items.json` (#30). The slot view subtracts what the slot has received to list
what is still out there, never where. It comes from the worker, so it is parsed strictly
and only the parsed copy is kept, beside the output zip, as names.json is."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

log = logging.getLogger(__name__)

SLOT_ITEMS_FILE = "slot_items.json"
MAX_BYTES = 64 * 1024 * 1024


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PoolItem(_Strict):
    name: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    count: int = Field(ge=1, le=1_000_000)
    flags: int = Field(ge=0, le=0xFF)
    """AP's network flags: 1 progression, 2 useful, 4 trap."""


class SlotItems(_Strict):
    slots: dict[Annotated[str, StringConstraints(pattern=r"^[0-9]{1,6}$")], list[PoolItem]] = Field(
        max_length=10_000
    )


def store(source: Path, target_dir: Path) -> None:
    """Keep the generate job's slot_items.json, if it parses; without it the slot view
    doesn't list unreceived items."""
    try:
        if source.stat().st_size > MAX_BYTES:
            raise ValueError("too large")
        items = SlotItems.model_validate_json(source.read_bytes())
    except (OSError, ValueError) as exc:  # a ValidationError is a ValueError
        log.warning("Ignoring the generation's slot items: %s", str(exc)[:500])
        return
    (target_dir / SLOT_ITEMS_FILE).write_text(items.model_dump_json(), encoding="utf-8")


def load(output_dir: Path, slot: int) -> list[PoolItem] | None:
    """One slot's items, or None when this game was generated without the file."""
    path = output_dir / SLOT_ITEMS_FILE
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        items = SlotItems.model_validate_json(path.read_bytes())
    except (OSError, ValueError):
        return None
    return items.slots.get(str(slot), [])
