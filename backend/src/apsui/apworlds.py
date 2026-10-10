"""Apworld uploads and approval (DESIGN.md §4, Apworlds).

1. Static inspection here, without running anything (apsui.apworld_inspect). A file that
   fails is rejected on the spot.
2. The worker's import test (the test-apworld job) loads it in isolation.
3. It then waits for the admin (pending), or goes straight into the library when the
   approval setting is auto. One that replaces a built-in world always waits.

The file waits in uploads/apworlds/ (web only) and, once approved, lives in the library
by hash. What goes into the library is always the uploaded bytes, never a copy back from
the worker.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from apsui.apworld_inspect import MAX_APWORLD_BYTES, InspectionError, inspect_apworld
from apsui.config import Settings
from apsui.jobs import JobQueue
from apsui.models import Apworld, Job

log = logging.getLogger(__name__)

__all__ = [
    "MAX_APWORLD_BYTES",
    "ApworldError",
    "approve",
    "detail",
    "reject",
    "submit_apworld",
    "summary",
]

SHORT_HASH = 6
LIVE = ("checking", "pending", "approved")
"""Statuses that hold the file: a second copy of the same bytes is refused."""


class ApworldError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class ImportTest(BaseModel):
    """The test-apworld job's output, parsed strictly: it is untrusted."""

    archipelago_version: str
    loaded: bool
    games: list[str]
    replaces_builtin: str | None
    error: str | None
    detail: str | None


def pending_path(settings: Settings, apworld: Apworld) -> Path:
    return settings.uploads_dir / "apworlds" / f"{apworld.id}.apworld"


def library_path(settings: Settings, apworld: Apworld) -> Path:
    return settings.library_dir / f"{apworld.sha256}.apworld"


def submit_apworld(
    session: Session, jobs: JobQueue, settings: Settings, filename: str, data: bytes
) -> Apworld:
    if len(data) > MAX_APWORLD_BYTES:
        raise ApworldError("too-large", "Apworld file is too large", 413)
    filename = Path(filename or "upload.apworld").name[:255]
    apworld = Apworld(
        filename=filename,
        sha256="",
        size=len(data),
        status="checking",
        uploaded_by="admin",
        uploaded_at=datetime.now(UTC),
    )
    try:
        found = inspect_apworld(filename, data, settings.archipelago_version)
    except InspectionError as exc:
        apworld.sha256 = hashlib.sha256(data).hexdigest()
        apworld.status, apworld.error_code, apworld.error_message = (
            "rejected",
            exc.code,
            exc.message,
        )
        apworld.checked_at = apworld.decided_at = datetime.now(UTC)
        session.add(apworld)
        session.commit()
        return apworld

    existing = session.scalars(
        select(Apworld).where(Apworld.sha256 == found.sha256, Apworld.status.in_(LIVE))
    ).first()
    if existing is not None:
        where = "in the library" if existing.status == "approved" else "waiting to be checked"
        raise ApworldError("already-uploaded", f"This apworld is already {where}", 409)

    apworld.sha256 = found.sha256
    apworld.module = found.module
    apworld.game = found.game
    apworld.world_version = found.world_version
    apworld.minimum_ap_version = found.minimum_ap_version
    apworld.maximum_ap_version = found.maximum_ap_version
    apworld.authors = found.authors
    apworld.manifest = found.manifest
    apworld.files = found.files
    session.add(apworld)
    session.flush()
    path = pending_path(settings, apworld)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    session.commit()

    job = jobs.submit(
        session,
        "test-apworld",
        params={"module": found.module, "game": found.game},
        inputs={f"{found.module}.apworld": data},
    )
    apworld.job_id = job.id
    session.commit()
    return apworld


def finish_apworld(session: Session, job: Job, _job_dir: Path, *, settings: Settings) -> None:
    """The import test finished: reject the apworld, or let it wait for the admin (or
    approve it, in auto mode). Never leaves it checking."""
    apworld = session.scalars(select(Apworld).where(Apworld.job_id == job.id)).one_or_none()
    if apworld is None or apworld.status != "checking":
        return
    apworld.checked_at = datetime.now(UTC)
    try:
        _finish(apworld, job, settings)
    except Exception:
        log.exception("finishing apworld %s failed", apworld.id)
        _reject(
            settings, apworld, "store-failed", "The file couldn't be stored; see the server log"
        )


