"""The game lifecycle (DESIGN.md §3): one current game, moved between states only by the
transitions below. Every state change goes through apply(), so the rules live in one place.

    Open ──► Locked ──► Generating ──► Generated ──► Running ──► Archived
     ▲          │            │              │  ▲         │           │
     │          └─ unlock ◄──┴─ on failure ─┘  └── stop ─┘           │
     └──────────────────── new game (ARCHIVE) ◄──────────────────────┘
                              restore: Archived ──► Generated

Scheduled (Beta, #40) will slot in between Generated and Running.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from apsui.models import Game


class GameState(StrEnum):
    OPEN = "open"
    LOCKED = "locked"
    GENERATING = "generating"
    GENERATED = "generated"
    RUNNING = "running"
    ARCHIVED = "archived"


class Action(StrEnum):
    LOCK = "lock"
    UNLOCK = "unlock"
    GENERATE = "generate"
    GENERATION_SUCCEEDED = "generation-succeeded"
    GENERATION_FAILED = "generation-failed"
    DISCARD_OUTPUT = "discard-output"
    START = "start"
    STOP = "stop"
    ARCHIVE = "archive"
    RESTORE = "restore"


@dataclass(frozen=True)
class Transition:
    sources: frozenset[GameState]
    target: GameState


S = GameState
TRANSITIONS: dict[Action, Transition] = {
    Action.LOCK: Transition(frozenset({S.OPEN}), S.LOCKED),
    Action.UNLOCK: Transition(frozenset({S.LOCKED}), S.OPEN),
    Action.GENERATE: Transition(frozenset({S.LOCKED}), S.GENERATING),
    Action.GENERATION_SUCCEEDED: Transition(frozenset({S.GENERATING}), S.GENERATED),
    Action.GENERATION_FAILED: Transition(frozenset({S.GENERATING}), S.LOCKED),
    # Throw the output away to change uploads or regenerate.
    Action.DISCARD_OUTPUT: Transition(frozenset({S.GENERATED}), S.LOCKED),
    Action.START: Transition(frozenset({S.GENERATED}), S.RUNNING),
    # Stop saves and shuts down; the game stays resumable.
    Action.STOP: Transition(frozenset({S.RUNNING}), S.GENERATED),
    Action.ARCHIVE: Transition(frozenset({S.GENERATED, S.RUNNING}), S.ARCHIVED),
    Action.RESTORE: Transition(frozenset({S.ARCHIVED}), S.GENERATED),
}


class TransitionError(Exception):
    def __init__(self, game: Game, action: Action) -> None:
        super().__init__(f"Can't {action.value.replace('-', ' ')} a game that is {game.state}")
        self.code = "invalid-transition"


def allowed_actions(state: GameState) -> list[Action]:
    return [action for action, t in TRANSITIONS.items() if state in t.sources]


def current_game(session: Session) -> Game:
    """The current game, creating an Open one if there is none (first start, or after
    ARCHIVE)."""
    game = session.scalars(select(Game).where(Game.is_current.is_(True))).one_or_none()
    if game is None:
        now = datetime.now(UTC)
        game = Game(state=GameState.OPEN, is_current=True, created_at=now, updated_at=now)
        session.add(game)
        session.commit()
    return game


def apply(session: Session, game: Game, action: Action) -> Game:
    """Move a game along one transition, or raise TransitionError.

    The update is conditional on the state the game was read in, so two concurrent
    requests can't both move it."""
    transition = TRANSITIONS[action]
    source = GameState(game.state)
    if source not in transition.sources:
        raise TransitionError(game, action)
    now = datetime.now(UTC)
    values: dict[str, object] = {"state": transition.target, "updated_at": now}
    if transition.target is GameState.ARCHIVED:
        values |= {"is_current": None, "archived_at": now}
    result = session.execute(
        update(Game).where(Game.id == game.id, Game.state == source).values(**values)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        session.rollback()
        session.refresh(game)
        raise TransitionError(game, action)
    session.commit()
    session.refresh(game)
    return game
