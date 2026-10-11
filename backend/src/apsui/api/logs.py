from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from apsui.db import get_session
from apsui.models import Apworld, Upload
from apsui.upload_log import detail, entry

router = APIRouter(tags=["logs"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_ENTRIES = 500


class LogEntry(BaseModel):
    kind: str
    """yaml or apworld."""
    id: int
    key: str
    """`<kind>-<id>`: what an error code links to."""
    filename: str
    sha256: str
    size: int
    status: str
    error_code: str | None
    error_message: str | None
    """The short error the uploader saw."""
    uploaded_by: str
    uploaded_at: datetime
    game_id: int | None
    """The game a YAML was uploaded to; apworlds belong to the library."""


class Check(BaseModel):
    name: str
    status: Literal["ok", "failed", "warning", "waiting"]
    message: str
    detail: str | None


class JobDetail(BaseModel):
    id: str
    type: str
    status: str
    submitted_at: datetime
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    traceback: str | None
    log_tail: str | None


class LogDetail(LogEntry):
    checks: list[Check]
    job: JobDetail | None
    """The latest worker job for it, with the full error and traceback."""


@router.get("/logs/uploads")
def list_upload_log(session: SessionDep) -> list[LogEntry]:
    """Every upload, YAML and apworld, newest first (admin only)."""
    items: list[Upload | Apworld] = [
        *session.scalars(select(Upload).order_by(Upload.id.desc()).limit(MAX_ENTRIES)),
        *session.scalars(select(Apworld).order_by(Apworld.id.desc()).limit(MAX_ENTRIES)),
    ]
    items.sort(key=lambda i: i.uploaded_at, reverse=True)
    return [LogEntry.model_validate(entry(i)) for i in items[:MAX_ENTRIES]]


@router.get("/logs/uploads/{kind}/{item_id}")
def get_upload_log(
    kind: Literal["yaml", "apworld"], item_id: int, session: SessionDep
) -> LogDetail:
    """One upload: who, when, hash, every check and its result, and the worker's error."""
    item: Upload | Apworld | None = (
        session.get(Apworld, item_id) if kind == "apworld" else session.get(Upload, item_id)
    )
    if item is None:
        raise HTTPException(404, detail={"code": "not-found", "message": "No such upload"})
    return LogDetail.model_validate(detail(session, item))
