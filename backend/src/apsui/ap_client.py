"""A small Archipelago-protocol client for the slot view (DESIGN.md §6, #30).

It connects as a slot with the `Tracker` tag, the way PopTracker or Universal Tracker do,
through the server supervisor's relay socket (the web and server services share no
network). It keeps what the slot view shows: received items, checked and missing
locations, hints, the slot's goal status, and the names of every game's items and
locations.

MultiServer runs apworld code, so everything it sends is untrusted: messages are size
limited and read field by field, and anything malformed is skipped.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from websockets.asyncio.client import ClientConnection, unix_connect
from websockets.exceptions import WebSocketException

log = logging.getLogger(__name__)

MAX_MESSAGE_BYTES = 64 * 1024 * 1024
"""A data package for a big multiworld runs to several MB."""
CONNECT_TIMEOUT = 15.0
CLIENT_GOAL = 30


class Refused(Exception):
    """MultiServer refused the login (InvalidSlot, InvalidPassword, …)."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__(", ".join(errors) or "refused")
        self.errors = errors


class Unavailable(Exception):
    """MultiServer couldn't be reached, or closed the connection."""


def version(text: str) -> dict[str, Any]:
    """AP's Version as the protocol sends it, from "0.6.8"."""
    parts = [int(p) if p.isdigit() else 0 for p in (text or "0.6.8").split(".")[:3]]
    major, minor, build = [*parts, 0, 0, 0][:3]
    return {"major": major, "minor": minor, "build": build, "class": "Version"}


