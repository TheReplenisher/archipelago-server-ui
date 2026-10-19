"""The player feed (DESIGN.md §5, server feed; #35): what MultiServer tells every player,
for players logged in to a slot.

It never comes from the admin's feed (MultiServer's own output holds the room password).
One observer connection, as the first slot with the `Tracker` tag, collects MultiServer's
PrintJSON messages. Only the kinds every player already sees in their own client are
kept: item sends, `/send` cheats, chat, server chat, joins and parts, goals, releases,
collects and countdowns, and the untyped notices MultiServer sends everyone (its
console's `/send` is one: "Cheat console: sending …"). Hints and anything addressed to the
observer's own slot (tutorials, command results, and the one untyped message AP 0.6.8
sends a single client, a compression warning) are dropped, so one slot's hints never
reach the others.

Each entry is rendered as parts (text, player, item, location), with an item's flags so
the page can mark progression, useful and trap items. The last 500 are kept, and a new
game starts a new feed.
"""

from __future__ import annotations

import collections
import itertools
import time
from typing import Any

from apsui.ap_client import Tracker

MAX_ENTRIES = 500
MAX_PART = 300
MAX_PARTS = 60
SHOWN = frozenset(
    {
        "ItemSend",
        "ItemCheat",
        "Chat",
        "ServerChat",
        "Join",
        "Part",
        "Goal",
        "Release",
        "Collect",
        "Countdown",
        "Notice",
    }
)
PRIVATE_NOTICES = ("Warning: your client does not support compressed",)
"""Untyped messages AP sends only to the connecting client."""


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def render(tracker: Tracker, message: dict[str, Any]) -> dict[str, Any] | None:
    """A PrintJSON message as a feed entry, or None if it isn't for everyone."""
    kind = message.get("type")
    data = message.get("data")
    if not isinstance(data, list):
        return None
    if kind is None:  # broadcast_text_all without a type: a notice for everyone
        first = data[0].get("text") if data and isinstance(data[0], dict) else None
        if not isinstance(first, str) or first.startswith(PRIVATE_NOTICES):
            return None
        kind = "Notice"
    if kind not in SHOWN:
        return None
    parts: list[dict[str, Any]] = []
    for raw in data[:MAX_PARTS]:
        if not isinstance(raw, dict):
            continue
        text = raw.get("text")
        text = text if isinstance(text, str) else ""
        part_type = raw.get("type")
        owner = _int(raw.get("player")) or 0
        game = tracker.games.get(owner, "")
        names = tracker.names.get(game)
        number = int(text) if text.lstrip("-").isdigit() else None
        if part_type == "player_id" and number is not None:
            parts.append({"kind": "player", "text": tracker.players.get(number, text)})
        elif part_type == "item_id" and number is not None:
            name = names.items.get(number, text) if names else text
            flags = _int(raw.get("flags")) or 0
            parts.append({"kind": "item", "text": name, "flags": flags})
        elif part_type == "location_id" and number is not None:
            name = names.locations.get(number, text) if names else text
            parts.append({"kind": "location", "text": name})
        elif part_type in ("player_name", "item_name", "location_name", "entrance_name"):
            parts.append({"kind": str(part_type).removesuffix("_name"), "text": text})
        else:
            parts.append({"kind": "text", "text": text})
    for part in parts:
        part["text"] = part["text"][:MAX_PART]
    return {"type": kind, "parts": parts} if parts else None


class Feed:
    """The entries of one game's feed, numbered so a page can ask for what's new."""

    def __init__(self) -> None:
        self.seed: str | None = None
        self.entries: collections.deque[dict[str, Any]] = collections.deque(maxlen=MAX_ENTRIES)
        self._ids = itertools.count(1)

    def reset(self, seed: str) -> None:
        self.seed = seed
        self.entries.clear()

    def add(self, tracker: Tracker, message: dict[str, Any]) -> None:
        entry = render(tracker, message)
        if entry is not None:
            self.entries.append({"id": next(self._ids), "at": time.time()} | entry)

    def after(self, last: int) -> list[dict[str, Any]]:
        return [e for e in self.entries if e["id"] > last]
