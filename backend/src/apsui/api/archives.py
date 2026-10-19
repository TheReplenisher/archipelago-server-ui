from collections.abc import Iterator
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from apsui import archives, audit
from apsui.api.game import GameOut, GenerationOut, SessionDep, game_out
from apsui.host_settings import load as load_settings
from apsui.lifecycle import GameState
from apsui.models import Game

router = APIRouter(tags=["archives"])


def _error(exc: archives.ArchiveError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message, **exc.extra})


class ArchiveOut(BaseModel):
    id: int
    created_at: datetime
    archived_at: datetime | None
    archived_from: GameState | None
    """Restore brings it back in this state (Running comes back Generated)."""
    size: int | None
    seed_name: str | None
    slots: list[str]
    worlds: list[str]


class ArchiveFileOut(BaseModel):
    path: str
    size: int


class ArchiveDetail(ArchiveOut):
    files: list[ArchiveFileOut]
    generations: list[GenerationOut]
    uploads: list[dict[str, Any]]
    """The upload log of this game, as it was when archived."""


class Retention(BaseModel):
    limit: Literal["none", "count", "size"]
    max_count: int
    max_size_mb: int
    count: int
    total_size: int


class ArchiveList(BaseModel):
    archives: list[ArchiveOut]
    retention: Retention


def _summary(request: Request, game: Game) -> ArchiveOut:
    meta = archives.read_meta(request.app.state.settings, game.id)
    return ArchiveOut(
        id=game.id,
        created_at=game.created_at,
        archived_at=game.archived_at,
        archived_from=GameState(game.archived_from) if game.archived_from else None,
        size=game.archive_size,
        seed_name=meta.get("seed_name"),
        slots=[s.get("name", "") for s in meta.get("slots", [])],
        worlds=[w.get("label", "") for w in meta.get("worlds", [])],
    )


@router.post("/game/archive")
async def archive_game(request: Request, session: SessionDep) -> GameOut:
    """ARCHIVE: end the current game (saving and stopping the server if it runs), keep
    everything in an archive, and open a new game. The UI asks "Are you sure?" first."""
    try:
        game = await archives.archive(session, request.app.state.settings)
    except archives.ArchiveError as exc:
        raise _error(exc) from exc
    return game_out(game, session)


@router.get("/archives")
def list_archives(request: Request, session: SessionDep) -> ArchiveList:
    """Every archived game, newest first, and the retention limit."""
    found = archives.list_archives(session)
    values = load_settings(session, request.app.state.settings)
    return ArchiveList(
        archives=[_summary(request, g) for g in found],
        retention=Retention(
            limit=values.archive_limit,
            max_count=values.archive_max_count,
            max_size_mb=values.archive_max_size_mb,
            count=len(found),
            total_size=sum(g.archive_size or 0 for g in found),
        ),
    )


@router.get("/archives/{game_id}")
def get_archive(game_id: int, request: Request, session: SessionDep) -> ArchiveDetail:
    """One archive, read-only: its slots, worlds, files, generation log and upload log."""
    settings = request.app.state.settings
    try:
        game = archives.get_archived(session, game_id)
    except archives.ArchiveError as exc:
        raise _error(exc) from exc
    meta = archives.read_meta(settings, game_id)
    return ArchiveDetail(
        **_summary(request, game).model_dump(),
        files=[ArchiveFileOut(path=f.path, size=f.size) for f in archives.files(settings, game_id)],
        generations=[GenerationOut.model_validate(g) for g in meta.get("generations", [])],
        uploads=meta.get("uploads", []),
    )


def _zip(name: str, chunks: Iterator[bytes]) -> StreamingResponse:
    return StreamingResponse(
        chunks,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/archives/{game_id}/download")
def download_archive(game_id: int, request: Request, session: SessionDep) -> StreamingResponse:
    """The whole archive as one zip."""
    try:
        name, chunks = archives.download(session, request.app.state.settings, game_id)
    except archives.ArchiveError as exc:
        raise _error(exc) from exc
    return _zip(name, chunks)


@router.get("/archives/{game_id}/files/{path:path}")
def download_file(game_id: int, path: str, request: Request, session: SessionDep) -> FileResponse:
    """One file of an archive, as listed. Never cached: it may be a spoiler log."""
    try:
        found = archives.open_file(session, request.app.state.settings, game_id, path)
    except archives.ArchiveError as exc:
        raise _error(exc) from exc
    return FileResponse(
        found,
        media_type="application/octet-stream",
        filename=found.name,
        headers={"Cache-Control": "no-store"},
    )


class RestoreIn(BaseModel):
    current: Literal["archive", "delete"] | None = None
    """What to do with the current game if it isn't empty. Without it, a non-empty current
    game is refused with code `current-game` and a summary of it, so the UI can ask."""


@router.post("/archives/{game_id}/restore")
async def restore_archive(
    game_id: int, body: RestoreIn, request: Request, session: SessionDep
) -> GameOut:
    """Make the archived game current again, in the state it was archived from."""
    audit.note(request, current_game=body.current)
    try:
        game = await archives.restore(session, request.app.state.settings, game_id, body.current)
    except archives.ArchiveError as exc:
        raise _error(exc) from exc
    return game_out(game, session)


@router.delete("/archives/{game_id}")
def delete_archive(game_id: int, request: Request, session: SessionDep) -> dict[str, bool]:
    """Delete an archive for good. The UI asks "Are you sure?" first."""
    try:
        archives.delete_archive(session, request.app.state.settings, game_id)
    except archives.ArchiveError as exc:
        raise _error(exc) from exc
    return {"deleted": True}
