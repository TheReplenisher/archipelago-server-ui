from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from apsui import hosting
from apsui.db import get_session
from apsui.generation import GenerationError, discard_output, start, summary
from apsui.lifecycle import Action, GameState, TransitionError, allowed_actions, apply, current_game
from apsui.models import Game, Generation
from apsui.uploads import unsettled_count

router = APIRouter(prefix="/game", tags=["game"])

ADMIN_ACTIONS = (
    Action.LOCK,
    Action.UNLOCK,
    Action.GENERATE,
    Action.DISCARD_OUTPUT,
    Action.START,
    Action.STOP,
)
"""Actions the admin triggers directly. Archive (#19) is added by its own feature, since
it does more than change the state."""


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
    """Freeze uploads so the admin can review them before generating. Refused while a
    file is still being checked or waiting for a name, so what gets generated is settled."""
    if unsettled_count(session, current_game(session).id):
        message = "Some uploads are still being checked or need a name"
        raise HTTPException(409, detail={"code": "uploads-pending", "message": message})
    return _admin_action(session, Action.LOCK)


@router.post("/unlock")
def unlock(session: SessionDep) -> GameOut:
    """Re-open uploads."""
    return _admin_action(session, Action.UNLOCK)


class Culprit(BaseModel):
    upload_id: int
    filename: str
    slots: list[str]


class GenerationOut(BaseModel):
    id: int
    status: str
    """running, ok or failed."""
    started_at: datetime
    finished_at: datetime | None
    seed_name: str | None
    output_file: str | None
    players: list[str]
    error_code: str | None
    error_message: str | None
    culprits: list[Culprit]
    """The uploads Archipelago's error points at, where it names one."""
    traceback: str | None
    log_tail: str | None


def _generation_error(exc: GenerationError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message})


@router.post("/generate", status_code=202)
def generate(request: Request, session: SessionDep) -> GenerationOut:
    """Generate the multiworld from the accepted YAMLs (from Locked). Poll GET /api/game
    and GET /api/game/generations for the result."""
    try:
        generation = start(session, request.app.state.jobs, request.app.state.settings)
    except GenerationError as exc:
        raise _generation_error(exc) from exc
    return GenerationOut.model_validate(summary(session, generation))


@router.post("/discard-output")
def discard(request: Request, session: SessionDep) -> GameOut:
    """Throw the generated output away and return to Locked."""
    try:
        return game_out(discard_output(session, request.app.state.settings))
    except GenerationError as exc:
        raise _generation_error(exc) from exc


@router.get("/generations")
def list_generations(session: SessionDep) -> list[GenerationOut]:
    """The current game's generation log, newest first."""
    game = current_game(session)
    generations = session.scalars(
        select(Generation).where(Generation.game_id == game.id).order_by(Generation.id.desc())
    )
    return [GenerationOut.model_validate(summary(session, g)) for g in generations]


def _hosting_error(exc: hosting.HostingError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message})


@router.post("/start")
async def start_server(request: Request, session: SessionDep) -> GameOut:
    """Start the live server on the generated game (Generated → Running). It reports
    `starting` until MultiServer is up; see GET /api/server."""
    try:
        return game_out(await hosting.start(session, request.app.state.settings))
    except hosting.HostingError as exc:
        raise _hosting_error(exc) from exc


@router.post("/stop")
async def stop_server(request: Request, session: SessionDep) -> GameOut:
    """Save and shut the server down (Running → Generated); Start resumes from the save."""
    try:
        return game_out(await hosting.stop(session, request.app.state.settings))
    except hosting.HostingError as exc:
        raise _hosting_error(exc) from exc
