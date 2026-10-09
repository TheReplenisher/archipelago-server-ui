"""YAML uploads (DESIGN.md §4). The worker checks each document on its own
(validate-yaml); this module stores the file, submits the job, and then makes the checks
that need the rest of the game: names unique across the game, and the slot limit.

A pending file waits in uploads/ (web only), never in the job folder: the worker could
alter what it was given, so the accepted file is always the bytes the admin uploaded.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apsui.config import Settings
from apsui.jobs import JobQueue
from apsui.lifecycle import GameState, current_game
from apsui.models import Job, Slot, Upload

log = logging.getLogger(__name__)

MAX_YAML_BYTES = 512_000


class UploadError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# The worker's output, parsed strictly: it is untrusted.
class CheckError(BaseModel):
    code: str
    message: str
    detail: str = ""


class CheckedDocument(BaseModel):
    index: int
    empty: bool
    name: str | None = None
    quantity: int = 1
    games: list[str] = []
    error: CheckError | None = None
    warnings: list[str] = []


class YamlCheck(BaseModel):
    error: CheckError | None
    documents: list[CheckedDocument]


def pending_path(settings: Settings, upload: Upload) -> Path:
    return settings.uploads_dir / f"{upload.id}.yaml"


def accepted_path(settings: Settings, upload: Upload) -> Path:
    return settings.game_dir / "yamls" / f"{upload.id}.yaml"


def submit_yaml(
    session: Session, jobs: JobQueue, settings: Settings, filename: str, data: bytes
) -> Upload:
    game = current_game(session)
    if game.state != GameState.OPEN:
        raise UploadError("uploads-closed", "Uploads are closed for this game", 409)
    if len(data) > MAX_YAML_BYTES:
        raise UploadError("too-large", "YAML file is too large", 413)
    if not data.strip():
        raise UploadError("empty", "The file is empty")

    upload = Upload(
        game_id=game.id,
        kind="yaml",
        filename=Path(filename or "upload.yaml").name[:255],
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        status="pending",
        uploaded_at=datetime.now(UTC),
    )
    session.add(upload)
    session.flush()
    path = pending_path(settings, upload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    session.commit()

    job = jobs.submit(
        session,
        "validate-yaml",
        # Generation settings come from the settings page with #25; these are AP's defaults.
        params={"plando_options": "bosses, connections, texts", "allow_quantity": False},
        inputs={"upload.yaml": data},
    )
    upload.job_id = job.id
    session.commit()
    return upload


def finish_yaml(session: Session, job: Job, _job_dir: Path, *, settings: Settings) -> None:
    """The validate-yaml job finished: accept the file or reject it with a short reason.
    Never leaves the upload pending: that would also block locking the game."""
    upload = session.scalars(select(Upload).where(Upload.job_id == job.id)).one_or_none()
    if upload is None or upload.status != "pending":
        return
    upload.checked_at = datetime.now(UTC)
    try:
        _finish(session, upload, job, settings)
    except Exception:
        log.exception("finishing upload %s failed", upload.id)
        upload.slots.clear()
        upload.status, upload.error_code = "rejected", "store-failed"
        upload.error_message = "The file couldn't be stored; see the server log"
        pending_path(settings, upload).unlink(missing_ok=True)


def _finish(session: Session, upload: Upload, job: Job, settings: Settings) -> None:
    def reject(code: str, message: str) -> None:
        upload.status, upload.error_code, upload.error_message = "rejected", code, message
        pending_path(settings, upload).unlink(missing_ok=True)

    if job.status != "ok":
        upload.detail = job.result
        return reject("check-failed", "The file couldn't be checked; see the upload log")
    try:
        check = YamlCheck.model_validate((job.result or {}).get("output"))
    except ValidationError:
        upload.detail = job.result
        return reject("check-failed", "The file couldn't be checked; see the upload log")
    upload.detail = check.model_dump()

    if check.error:
        return reject(check.error.code, check.error.message)
    documents = [d for d in check.documents if not d.empty]
    for document in documents:
        if document.error:
            return reject(document.error.code, document.error.message)

    names = [d.name or "" for d in documents]
    keys = [name.casefold() for name in names]
    if len(set(keys)) != len(keys):
        return reject("name-duplicate", "Two slots in this file share a name")
    taken = set(
        session.scalars(
            select(Slot.name_key).where(Slot.game_id == upload.game_id, Slot.name_key.in_(keys))
        )
    )
    if taken:
        name = next(n for n, k in zip(names, keys, strict=True) if k in taken)
        return reject("name-taken", f"Slot name {name} is already taken")
    existing = session.scalar(
        select(func.count()).select_from(Slot).where(Slot.game_id == upload.game_id)
    )
    if (existing or 0) + sum(d.quantity for d in documents) > settings.max_slots:
        return reject("too-many-slots", f"This would go over the {settings.max_slots}-slot limit")

    accepted = accepted_path(settings, upload)
    accepted.parent.mkdir(parents=True, exist_ok=True)
    # uploads/ and game/ are separate volumes under Compose, so this may be a copy.
    shutil.move(pending_path(settings, upload), accepted)
    for document in documents:
        assert document.name is not None  # noqa: S101 - no error means the worker set it
        upload.slots.append(
            Slot(
                game_id=upload.game_id,
                document=document.index,
                name=document.name,
                name_key=document.name.casefold(),
                games=document.games,
            )
        )
    upload.status = "accepted"


def remove_upload(session: Session, settings: Settings, upload_id: int) -> Upload:
    game = current_game(session)
    upload = session.get(Upload, upload_id)
    if upload is None or upload.game_id != game.id:
        raise UploadError("not-found", "No such upload in the current game", 404)
    if game.state != GameState.OPEN:
        raise UploadError("uploads-closed", "Uploads are closed for this game", 409)
    if upload.status == "pending":
        raise UploadError("still-checking", "Wait until the file has been checked", 409)
    if upload.status == "accepted":
        accepted_path(settings, upload).unlink(missing_ok=True)
        upload.slots.clear()
        upload.status = "removed"
        session.commit()
    return upload


def pending_count(session: Session, game_id: int) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(Upload)
            .where(Upload.game_id == game_id, Upload.status == "pending")
        )
        or 0
    )


def summary(upload: Upload) -> dict[str, Any]:
    return {
        "id": upload.id,
        "kind": upload.kind,
        "filename": upload.filename,
        "status": upload.status,
        "error_code": upload.error_code,
        "error_message": upload.error_message,
        "uploaded_at": upload.uploaded_at,
        "checked_at": upload.checked_at,
        "slots": [slot.name for slot in upload.slots],
    }