def _finish(apworld: Apworld, job: Job, settings: Settings) -> None:
    if job.status != "ok":
        apworld.import_result = job.result
        _reject(settings, apworld, "check-failed", "The import test didn't finish")
        return
    try:
        result = ImportTest.model_validate((job.result or {}).get("output"))
    except ValidationError:
        apworld.import_result = job.result
        _reject(settings, apworld, "check-failed", "The import test gave an unreadable result")
        return
    apworld.import_result = result.model_dump()
    apworld.replaces_builtin = result.replaces_builtin
    if not result.loaded:
        message = (result.error or "unknown error")[:300]
        _reject(settings, apworld, "import-failed", f"The apworld failed to load: {message}")
        return
    apworld.status = "pending"
    if settings.apworld_approval == "auto" and result.replaces_builtin is None:
        _approve(settings, apworld)


def _reject(settings: Settings, apworld: Apworld, code: str, message: str) -> None:
    apworld.status, apworld.error_code, apworld.error_message = "rejected", code, message
    apworld.decided_at = datetime.now(UTC)
    pending_path(settings, apworld).unlink(missing_ok=True)


def _approve(settings: Settings, apworld: Apworld) -> None:
    target = library_path(settings, apworld)
    target.parent.mkdir(parents=True, exist_ok=True)
    # The library and uploads/ can be different volumes: move, not rename.
    shutil.move(pending_path(settings, apworld), target)
    apworld.status = "approved"
    apworld.decided_at = datetime.now(UTC)


def _waiting(session: Session, apworld_id: int) -> Apworld:
    apworld = session.get(Apworld, apworld_id)
    if apworld is None:
        raise ApworldError("not-found", "No such apworld", 404)
    if apworld.status != "pending":
        raise ApworldError("not-pending", "This apworld isn't waiting for approval", 409)
    return apworld


def approve(session: Session, settings: Settings, apworld_id: int) -> Apworld:
    apworld = _waiting(session, apworld_id)
    _approve(settings, apworld)
    session.commit()
    return apworld


def reject(session: Session, settings: Settings, apworld_id: int) -> Apworld:
    apworld = _waiting(session, apworld_id)
    _reject(settings, apworld, "rejected-by-admin", "Turned down by the admin")
    session.commit()
    return apworld


def label(apworld: Apworld) -> str:
    """`Game · custom · version · short hash` (DESIGN.md §4, the apworld library)."""
    version = f"v{apworld.world_version}" if apworld.world_version else "no version"
    return f"{apworld.game or apworld.filename} · custom · {version} · {short_hash(apworld)}"


def short_hash(apworld: Apworld) -> str:
    return apworld.sha256[:SHORT_HASH]


def summary(apworld: Apworld) -> dict[str, Any]:
    return {
        "id": apworld.id,
        "filename": apworld.filename,
        "label": label(apworld),
        "game": apworld.game,
        "world_version": apworld.world_version,
        "sha256": apworld.sha256,
        "short_hash": short_hash(apworld),
        "size": apworld.size,
        "status": apworld.status,
        "replaces_builtin": apworld.replaces_builtin,
        "error_code": apworld.error_code,
        "error_message": apworld.error_message,
        "uploaded_by": apworld.uploaded_by,
        "uploaded_at": apworld.uploaded_at,
        "checked_at": apworld.checked_at,
        "decided_at": apworld.decided_at,
    }


def detail(apworld: Apworld) -> dict[str, Any]:
    """Everything the approval screen shows: manifest, files, hash, uploader, import test."""
    return summary(apworld) | {
        "module": apworld.module,
        "minimum_ap_version": apworld.minimum_ap_version,
        "maximum_ap_version": apworld.maximum_ap_version,
        "authors": apworld.authors or [],
        "manifest": apworld.manifest,
        "files": apworld.files or [],
        "import_test": _import_test(apworld.import_result),
    }


def _import_test(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not result:
        return None
    if "loaded" in result:
        keys = ("loaded", "games", "replaces_builtin", "error", "detail")
        return {key: result.get(key) for key in keys}
    # The job itself failed: its error and traceback.
    error = result.get("error") or {}
    return {
        "loaded": False,
        "games": [],
        "replaces_builtin": None,
        "error": error.get("message"),
        "detail": error.get("traceback") or result.get("log_tail"),
    }
