"""Backup and restore (#38). See apsui.backups."""

import asyncio
import logging
from datetime import datetime
from typing import Annotated, Any

from apsui_worker.protocol import State
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from apsui import audit, backups
from apsui.api.game import SessionDep
from apsui.config import Settings
from apsui.jobs import JobQueue
from apsui.slots import SlotViews

log = logging.getLogger(__name__)

router = APIRouter(prefix="/backups", tags=["backups"])


def _error(exc: backups.BackupError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message})


class BackupOut(BaseModel):
    name: str
    size: int
    created_at: datetime
    readable: bool
    """False for a file that isn't a backup this version can restore."""
    archives: bool
    """It holds the archived games too."""
    label: str | None
    app_version: str | None
    archipelago_version: str | None
    files: int


class BackupList(BaseModel):
    backups: list[BackupOut]
    making: bool
    """A backup is being made right now."""
    total_size: int


def _out(found: backups.BackupFile) -> BackupOut:
    manifest = found.manifest or {}
    return BackupOut(
        name=found.name,
        size=found.size,
        created_at=found.created_at,
        readable=found.manifest is not None,
        archives=bool(manifest.get("archives")),
        label=manifest.get("label"),
        app_version=manifest.get("app_version"),
        archipelago_version=manifest.get("archipelago_version"),
        files=len(manifest.get("files") or {}),
    )


@router.get("")
def list_backups(request: Request) -> BackupList:
    settings: Settings = request.app.state.settings
    found = backups.list_backups(settings)
    return BackupList(
        backups=[_out(b) for b in found],
        making=backups.making(settings),
        total_size=sum(b.size for b in found),
    )


class CreateIn(BaseModel):
    archives: bool = True
    """Include the archived games (they can be big)."""


@router.post("", status_code=202)
async def create_backup(body: CreateIn, request: Request) -> dict[str, bool]:
    """Make a backup in the background; GET /api/backups shows it once it's done."""
    settings: Settings = request.app.state.settings
    if backups.making(settings):
        raise _error(backups.BackupError("busy", "A backup is already being made"))
    audit.note(request, archives=body.archives)
    engine = request.app.state.engine

    async def make() -> None:
        try:
            await asyncio.to_thread(backups.create, engine, settings, body.archives)
        except Exception:
            log.exception("making a backup failed")

    request.app.state.backup_task = asyncio.create_task(make())
    await asyncio.sleep(0)  # let it start, so the list says it is being made
    return {"ok": True}


@router.get("/{name}")
def download_backup(name: str, request: Request) -> FileResponse:
    try:
        path = backups.path_of(request.app.state.settings, name)
    except backups.BackupError as exc:
        raise _error(exc) from exc
    return FileResponse(path, media_type="application/zip", filename=name)


@router.delete("/{name}")
def delete_backup(name: str, request: Request) -> dict[str, bool]:
    try:
        backups.delete(request.app.state.settings, name)
    except backups.BackupError as exc:
        raise _error(exc) from exc
    return {"ok": True}


@router.post("/incoming", status_code=201)
def start_upload(request: Request) -> dict[str, str]:
    """Upload a backup file in pieces: start, PUT each piece in order, then finish."""
    return {"id": backups.start_incoming(request.app.state.settings)}


@router.put("/incoming/{upload_id}")
async def upload_piece(
    upload_id: str, request: Request, offset: Annotated[int, Query(ge=0)]
) -> dict[str, int]:
    """One piece (at most 16 MB) of the file, as the raw request body, at `offset`."""
    data = bytearray()
    async for chunk in request.stream():  # read no more than a piece can be
        data += chunk
        if len(data) > backups.MAX_CHUNK:
            raise _error(backups.BackupError("too-large", "A piece can be at most 16 MB", 413))
    try:
        size = backups.append_incoming(request.app.state.settings, upload_id, offset, bytes(data))
    except backups.BackupError as exc:
        raise _error(exc) from exc
    return {"size": size}


class FinishIn(BaseModel):
    filename: str = Field(default="uploaded.zip", max_length=255)


@router.post("/incoming/{upload_id}/finish")
def finish_upload(upload_id: str, body: FinishIn, request: Request) -> BackupOut:
    settings: Settings = request.app.state.settings
    try:
        path = backups.finish_incoming(settings, upload_id, body.filename)
    except backups.BackupError as exc:
        raise _error(exc) from exc
    audit.note(request, name=path.name)
    return next(_out(b) for b in backups.list_backups(settings) if b.name == path.name)


@router.post("/{name}/restore")
async def restore_backup(name: str, request: Request, session: SessionDep) -> dict[str, Any]:
    """Replace everything with this backup (#38): the database, library, waiting uploads,
    current game, and the archives if it has them. Keeps the admin's password, logins and
    the audit log. A safety backup of the current state is made first."""
    settings: Settings = request.app.state.settings
    jobs: JobQueue = request.app.state.jobs
    busy = bool(jobs.dirs.ids(State.QUEUE) or jobs.dirs.ids(State.RUNNING))
    audit.note(request, name=name)
    try:
        backups.check_can_restore(session, busy)
        session.close()
        request.app.state.maintenance = True
        try:
            manifest = await asyncio.to_thread(
                backups.restore, request.app.state.engine, settings, name
            )
        finally:
            request.app.state.maintenance = False
    except backups.BackupError as exc:
        raise _error(exc) from exc
    views: SlotViews = request.app.state.slot_views
    await views.reset()
    return {
        "restored": name,
        "created_at": manifest.get("created_at"),
        "archives": bool(manifest.get("archives")),
    }
