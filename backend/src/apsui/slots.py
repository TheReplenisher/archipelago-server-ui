"""Slot login and the slot view (DESIGN.md §6, #30).

A player logs in with their slot name and the room password, which the running
MultiServer checks: the login is a real Archipelago connection, as that slot, with the
`Tracker` tag. The web service keeps no credentials of its own. A session lives in this
process's memory (a cookie holds its random token), so a web restart logs players out.

- **While the server isn't running** there is no slot view and no login: the player is
  told the server is stopped and to contact the admin (conne's decision, 2026-10-11).
- **One connection per slot,** shared by that slot's sessions and closed after a while
  unused; the next view opens it again with the session's password. MultiServer
  announces each new one ("… tracking … has joined"), as it does for any tracker.
- **A session belongs to one generated game** (its seed): a new game means a new login.
- **Unreceived items** follow the room's `!remaining` setting, as AP's own command does:
  enabled shows them, goal shows them once the slot has reached its goal, disabled never.
"""

from __future__ import annotations

import asyncio
import collections
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any

from apsui_server.protocol import ControlError
from sqlalchemy import select
from sqlalchemy.orm import Session

from apsui import host_settings, slot_items
from apsui.ap_client import GameNames, Refused, Tracker, Unavailable
from apsui.config import Settings
from apsui.generation import output_dir
from apsui.lifecycle import GameState, current_game
from apsui.models import Generation
from apsui.player_feed import Feed
from apsui.server_control import request

log = logging.getLogger(__name__)

COOKIE = "apsui_slot"
SESSION_IDLE = 12 * 3600.0
TRACKER_IDLE = 600.0
OBSERVER_IDLE = 1800.0
"""The player feed's connection closes after this long without a player looking."""
LOGIN_ATTEMPTS = 10
"""Logins per client address per minute; each one is a connection to MultiServer."""
MAX_NAME = 16
MAX_PASSWORD = 64

STATUS_LABELS = {0: "unspecified", 10: "no priority", 20: "avoid", 30: "priority", 40: "found"}


class SlotError(Exception):
    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def stopped() -> SlotError:
    return SlotError("server-stopped", "The server is stopped", 503)


@dataclass
class SlotSession:
    name: str
    password: str
    seed: str
    last_seen: float


class SlotViews:
    """Every slot session and slot connection of this web service."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sessions: dict[str, SlotSession] = {}
        self.trackers: dict[str, Tracker] = {}
        self.last_used: dict[str, float] = {}
        self.attempts: dict[str, collections.deque[float]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.feed = Feed()
        self.observer: Tracker | None = None
        self.observer_used = 0.0
        self._observer_lock = asyncio.Lock()

    async def login(self, db: Session, name: str, password: str, client: str) -> str:
        """Check the slot name and password against the running server; returns a
        session token."""
        self._limit(client)
        if not name or len(name) > MAX_NAME or len(password) > MAX_PASSWORD:
            raise SlotError("login-refused", "Slot name or room password is wrong", 401)
        seed = await self._running_seed(db)
        async with self._lock(name):
            tracker = self.trackers.get(name)
            if tracker is None or not tracker.open or tracker.password != password:
                await self._connect(name, password)
        token = secrets.token_urlsafe(32)
        self.sessions[_key(token)] = SlotSession(name, password, seed, time.monotonic())
        log.info("Slot %r logged in to the slot view", name)
        return token

    def logout(self, token: str | None) -> None:
        if token:
            self.sessions.pop(_key(token), None)

    async def view(self, db: Session, token: str | None) -> dict[str, Any]:
        session = self._session(token)
        seed = await self._running_seed(db)
        if session.seed != seed:
            self.logout(token)
            raise SlotError("game-changed", "A new game has started: log in again", 401)
        async with self._lock(session.name):
            tracker = self.trackers.get(session.name)
            if tracker is None or not tracker.open:
                try:
                    tracker = await self._connect(session.name, session.password)
                except SlotError as exc:
                    if exc.status == 401:  # the password has changed since
                        self.logout(token)
                        raise SlotError("login-expired", "Log in again", 401) from exc
                    raise
        self.last_used[session.name] = time.monotonic()
        await self._sweep()
        values = host_settings.load(db, self.settings)
        pool = slot_items.load(output_dir(self.settings), tracker.slot)
        return snapshot(tracker, pool, values.remaining_mode)

    async def slot_name(self, db: Session, token: str | None) -> str:
        """The slot this session is logged in to, while its game is the one running."""
        session = self._session(token)
        if session.seed != await self._running_seed(db):
            self.logout(token)
            raise SlotError("game-changed", "A new game has started: log in again", 401)
        return session.name

    async def feed_after(self, db: Session, token: str | None, last: int) -> dict[str, Any]:
        """The player feed's entries after `last` (#35), for a logged-in player. Opens
        the observer connection if it isn't open."""
        await self.slot_name(db, token)
        seed = await self._running_seed(db)
        async with self._observer_lock:
            if self.feed.seed != seed:
                await self._close_observer()
                self.feed.reset(seed)
            if self.observer is None or not self.observer.open:
                await self._open_observer(db)
        self.observer_used = time.monotonic()
        entries = self.feed.after(last)
        return {"entries": entries, "last": entries[-1]["id"] if entries else last}

    async def _open_observer(self, db: Session) -> None:
        """Connect as the game's first slot, with the room password from the settings."""
        game = current_game(db)
        generation = db.scalars(
            select(Generation)
            .where(Generation.game_id == game.id, Generation.status == "ok")
            .order_by(Generation.id.desc())
        ).first()
        players = generation.players if generation else None
        if not players:
            raise SlotError("feed-unavailable", "The feed isn't available", 503)
        password = host_settings.load(db, self.settings).password
        observer = Tracker(
            self.settings.relay_socket,
            players[0],
            password,
            self.settings.archipelago_version,
            on_print=self.feed.add,
        )
        try:
            await observer.start()
        except (Refused, Unavailable) as exc:
            log.warning("The player feed can't connect: %s", exc)
            raise SlotError("feed-unavailable", "The feed isn't available right now", 503) from exc
        self.observer = observer

    async def _close_observer(self) -> None:
        if self.observer is not None:
            await self.observer.close()
            self.observer = None

    async def reset(self) -> None:
        """Forget every session and connection: the data under them was replaced (#38)."""
        await self.close()
        self.sessions.clear()
        self.feed = Feed()

    async def close(self) -> None:
        for tracker in list(self.trackers.values()):
            await tracker.close()
        self.trackers.clear()
        await self._close_observer()

    async def _connect(self, name: str, password: str) -> Tracker:
        tracker = Tracker(
            self.settings.relay_socket, name, password, self.settings.archipelago_version
        )
        try:
            await tracker.start()
        except Refused as exc:
            raise SlotError("login-refused", "Slot name or room password is wrong", 401) from exc
        except Unavailable as exc:
            log.warning("Slot view can't reach MultiServer: %s", exc)
            raise SlotError("server-unavailable", "The server isn't answering", 503) from exc
        old = self.trackers.get(name)
        if old is not None:
            await old.close()
        self.trackers[name] = tracker
        self.last_used[name] = time.monotonic()
        return tracker

    async def _running_seed(self, db: Session) -> str:
        """The seed being hosted, or SlotError when the server isn't running."""
        game = current_game(db)
        if game.state != GameState.RUNNING:
            raise stopped()
        try:
            status = await request(self.settings.control_socket, {"op": "status"})
        except ControlError as exc:
            raise stopped() from exc
        if status.get("state") != "running":
            raise stopped()
        generation = db.scalars(
            select(Generation)
            .where(Generation.game_id == game.id, Generation.status == "ok")
            .order_by(Generation.id.desc())
        ).first()
        if generation is None or not generation.seed_name:
            raise stopped()
        return generation.seed_name

    def _session(self, token: str | None) -> SlotSession:
        session = self.sessions.get(_key(token)) if token else None
        now = time.monotonic()
        if session is None or now - session.last_seen > SESSION_IDLE:
            self.logout(token)
            raise SlotError("not-logged-in", "Log in with your slot name", 401)
        session.last_seen = now
        return session

    async def _sweep(self) -> None:
        """Close slot connections nobody has looked at for a while."""
        now = time.monotonic()
        for name, tracker in list(self.trackers.items()):
            if now - self.last_used.get(name, 0) > TRACKER_IDLE:
                await tracker.close()
                del self.trackers[name]
        if self.observer is not None and now - self.observer_used > OBSERVER_IDLE:
            await self._close_observer()

    def _limit(self, client: str) -> None:
        now = time.monotonic()
        recent = self.attempts.setdefault(client, collections.deque())
        while recent and now - recent[0] > 60:
            recent.popleft()
        if len(recent) >= LOGIN_ATTEMPTS:
            raise SlotError("too-many-logins", "Too many logins: wait a minute", 429)
        recent.append(now)

    def _lock(self, name: str) -> asyncio.Lock:
        return self._locks.setdefault(name, asyncio.Lock())


