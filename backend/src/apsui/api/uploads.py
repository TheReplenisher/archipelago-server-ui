from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from apsui.config import Settings
from apsui.db import get_session
from apsui.jobs import JobQueue
from apsui.lifecycle import current_game
from apsui.models import Slot, Upload
from apsui.uploads import (
    MAX_YAML_BYTES,
    UploadError,
    cancel,
    remove_upload,
    rename,
    submit_yaml,
    summary,
)

router = APIRouter(tags=["uploads"])

SessionDep = Annotated[Session, Depends(get_session)]


class NameProblem(BaseModel):
    document: int
    """The document's position in the file (0 is the first)."""
    current: str | list[str] | None
    """What the file has: the name, or the names a weighted entry could roll."""
    code: str
    message: str
    suggestion: str


class UploadOut(BaseModel):
    id: int
    kind: str
    filename: str
    status: str
    error_code: str | None
    error_message: str | None
    uploaded_at: datetime
    checked_at: datetime | None
    slots: list[str]
    name_problems: list[NameProblem]
    """While status is needs-name: the slots that need a new name."""


class NewName(BaseModel):
    document: int
    name: str


class RenameIn(BaseModel):
    names: list[NewName]


class SlotOut(BaseModel):
    name: str
    games: list[str]
    upload_id: int


def _error(exc: UploadError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message})


@router.post("/uploads/yaml", status_code=202)
async def upload_yaml(request: Request, file: UploadFile, session: SessionDep) -> UploadOut:
    """Upload a player YAML (admin only in Alpha 1). It is checked by the worker; poll
    GET /api/uploads for the result."""
    data = await file.read(MAX_YAML_BYTES + 1)
    settings: Settings = request.app.state.settings
    jobs: JobQueue = request.app.state.jobs
    try:
        upload = submit_yaml(session, jobs, settings, file.filename or "", data)
    except UploadError as exc:
        raise _error(exc) from exc
    return UploadOut.model_validate(summary(upload))


@router.get("/uploads")
def list_uploads(session: SessionDep) -> list[UploadOut]:
    """Every upload to the current game, newest first."""
    game = current_game(session)
    uploads = session.scalars(
        select(Upload).where(Upload.game_id == game.id).order_by(Upload.id.desc())
    )
    return [UploadOut.model_validate(summary(u)) for u in uploads]


@router.delete("/uploads/{upload_id}")
def delete_upload(request: Request, upload_id: int, session: SessionDep) -> UploadOut:
    """Remove an accepted file and its slots while uploads are open. The record stays, as
    part of the upload log."""
    try:
        upload = remove_upload(session, request.app.state.settings, upload_id)
    except UploadError as exc:
        raise _error(exc) from exc
    return UploadOut.model_validate(summary(upload))


@router.post("/uploads/{upload_id}/rename", status_code=202)
def rename_upload(
    request: Request, upload_id: int, body: RenameIn, session: SessionDep
) -> UploadOut:
    """Give new slot names to an upload waiting for them. The YAML is edited (only its
    `name:` entries) and checked again; poll GET /api/uploads for the result."""
    names = {n.document: n.name for n in body.names}
    try:
        upload = rename(
            session, request.app.state.jobs, request.app.state.settings, upload_id, names
        )
    except UploadError as exc:
        raise _error(exc) from exc
    return UploadOut.model_validate(summary(upload))


@router.post("/uploads/{upload_id}/cancel")
def cancel_upload(request: Request, upload_id: int, session: SessionDep) -> UploadOut:
    """Turn down an upload waiting for a name. It is rejected; upload a fixed file."""
    try:
        upload = cancel(session, request.app.state.settings, upload_id)
    except UploadError as exc:
        raise _error(exc) from exc
    return UploadOut.model_validate(summary(upload))


@router.get("/slots")
def list_slots(session: SessionDep) -> list[SlotOut]:
    game = current_game(session)
    slots = session.scalars(select(Slot).where(Slot.game_id == game.id).order_by(Slot.id))
    return [SlotOut(name=s.name, games=s.games, upload_id=s.upload_id) for s in slots]