def _int(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


@dataclass
class Item:
    item: int
    location: int
    player: int
    flags: int


@dataclass
class Hint:
    receiving_player: int
    finding_player: int
    location: int
    item: int
    found: bool
    entrance: str
    item_flags: int
    status: int


@dataclass
class GameNames:
    items: dict[int, str] = field(default_factory=dict)
    locations: dict[int, str] = field(default_factory=dict)


class Tracker:
    """One slot's live view. start() connects and waits for MultiServer's answer; the
    connection then stays open, updating the state, until close() or MultiServer goes."""

    def __init__(
        self,
        relay: Path,
        name: str,
        password: str,
        ap_version: str,
        on_print: Callable[[Tracker, dict[str, Any]], None] | None = None,
    ) -> None:
        self.relay, self.name, self.password = relay, name, password
        self.on_print = on_print
        """Called with each PrintJSON message (the player feed's observer, #35)."""
        self.ap_version = ap_version
        self.team = self.slot = 0
        self.players: dict[int, str] = {}
        self.games: dict[int, str] = {}
        self.checked: set[int] = set()
        self.missing: set[int] = set()
        self.received: list[Item] = []
        self.hints: list[Hint] = []
        self.client_status = 0
        self.hint_points = 0
        self.names: dict[str, GameNames] = {}
        self.open = False
        self._task: asyncio.Task[None] | None = None
        self._ws: ClientConnection | None = None

    @property
    def game(self) -> str:
        return self.games.get(self.slot, "")

    @property
    def hints_key(self) -> str:
        return f"_read_hints_{self.team}_{self.slot}"

    @property
    def status_key(self) -> str:
        return f"_read_client_status_{self.team}_{self.slot}"

    async def start(self) -> None:
        """Connect and log in; raises Refused or Unavailable."""
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                ws = await unix_connect(
                    str(self.relay), uri="ws://localhost/", max_size=MAX_MESSAGE_BYTES
                )
                try:
                    await self._login(ws)
                except BaseException:
                    await ws.close()
                    raise
        except (OSError, TimeoutError, WebSocketException) as exc:
            raise Unavailable(str(exc) or type(exc).__name__) from exc
        self._ws, self.open = ws, True
        self._task = asyncio.create_task(self._listen(ws))

    async def close(self) -> None:
        self.open = False
        if self._ws is not None:
            await self._ws.close()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _login(self, ws: ClientConnection) -> None:
        await self._receive(ws)  # RoomInfo
        await self._send(
            ws,
            {
                "cmd": "Connect",
                "password": self.password,
                "game": "",
                "name": self.name,
                "uuid": uuid.uuid4().hex,
                "version": version(self.ap_version),
                "items_handling": 0b111,
                "tags": ["Tracker"],
                "slot_data": False,
            },
        )
        # Logged in once Connected arrives; ready once the names and stored hints have too.
        waiting: set[str] = {"Connected"}
        while waiting:
            for message in await self._receive(ws):
                command = message.get("cmd")
                if command == "ConnectionRefused":
                    errors = message.get("errors")
                    found = errors if isinstance(errors, list) else []
                    raise Refused([e for e in found if isinstance(e, str)])
                if command == "Connected" and "Connected" in waiting:
                    self._connected(message)
                    games = sorted(set(self.games.values()))
                    keys = [self.hints_key, self.status_key]
                    await self._send(
                        ws,
                        {"cmd": "GetDataPackage", "games": games},
                        {"cmd": "Get", "keys": keys},
                        {"cmd": "SetNotify", "keys": keys},
                    )
                    waiting = {"DataPackage", "Retrieved"}
                    continue
                self._handle(message)
                waiting.discard(str(command))

    async def _listen(self, ws: ClientConnection) -> None:
        try:
            while True:
                for message in await self._receive(ws):
                    self._handle(message)
        except (Unavailable, WebSocketException, OSError):
            pass
        finally:
            self.open = False

    async def _send(self, ws: ClientConnection, *messages: dict[str, Any]) -> None:
        await ws.send(json.dumps(list(messages)))

    async def _receive(self, ws: ClientConnection) -> list[dict[str, Any]]:
        try:
            data = await ws.recv()
        except WebSocketException as exc:
            raise Unavailable("connection closed") from exc
        try:
            messages = json.loads(data)
        except ValueError:
            return []
        if not isinstance(messages, list):
            return []
        return [m for m in messages if isinstance(m, dict)]

    def _connected(self, message: dict[str, Any]) -> None:
        self.team, self.slot = _int(message.get("team")), _int(message.get("slot"))
        self._players(message.get("players"))
        slot_info = message.get("slot_info")
        if isinstance(slot_info, dict):
            for key, info in slot_info.items():
                if isinstance(info, dict) and str(key).isdigit():
                    self.games[int(key)] = _str(info.get("game"))
                    self.players.setdefault(int(key), _str(info.get("name")))
        self.checked = {i for i in message.get("checked_locations") or [] if isinstance(i, int)}
        self.missing = {i for i in message.get("missing_locations") or [] if isinstance(i, int)}
        self.hint_points = _int(message.get("hint_points"))

    def _players(self, players: object) -> None:
        if not isinstance(players, list):
            return
        for player in players:
            if isinstance(player, dict) and _int(player.get("team")) == self.team:
                name = _str(player.get("alias")) or _str(player.get("name"))
                self.players[_int(player.get("slot"))] = name

    def _handle(self, message: dict[str, Any]) -> None:
        command = message.get("cmd")
        if command == "ReceivedItems":
            items = [i for i in (_item(x) for x in message.get("items") or []) if i]
            index = _int(message.get("index"), -1)
            if index == 0:
                self.received = items
            elif index == len(self.received):
                self.received += items
        elif command == "RoomUpdate":
            new = {i for i in message.get("checked_locations") or [] if isinstance(i, int)}
            self.checked |= new
            self.missing -= new
            if "hint_points" in message:
                self.hint_points = _int(message.get("hint_points"))
            self._players(message.get("players"))
        elif command == "DataPackage":
            data = message.get("data")
            games = data.get("games") if isinstance(data, dict) else None
            if isinstance(games, dict):
                for game, package in games.items():
                    if isinstance(game, str) and isinstance(package, dict):
                        self.names[game] = _names(package)
        elif command == "Retrieved":
            keys = message.get("keys")
            if isinstance(keys, dict):
                for key, value in keys.items():
                    self._stored(key, value)
        elif command == "SetReply":
            self._stored(message.get("key"), message.get("value"))
        elif command == "PrintJSON" and self.on_print is not None:
            self.on_print(self, message)

    def _stored(self, key: object, value: object) -> None:
        if key == self.hints_key and isinstance(value, list):
            self.hints = [h for h in (_hint(x) for x in value) if h]
        elif key == self.status_key:
            self.client_status = _int(value)

    @property
    def goal(self) -> bool:
        return self.client_status == CLIENT_GOAL


def _item(raw: object) -> Item | None:
    if not isinstance(raw, dict):
        return None
    return Item(
        _int(raw.get("item")), _int(raw.get("location")), _int(raw.get("player")),
        _int(raw.get("flags")),
    )  # fmt: skip


def _hint(raw: object) -> Hint | None:
    if not isinstance(raw, dict):
        return None
    return Hint(
        receiving_player=_int(raw.get("receiving_player")),
        finding_player=_int(raw.get("finding_player")),
        location=_int(raw.get("location")),
        item=_int(raw.get("item")),
        found=raw.get("found") is True,
        entrance=_str(raw.get("entrance"))[:200],
        item_flags=_int(raw.get("item_flags")),
        status=_int(raw.get("status")),
    )


def _names(package: dict[str, Any]) -> GameNames:
    names = GameNames()
    for source, target in (
        (package.get("item_name_to_id"), names.items),
        (package.get("location_name_to_id"), names.locations),
    ):
        if isinstance(source, dict):
            for name, code in source.items():
                if isinstance(name, str) and isinstance(code, int):
                    target[code] = name[:256]
    return names
