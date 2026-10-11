"""Start / Stop / Save for the live server (DESIGN.md §3 and §5, #24). The server service's
supervisor runs MultiServer; the web service asks it over the control socket and moves
the game between Generated and Running."""

from __future__ import annotations

import shutil
from typing import Any

from apsui_server.protocol import ControlError
from sqlalchemy.orm import Session

from apsui.apworlds import library_path
from apsui.config import Settings
from apsui.lifecycle import Action, GameState, TransitionError, apply, current_game
from apsui.models import Game
from apsui.server_control import STOP_TIMEOUT, TIMEOUT, request
from apsui.worlds import locks


class HostingError(Exception):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def prepare_worlds(session: Session, settings: Settings, game: Game) -> None:
    """Put exactly the game's locked custom apworlds where the server's MultiServer loads
    custom worlds from (its XDG_DATA_HOME is game/ap). Nothing else from the library
    reaches the server service."""
    worlds = settings.game_dir / "ap" / "Archipelago" / "worlds"
    shutil.rmtree(worlds, ignore_errors=True)
    worlds.mkdir(parents=True)
    for lock in locks(session, game.id):
        if lock.apworld is not None:
            shutil.copyfile(
                library_path(settings, lock.apworld), worlds / f"{lock.apworld.module}.apworld"
            )


async def _ask(settings: Settings, op: str, seconds: float = TIMEOUT) -> dict[str, Any]:
    try:
        response = await request(settings.control_socket, {"op": op}, seconds)
    except ControlError as exc:
        raise HostingError("server-unreachable", "The server service isn't answering", 503) from exc
    if not response.get("ok"):
        code = str(response.get("error", "server-error"))
        raise HostingError(code, str(response.get("message", "The server refused")))
    return response


async def start(session: Session, settings: Settings) -> Game:
    game = current_game(session)
    if game.state != GameState.GENERATED:
        raise HostingError("not-generated", "Generate the game before starting the server")
    prepare_worlds(session, settings, game)
    await _ask(settings, "start")
    try:
        return apply(session, game, Action.START)
    except TransitionError as exc:  # someone else moved the game meanwhile
        await _ask(settings, "stop", STOP_TIMEOUT)
        raise HostingError(exc.code, str(exc)) from exc


async def stop(session: Session, settings: Settings) -> Game:
    """Save and shut down; the game stays resumable (back to Generated)."""
    game = current_game(session)
    if game.state != GameState.RUNNING:
        raise HostingError("not-running", "The server isn't running")
    await _ask(settings, "stop", STOP_TIMEOUT)
    try:
        return apply(session, game, Action.STOP)
    except TransitionError as exc:
        raise HostingError(exc.code, str(exc)) from exc


async def save(session: Session, settings: Settings) -> dict[str, Any]:
    if current_game(session).state != GameState.RUNNING:
        raise HostingError("not-running", "The server isn't running")
    return await _ask(settings, "save")
