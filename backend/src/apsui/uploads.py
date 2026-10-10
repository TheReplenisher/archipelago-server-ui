"""YAML uploads (DESIGN.md §4). The worker checks each document on its own
(validate-yaml); this module stores the file, submits the job, and then makes the checks
that need the rest of the game: names unique across the game, and the slot limit.

A pending file waits in uploads/ (web only), never in the job folder: the worker could
alter what it was given, so the accepted file is always the bytes the admin uploaded, or
those bytes with only the slot names changed when the admin renamed a slot.

A slot-name problem doesn't reject the file. It waits as needs-name until the admin
either gives new names (rename(): the YAML is edited here and checked again) or cancels
it (cancel(): rejected, so a fixed file has to be uploaded).
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apsui.config import Settings
from apsui.jobs import JobQueue
from apsui.lifecycle import GameState, current_game
from apsui.models import Game, Job, Slot, Upload
from apsui.worlds import (
    LOCKED_MESSAGE,
    WorldError,
    choose,
    conflict,
    job_inputs,
    lock,
    release_unused,
)
from apsui.yaml_names import InvalidName, check_new_name, set_names

log = logging.getLogger(__name__)

MAX_YAML_BYTES = 512_000

# Generation settings come from the settings page with #25; these are AP's defaults.
VALIDATE_PARAMS = {"plando_options": "bosses, connections, texts", "allow_quantity": False}


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
    name_raw: str | list[str] | None = None
    name_error: CheckError | None = None
    quantity: int = 1
    games: list[str] = []
    error: CheckError | None = None
    warnings: list[str] = []


class YamlCheck(BaseModel):
    error: CheckError | None
    documents: list[CheckedDocument]
    custom_games: list[str] = []


def pending_path(settings: Settings, upload: Upload) -> Path:
    return settings.uploads_dir / f"{upload.id}.yaml"


def accepted_path(settings: Settings, upload: Upload) -> Path:
    return settings.game_dir / "yamls" / f"{upload.id}.yaml"


def submit_yaml(
    session: Session,
    jobs: JobQueue,
    settings: Settings,
    filename: str,
    data: bytes,
    apworld_ids: Sequence[int] = (),
) -> Upload:
    """Store the file and have the worker check it, with the library apworlds picked for
    it and the locked custom world of every other game."""
    game = current_game(session)
    if game.state != GameState.OPEN:
        raise UploadError("uploads-closed", "Uploads are closed for this game", 409)
    if len(data) > MAX_YAML_BYTES:
        raise UploadError("too-large", "YAML file is too large", 413)
    if not data.strip():
        raise UploadError("empty", "The file is empty")
    try:
        chosen = choose(session, game.id, apworld_ids)
    except WorldError as exc:
        raise UploadError(exc.code, exc.message) from exc

    upload = Upload(
        game_id=game.id,
        kind="yaml",
        filename=Path(filename or "upload.yaml").name[:255],
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        status="pending",
        worlds={game_name: apworld.id for game_name, apworld in chosen.items()},
        uploaded_by="admin",
        uploaded_at=datetime.now(UTC),
    )
    session.add(upload)
    session.flush()
    path = pending_path(settings, upload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    session.commit()
    _check(session, jobs, settings, upload, data)
    return upload


def _check(
    session: Session, jobs: JobQueue, settings: Settings, upload: Upload, data: bytes
) -> None:
    inputs: dict[str, bytes | Path] = {"upload.yaml": data}
    inputs |= job_inputs(session, settings, upload)
    job = jobs.submit(session, "validate-yaml", params=VALIDATE_PARAMS, inputs=inputs)
    upload.job_id = job.id
    session.commit()


def finish_yaml(session: Session, job: Job, _job_dir: Path, *, settings: Settings) -> None:
    """The validate-yaml job finished: accept the file, ask for slot names, or reject it
    with a short reason. Never leaves the upload pending: that would block locking."""
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
        if document.error:  # renaming can't fix these
            return reject(document.error.code, document.error.message)
    games = {game for d in documents for game in d.games}
    not_loaded = sorted(
        g for g in games if g in (upload.worlds or {}) and g not in check.custom_games
    )
    if not_loaded:
        return reject("world-not-loaded", f"The custom apworld for {not_loaded[0]} didn't load")
    if conflict(session, upload, games):
        return reject("version-locked", LOCKED_MESSAGE)
    quantity = sum(d.quantity for d in documents)
    if slot_count(session, upload.game_id) + quantity > settings.max_slots:
        return reject("too-many-slots", f"This would go over the {settings.max_slots}-slot limit")

    problems = name_problems(session, upload.game_id, documents)
    if problems:
        upload.status, upload.name_problems = "needs-name", problems
        return

    accepted = accepted_path(settings, upload)
    accepted.parent.mkdir(parents=True, exist_ok=True)
    # uploads/ and game/ are separate volumes under Compose, so this may be a copy.
    shutil.move(pending_path(settings, upload), accepted)
    for document in documents:
        assert document.name is not None  # noqa: S101 - no name problem means it is set
        upload.slots.append(
            Slot(
                game_id=upload.game_id,
                document=document.index,
                name=document.name,
                name_key=document.name.casefold(),
                games=document.games,
            )
        )
    lock(session, upload, games)
    upload.status = "accepted"


def slot_count(session: Session, game_id: int) -> int:
    count = session.scalar(select(func.count()).select_from(Slot).where(Slot.game_id == game_id))
    return count or 0


def name_problems(
    session: Session, game_id: int, documents: list[CheckedDocument]
) -> list[dict[str, Any]]:
    """Every document whose slot name has to change, with the reason and a suggestion."""
    problems: dict[int, dict[str, Any]] = {}

    def add(doc: CheckedDocument, code: str, message: str, suggestion: str | None = None) -> None:
        problems.setdefault(
            doc.index,
            {
                "document": doc.index,
                "current": doc.name_raw,
                "code": code,
                "message": message,
                "suggestion": suggest(doc.name_raw) if suggestion is None else suggestion,
            },
        )

    for doc in documents:
        if doc.name_error:
            add(doc, doc.name_error.code, doc.name_error.message)
    named = [(d, d.name) for d in documents if d.name and d.index not in problems]
    taken = set(
        session.scalars(
            select(Slot.name_key).where(
                Slot.game_id == game_id, Slot.name_key.in_([n.casefold() for _, n in named])
            )
        )
    )
    seen: set[str] = set()
    used = taken | {name.casefold() for _, name in named}
    for doc, name in named:
        key = name.casefold()
        if key in taken or key in seen:
            free = free_variant(name, used)
            used.add(free.casefold())
            if key in taken:
                add(doc, "name-taken", f"Slot name {name} is already taken", free)
            else:
                add(doc, "name-duplicate", "Another slot in this file has this name", free)
        seen.add(key)
    return [problems[i] for i in sorted(problems)]


def free_variant(name: str, used: set[str]) -> str:
    """name2, name3, ... cut to fit 16 characters, and not already used."""
    for n in range(2, 1000):
        candidate = f"{name[: 16 - len(str(n))]}{n}"
        if candidate.casefold() not in used:
            return candidate
    return ""


def suggest(current: str | list[str] | None) -> str:
    """A starting point for the new name: the first option of a weighted name, a template
    filled in, or a long name cut to 16 characters."""
    if isinstance(current, list):
        current = current[0] if current else None
    if not current:
        return ""
    for template in ("%number%", "%NUMBER%", "%player%", "%PLAYER%"):
        current = current.replace(template, "1")
    current = current.replace("%", "").strip()
    return current[:16].strip()


def rename(
    session: Session, jobs: JobQueue, settings: Settings, upload_id: int, names: dict[int, str]
) -> Upload:
    """Give new slot names to an upload waiting for them, edit its YAML, check it again."""
    game, upload = _own_upload(session, upload_id)
    if upload.status != "needs-name":
        raise UploadError("not-waiting", "This upload isn't waiting for a name", 409)
    problems = upload.name_problems or []
    if set(names) != {p["document"] for p in problems}:
        raise UploadError("names-missing", "Give a new name for every slot listed")
    try:
        new = {index: check_new_name(name) for index, name in names.items()}
    except InvalidName as exc:
        raise UploadError("name-invalid", str(exc)) from exc

    check = YamlCheck.model_validate(upload.detail)
    kept = [d.name for d in check.documents if not d.empty and d.name and d.index not in new]
    final = kept + list(new.values())
    keys = [n.casefold() for n in final]
    duplicate = next((n for n, k in zip(final, keys, strict=True) if keys.count(k) > 1), None)
    if duplicate:
        raise UploadError("name-duplicate", f"{duplicate} is used twice in this file")
    taken = sorted(
        session.scalars(select(Slot.name).where(Slot.game_id == game.id, Slot.name_key.in_(keys)))
    )
    if taken:
        raise UploadError("name-taken", f"Slot name {taken[0]} is already taken")

    path = pending_path(settings, upload)
    try:
        edited = set_names(path.read_bytes().decode("utf-8-sig"), new).encode()
    except (ValueError, OSError) as exc:  # includes InvalidName and PyYAML's errors
        raise UploadError(
            "edit-failed", "The file couldn't be edited; cancel and re-upload"
        ) from exc
    path.write_bytes(edited)

    # Kept with the upload, so its log shows what was renamed.
    upload.name_problems = [p | {"new_name": new[p["document"]]} for p in problems]
    upload.status, upload.checked_at = "pending", None
    upload.sha256, upload.size = hashlib.sha256(edited).hexdigest(), len(edited)
    session.commit()
    _check(session, jobs, settings, upload, edited)
    return upload


def cancel(session: Session, settings: Settings, upload_id: int) -> Upload:
    """Turn down an upload waiting for a name: it is rejected, and a fixed file has to be
    uploaded instead."""
    _game, upload = _own_upload(session, upload_id)
    if upload.status != "needs-name":
        raise UploadError("not-waiting", "This upload isn't waiting for a name", 409)
    upload.status, upload.error_code = "rejected", "cancelled"
    upload.error_message = "Cancelled; upload a fixed file to try again"
    pending_path(settings, upload).unlink(missing_ok=True)
    session.commit()
    return upload


def remove_upload(session: Session, settings: Settings, upload_id: int) -> Upload:
    _game, upload = _own_upload(session, upload_id)
    if upload.status == "needs-name":
        return cancel(session, settings, upload_id)
    if upload.status == "pending":
        raise UploadError("still-checking", "Wait until the file has been checked", 409)
    if upload.status == "accepted":
        accepted_path(settings, upload).unlink(missing_ok=True)
        upload.slots.clear()
        upload.status = "removed"
        release_unused(session, upload.game_id)
        session.commit()
    return upload


def _own_upload(session: Session, upload_id: int) -> tuple[Game, Upload]:
    game = current_game(session)
    upload = session.get(Upload, upload_id)
    if upload is None or upload.game_id != game.id:
        raise UploadError("not-found", "No such upload in the current game", 404)
    if game.state != GameState.OPEN:
        raise UploadError("uploads-closed", "Uploads are closed for this game", 409)
    return game, upload


def unsettled_count(session: Session, game_id: int) -> int:
    """Uploads still being checked or waiting for a name: the game can't be locked."""
    count = session.scalar(
        select(func.count())
        .select_from(Upload)
        .where(Upload.game_id == game_id, Upload.status.in_(("pending", "needs-name")))
    )
    return count or 0


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
        "name_problems": upload.name_problems if upload.status == "needs-name" else [],
    }
