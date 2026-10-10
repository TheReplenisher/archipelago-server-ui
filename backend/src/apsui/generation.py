"""Manual generation (DESIGN.md §3, #18).

The admin starts it from Locked. The worker runs Archipelago's Generate on the game's
accepted YAMLs, with the custom apworld each game is locked to (apsui.worlds). On success
the output zip goes into game/output/, where the server service finds it, and the game is
Generated. On failure the game returns to Locked, and the generation log names the
uploads AP's error points at, where it does.
"""

from __future__ import annotations

import logging
import re
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from apsui.apworlds import library_path
from apsui.config import Settings
from apsui.jobs import JobQueue, safe_output_files
from apsui.lifecycle import Action, GameState, TransitionError, apply, current_game
from apsui.models import Game, Generation, Job, Slot, Upload
from apsui.uploads import VALIDATE_PARAMS, accepted_path
from apsui.worlds import locks

log = logging.getLogger(__name__)

GENERATE_TIMEOUT = 3600
# Generation settings come from the settings page with #25; these are AP's defaults.
GENERATE_PARAMS = {"plando_options": VALIDATE_PARAMS["plando_options"], "spoiler": 3}
_OUTPUT_NAME = re.compile(r"AP_[A-Za-z0-9_-]{1,64}\.zip")
_UPLOAD_FILE = re.compile(r"\b(\d+)\.yaml\b")


class GenerationError(Exception):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class GenerateOutput(BaseModel):
    """The generate job's output, parsed strictly: it is untrusted."""

    seed_name: str
    zip: str
    players: list[str]


def output_dir(settings: Settings) -> Path:
    return settings.game_dir / "output"


def start(session: Session, jobs: JobQueue, settings: Settings) -> Generation:
    game = current_game(session)
    if game.state != GameState.LOCKED:
        raise GenerationError("not-locked", "Lock uploads before generating")
    uploads = list(
        session.scalars(
            select(Upload)
            .where(Upload.game_id == game.id, Upload.status == "accepted")
            .order_by(Upload.id)
        )
    )
    if not uploads:
        raise GenerationError("no-slots", "There are no accepted YAMLs to generate with")
    inputs: dict[str, bytes | Path] = {f"{u.id}.yaml": accepted_path(settings, u) for u in uploads}
    for lock in locks(session, game.id):
        if lock.apworld is not None:
            inputs[f"{lock.apworld.module}.apworld"] = library_path(settings, lock.apworld)

    try:
        apply(session, game, Action.GENERATE)
    except TransitionError as exc:
        raise GenerationError(exc.code, str(exc)) from exc
    generation = Generation(game_id=game.id, status="running", started_at=datetime.now(UTC))
    session.add(generation)
    session.commit()
    try:
        job = jobs.submit(
            session, "generate", params=GENERATE_PARAMS, inputs=inputs, timeout=GENERATE_TIMEOUT
        )
    except Exception:
        log.exception("submitting generation for game %s failed", game.id)
        _failed(session, game, generation, "submit-failed", "Generation couldn't be started")
        raise
    generation.job_id = job.id
    session.commit()
    return generation


def finish_generation(session: Session, job: Job, job_dir: Path, *, settings: Settings) -> None:
    """The generate job finished: store the output and mark the game Generated, or record
    the failure and return it to Locked."""
    generation = session.scalars(
        select(Generation).where(Generation.job_id == job.id)
    ).one_or_none()
    if generation is None or generation.status != "running":
        return
    game = session.get(Game, generation.game_id)
    assert game is not None  # noqa: S101 - the foreign key guarantees it
    try:
        _finish(session, game, generation, job, job_dir, settings)
    except Exception:
        log.exception("finishing generation %s failed", generation.id)
        session.rollback()
        _failed(session, game, generation, "store-failed", "The output couldn't be stored")


def _finish(
    session: Session,
    game: Game,
    generation: Generation,
    job: Job,
    job_dir: Path,
    settings: Settings,
) -> None:
    if job.status != "ok":
        result = job.result or {}
        error = result.get("error") or {}
        text = "\n".join(
            str(part)
            for part in (error.get("message"), error.get("traceback"), result.get("log_tail"))
            if part
        )
        generation.culprits = culprits(session, game.id, text)
        message = job.error_message or f"Generation {job.status}"
        _failed(session, game, generation, job.error_code or job.status, message[:500])
        return
    try:
        output = GenerateOutput.model_validate((job.result or {}).get("output"))
    except ValidationError:
        _failed(session, game, generation, "bad-output", "Generation gave an unreadable result")
        return
    source = safe_output_files(job_dir).get(output.zip)
    if not _OUTPUT_NAME.fullmatch(output.zip) or source is None or not zipfile.is_zipfile(source):
        _failed(session, game, generation, "no-output", "Generation produced no output file")
        return
    target_dir = output_dir(settings)
    shutil.rmtree(target_dir, ignore_errors=True)
    target_dir.mkdir(parents=True)
    # The job queue and game/ are separate volumes under Compose: move, not rename.
    shutil.move(source, target_dir / output.zip)
    generation.status, generation.finished_at = "ok", datetime.now(UTC)
    generation.seed_name, generation.output_file = output.seed_name, output.zip
    generation.players = output.players
    session.commit()
    apply(session, game, Action.GENERATION_SUCCEEDED)


def _failed(session: Session, game: Game, generation: Generation, code: str, message: str) -> None:
    generation.status, generation.finished_at = "failed", datetime.now(UTC)
    generation.error_code, generation.error_message = code, message
    session.commit()
    try:
        apply(session, game, Action.GENERATION_FAILED)
    except TransitionError:
        log.warning("game %s was not generating when generation %s failed", game.id, generation.id)


def culprits(session: Session, game_id: int, text: str) -> list[dict[str, Any]]:
    """The uploads AP's error points at: by the YAML's file name (<upload id>.yaml), or by
    a slot name it mentions."""
    uploads = {
        u.id: u
        for u in session.scalars(
            select(Upload).where(Upload.game_id == game_id, Upload.status == "accepted")
        )
    }
    found = {int(m) for m in _UPLOAD_FILE.findall(text)} & set(uploads)
    for slot in session.scalars(select(Slot).where(Slot.game_id == game_id)):
        if re.search(rf"(?<![\w]){re.escape(slot.name)}(?![\w])", text):
            found.add(slot.upload_id)
    return [
        {
            "upload_id": uploads[i].id,
            "filename": uploads[i].filename,
            "slots": [s.name for s in uploads[i].slots],
        }
        for i in sorted(found)
        if i in uploads
    ]


def discard_output(session: Session, settings: Settings) -> Game:
    """Throw the output away (Generated → Locked), to change uploads or generate again."""
    game = current_game(session)
    try:
        apply(session, game, Action.DISCARD_OUTPUT)
    except TransitionError as exc:
        raise GenerationError(exc.code, str(exc)) from exc
    shutil.rmtree(output_dir(settings), ignore_errors=True)
    return game


def summary(session: Session, generation: Generation) -> dict[str, Any]:
    job = session.get(Job, generation.job_id) if generation.job_id else None
    result = (job.result or {}) if job else {}
    return {
        "id": generation.id,
        "status": generation.status,
        "started_at": generation.started_at,
        "finished_at": generation.finished_at,
        "seed_name": generation.seed_name,
        "output_file": generation.output_file,
        "players": generation.players or [],
        "error_code": generation.error_code,
        "error_message": generation.error_message,
        "culprits": generation.culprits or [],
        "traceback": (result.get("error") or {}).get("traceback"),
        "log_tail": result.get("log_tail") or None,
    }
