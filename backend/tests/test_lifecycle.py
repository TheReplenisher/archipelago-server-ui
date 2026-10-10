from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apsui.db import make_engine, make_sessionmaker
from apsui.lifecycle import (
    TRANSITIONS,
    Action,
    GameState,
    TransitionError,
    allowed_actions,
    apply,
    current_game,
)
from apsui.migrate import upgrade
from apsui.models import Game

S = GameState


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    upgrade(engine)
    with make_sessionmaker(engine)() as s:
        yield s
    engine.dispose()


def walk(session: Session, *actions: Action) -> Game:
    game = current_game(session)
    for action in actions:
        game = apply(session, game, action)
    return game


def test_first_start_creates_an_open_game(session: Session) -> None:
    game = current_game(session)
    assert game.state == S.OPEN and game.is_current
    assert current_game(session).id == game.id  # and doesn't make another


def test_the_whole_happy_path(session: Session) -> None:
    game = walk(
        session,
        Action.LOCK,
        Action.GENERATE,
        Action.GENERATION_SUCCEEDED,
        Action.START,
        Action.STOP,
        Action.START,
    )
    assert game.state == S.RUNNING
    archived = apply(session, game, Action.ARCHIVE)
    assert archived.state == S.ARCHIVED
    assert archived.is_current is None and archived.archived_at is not None
    new = current_game(session)
    assert new.id != archived.id and new.state == S.OPEN  # ARCHIVE re-opens uploads


def test_failure_and_unlock_paths(session: Session) -> None:
    game = walk(session, Action.LOCK, Action.GENERATE, Action.GENERATION_FAILED)
    assert game.state == S.LOCKED
    game = walk(session, Action.UNLOCK)
    assert game.state == S.OPEN
    game = walk(session, Action.LOCK, Action.GENERATE, Action.GENERATION_SUCCEEDED)
    assert apply(session, game, Action.DISCARD_OUTPUT).state == S.LOCKED


@pytest.mark.parametrize(
    ("actions", "illegal"),
    [
        ((), Action.GENERATE),  # can't generate while uploads are open
        ((), Action.START),
        ((Action.LOCK,), Action.START),  # nothing generated yet
        ((Action.LOCK, Action.GENERATE), Action.UNLOCK),  # not mid-generation
        ((Action.LOCK, Action.GENERATE), Action.ARCHIVE),
        ((), Action.ARCHIVE),
    ],
)
def test_illegal_transitions_are_refused(
    session: Session, actions: tuple[Action, ...], illegal: Action
) -> None:
    game = walk(session, *actions)
    before = game.state
    with pytest.raises(TransitionError):
        apply(session, game, illegal)
    assert current_game(session).state == before


def test_a_stale_read_cannot_move_the_game(session: Session) -> None:
    """Two requests both read the game as Open; only the first lock wins."""
    game = current_game(session)
    with make_sessionmaker(session.get_bind())() as other:  # type: ignore[arg-type]
        stale = other.get(Game, game.id)
        assert stale is not None and stale.state == S.OPEN
        apply(session, game, Action.LOCK)
        with pytest.raises(TransitionError):
            apply(other, stale, Action.LOCK)
        assert stale.state == S.LOCKED  # refreshed to the real state


def test_only_one_current_game(session: Session) -> None:
    current_game(session)
    now = datetime.now(UTC)
    session.add(Game(state=S.OPEN, is_current=True, created_at=now, updated_at=now))
    with pytest.raises(IntegrityError):
        session.commit()


def test_every_state_is_reachable_and_has_a_way_out() -> None:
    targets = {t.target for t in TRANSITIONS.values()}
    assert set(GameState) - {S.OPEN} <= targets
    for state in GameState:
        if state is not S.ARCHIVED:  # archived games leave by restore only
            assert allowed_actions(state), state


def test_api_shows_and_moves_the_current_game(client: TestClient) -> None:
    game = client.get("/api/game").json()
    assert (game["state"], game["actions"]) == ("open", ["lock"])

    locked = client.post("/api/game/lock").json()
    assert (locked["state"], locked["actions"]) == ("locked", ["unlock", "generate"])

    refused = client.post("/api/game/lock")
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "invalid-transition"

    assert client.post("/api/game/unlock").json()["state"] == "open"