def _key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def snapshot(
    tracker: Tracker, pool: list[slot_items.PoolItem] | None, remaining_mode: str
) -> dict[str, Any]:
    """What the slot view shows. Locations of unreceived items, and what unchecked
    locations hold, are never part of it."""

    def names(game: str) -> GameNames:
        return tracker.names.get(game) or GameNames()

    def item(game: str, code: int) -> str:
        return names(game).items.get(code, f"Item {code}")

    def location(game: str, code: int) -> str:
        if code == -2:
            return "Starting inventory"
        if code == -1:
            return "Sent by the server"
        return names(game).locations.get(code, f"Location {code}")

    def player(slot: int) -> str:
        return tracker.players.get(slot, f"Player {slot}")

    own = tracker.game
    received = [
        {
            "item": item(own, i.item),
            "player": player(i.player),
            "location": location(tracker.games.get(i.player, ""), i.location),
            "flags": i.flags,
        }
        for i in tracker.received
    ]
    shown = remaining_mode == "enabled" or (remaining_mode == "goal" and tracker.goal)
    unreceived = None
    if pool is not None and shown:
        got = collections.Counter(r["item"] for r in received)
        unreceived = [
            {"item": p.name, "count": p.count - got[p.name], "flags": p.flags}
            for p in pool
            if p.count > got[p.name]
        ]
    return {
        "slot": {"name": tracker.name, "game": own, "team": tracker.team, "slot": tracker.slot},
        "live": tracker.open,
        "goal": tracker.goal,
        "hint_points": tracker.hint_points,
        "checked": len(tracker.checked),
        "locations": len(tracker.checked) + len(tracker.missing),
        "received": received,
        "unreceived": unreceived,
        "unreceived_rule": remaining_mode if pool is not None else "unavailable",
        "unchecked": sorted(location(own, code) for code in tracker.missing),
        "hints": [
            {
                "item": item(tracker.games.get(h.receiving_player, ""), h.item),
                "receiving": player(h.receiving_player),
                "finding": player(h.finding_player),
                "location": location(tracker.games.get(h.finding_player, ""), h.location),
                "entrance": h.entrance,
                "found": h.found,
                "status": STATUS_LABELS.get(h.status, "unspecified"),
                "flags": h.item_flags,
            }
            for h in tracker.hints
        ],
    }
