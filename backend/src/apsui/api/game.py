from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apsui.db import get_session
from apsui.lifecycle import Action, GameState, TransitionError, allowed_actions, apply, current_game
from apsui.models import Game

router = APIRouter(prefix="/game", tags=["game"])

ADMIN_ACTIONS = (Action.LOCK, Action.UNLOCK)
"""Actions the admin triggers directly. Generate (#18), start/stop (#24) and archive (#19)
are added by their own features, since each does more than change the state."""


class GameOut(BaseModel):
    id: int
    state: GameState
    created_at: datetime
    updated_at: datetime
    actions: list[Action]
    """What the admin can do from this state."""


def game_out(game: Game) -> GameOut:
    state = GameState(game.state)
    return GameOut(
        id=game.id,
        state=state,
        created_at=game.created_at,
        updated_at=game.updated_at,
        actions=[a for a in allowed_actions(state) if a in ADMIN_ACTIONS],
    )


SessionDep = Annotated[Session, Depends(get_session)]


@router.get("")
def get_game(session: SessionDep) -> GameOut:
    return game_out(current_game(session))


def _admin_action(session: Session, action: Action) -> GameOut:
    try:
        return game_out(apply(session, current_game(session), action))
    except TransitionError as exc:
        raise HTTPException(409, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post("/lock")
def lock(session: SessionDep) -> GameOut:
    """Freeze uploads so the admin can review them before generating."""
    return _admin_action(session, Action.LOCK)


@router.post("/unlock")
def unlock(session: SessionDep) -> GameOut:
    """Re-open uploads."""
    return _admin_action(session, Action.UNLOCK)
