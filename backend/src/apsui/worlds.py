"""Which world each game uses in the current multiworld (DESIGN.md §4: the apworld library
and version locking).

An upload may pick library apworlds. Each game it uses is then checked with the picked
apworld, else the game's locked world, else the official built-in world: a custom
apworld from an earlier game is never used unless picked or locked. The first accepted
YAML for a game locks it, because Archipelago allows one world per game.

The lock is compared with what the worker actually checked the file with, when the check
finishes: another upload may have locked the game in the meantime.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from apsui.apworlds import label as apworld_label
from apsui.apworlds import library_path
from apsui.config import Settings
from apsui.models import Apworld, Slot, Upload, WorldLock

LOCKED_MESSAGE = "Different game version already in use — contact the server admin"


class WorldError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def locks(session: Session, game_id: int) -> list[WorldLock]:
    return list(
        session.scalars(
            select(WorldLock).where(WorldLock.game_id == game_id).order_by(WorldLock.world)
        )
    )


def choose(session: Session, game_id: int, apworld_ids: Iterable[int]) -> dict[str, Apworld]:
    """The library apworlds a new upload is checked with, by game: the ones picked for it,
    plus the locked custom world of every other game."""
    chosen: dict[str, Apworld] = {}
    for apworld_id in dict.fromkeys(apworld_ids):
        apworld = session.get(Apworld, apworld_id)
        if apworld is None or apworld.status != "approved" or not apworld.game:
            raise WorldError("apworld-unavailable", "That apworld isn't in the library")
        if apworld.replaces_builtin:
            # Archipelago would load the built-in world instead (#77).
            raise WorldError(
                "builtin-replacement-unsupported",
                "Custom versions of built-in games aren't supported yet",
            )
        if apworld.game in chosen:
            raise WorldError("two-versions", f"Pick one version of {apworld.game}")
        chosen[apworld.game] = apworld
    for lock in locks(session, game_id):
        if lock.apworld is not None and lock.world not in chosen:
            chosen[lock.world] = lock.apworld
    modules = [a.module for a in chosen.values()]
    if len(set(modules)) != len(modules):
        raise WorldError("module-clash", "Two of these apworlds have the same file name")
    return chosen


def job_inputs(session: Session, settings: Settings, upload: Upload) -> dict[str, Path]:
    """The library files to give the worker with this upload's YAML."""
    inputs = {}
    for apworld_id in (upload.worlds or {}).values():
        apworld = session.get(Apworld, apworld_id)
        if apworld is not None:
            inputs[f"{apworld.module}.apworld"] = library_path(settings, apworld)
    return inputs


def conflict(session: Session, upload: Upload, games: Iterable[str]) -> str | None:
    """The first game whose lock disagrees with the world this upload was checked with."""
    locked = {lock.world: lock.apworld_id for lock in locks(session, upload.game_id)}
    checked_with = upload.worlds or {}
    for game in sorted(set(games)):
        if game in locked and locked[game] != checked_with.get(game):
            return game
    return None


def lock(session: Session, upload: Upload, games: Iterable[str]) -> None:
    """Lock every game this accepted upload uses that isn't locked yet."""
    locked = {lock.world for lock in locks(session, upload.game_id)}
    for game in sorted(set(games) - locked):
        session.add(
            WorldLock(
                game_id=upload.game_id,
                world=game,
                apworld_id=(upload.worlds or {}).get(game),
                upload_id=upload.id,
                locked_at=datetime.now(UTC),
            )
        )


def release_unused(session: Session, game_id: int) -> None:
    """Unlock games no accepted slot uses any more, e.g. after a YAML was removed."""
    session.flush()
    used = {
        game
        for games in session.scalars(select(Slot.games).where(Slot.game_id == game_id))
        for game in games
    }
    for lock in locks(session, game_id):
        if lock.world not in used:
            session.delete(lock)


def label(settings: Settings, lock: WorldLock) -> str:
    """`Game · official · AP version`, or the library apworld's label."""
    if lock.apworld is not None:
        return apworld_label(lock.apworld)
    version = f" · AP {settings.archipelago_version}" if settings.archipelago_version else ""
    return f"{lock.world} · official{version}"
