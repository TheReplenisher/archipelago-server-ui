from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from apsui.apworlds import (
    MAX_APWORLD_BYTES,
    ApworldError,
    approve,
    detail,
    reject,
    submit_apworld,
    summary,
)
from apsui.db import get_session
from apsui.models import Apworld

router = APIRouter(tags=["apworlds"])

SessionDep = Annotated[Session, Depends(get_session)]


class ApworldOut(BaseModel):
    id: int
    filename: str
    label: str
    """`Game · custom · version · short hash`."""
    game: str | None
    world_version: str | None
    sha256: str
    short_hash: str
    size: int
    status: str
    """checking, pending (waiting for the admin), approved (in the library) or rejected."""
    replaces_builtin: str | None
    """The built-in world's version, when this apworld would replace it."""
    error_code: str | None
    error_message: str | None
    uploaded_by: str
    uploaded_at: datetime
    checked_at: datetime | None
    decided_at: datetime | None


class ApworldFile(BaseModel):
    name: str
    size: int


class ImportTestOut(BaseModel):
    loaded: bool
    games: list[str]
    replaces_builtin: str | None
    error: str | None
    detail: str | None
    """The full traceback, when it failed."""


class ApworldDetail(ApworldOut):
    module: str | None
    minimum_ap_version: str | None
    maximum_ap_version: str | None
    authors: list[str]
    manifest: dict[str, Any] | None
    files: list[ApworldFile]
    import_test: ImportTestOut | None


def _error(exc: ApworldError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message})


@router.post("/apworlds", status_code=202)
async def upload_apworld(request: Request, file: UploadFile, session: SessionDep) -> ApworldOut:
    """Upload an apworld (admin only). It is inspected at once, then import-tested by the
    worker; poll GET /api/apworlds for the result."""
    data = await file.read(MAX_APWORLD_BYTES + 1)
    try:
        apworld = submit_apworld(
            session, request.app.state.jobs, request.app.state.settings, file.filename or "", data
        )
    except ApworldError as exc:
        raise _error(exc) from exc
    return ApworldOut.model_validate(summary(apworld))


@router.get("/apworlds")
def list_apworlds(session: SessionDep) -> list[ApworldOut]:
    """Every uploaded apworld, newest first."""
    apworlds = session.scalars(select(Apworld).order_by(Apworld.id.desc()))
    return [ApworldOut.model_validate(summary(a)) for a in apworlds]


@router.get("/apworlds/{apworld_id}")
def get_apworld(apworld_id: int, session: SessionDep) -> ApworldDetail:
    """The approval screen: manifest, file list, hash, uploader and import test."""
    apworld = session.get(Apworld, apworld_id)
    if apworld is None:
        raise HTTPException(404, detail={"code": "not-found", "message": "No such apworld"})
    return ApworldDetail.model_validate(detail(apworld))


@router.post("/apworlds/{apworld_id}/approve")
def approve_apworld(request: Request, apworld_id: int, session: SessionDep) -> ApworldOut:
    """Put a pending apworld into the library."""
    try:
        apworld = approve(session, request.app.state.settings, apworld_id)
    except ApworldError as exc:
        raise _error(exc) from exc
    return ApworldOut.model_validate(summary(apworld))


@router.post("/apworlds/{apworld_id}/reject")
def reject_apworld(request: Request, apworld_id: int, session: SessionDep) -> ApworldOut:
    """Turn down a pending apworld. The record stays, as part of the upload log."""
    try:
        apworld = reject(session, request.app.state.settings, apworld_id)
    except ApworldError as exc:
        raise _error(exc) from exc
    return ApworldOut.model_validate(summary(apworld))
