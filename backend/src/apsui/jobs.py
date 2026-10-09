"""The web service's side of the worker job queue (DESIGN.md §2, protocol in
apsui_worker.protocol).

submit() puts a job in the queue; collect() records finished jobs in the database and
hands their files to whoever registered for that job type, then deletes them. Everything
the worker wrote is treated as untrusted: it runs apworld code.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apsui_worker.protocol import (
    DEFAULT_TIMEOUTS,
    INPUT_DIR,
    OUTPUT_DIR,
    RESULT_FILE,
    SPEC_FILE,
    JobDirs,
    JobError,
    JobResult,
    JobSpec,
    ProtocolError,
    State,
    is_safe_file_name,
    new_job_id,
    read_json_file,
    write_json_atomic,
)
from sqlalchemy.orm import Session

from apsui.models import Job

log = logging.getLogger(__name__)

FALLBACK_TIMEOUT = 300.0

FinishedHandler = Callable[[Session, Job, Path], None]
"""Called with the finished job and its done/ directory, before the directory is deleted.
Use safe_output_files() to read what the worker produced."""


class JobQueue:
    def __init__(self, root: Path) -> None:
        self.dirs = JobDirs(root)
        self.on_finished: dict[str, FinishedHandler] = {}

    def ensure(self) -> None:
        """Create the folders and clear jobs half-assembled before a restart."""
        self.dirs.ensure()
        for job_id in self.dirs.ids(State.TMP):
            shutil.rmtree(self.dirs.path(State.TMP, job_id), ignore_errors=True)

    def submit(
        self,
        session: Session,
        job_type: str,
        params: Mapping[str, Any] | None = None,
        inputs: Mapping[str, bytes | Path] | None = None,
        timeout: float | None = None,
    ) -> Job:
        job_id = new_job_id()
        tmp = self.dirs.path(State.TMP, job_id)
        (tmp / INPUT_DIR).mkdir(parents=True)
        try:
            for name, data in (inputs or {}).items():
                if not is_safe_file_name(name):
                    raise ValueError(f"unsafe input file name: {name!r}")
                target = tmp / INPUT_DIR / name
                if isinstance(data, Path):
                    shutil.copyfile(data, target)
                else:
                    target.write_bytes(data)
            spec = JobSpec(
                id=job_id,
                type=job_type,
                params=dict(params or {}),
                timeout=timeout or DEFAULT_TIMEOUTS.get(job_type, FALLBACK_TIMEOUT),
                submitted_at=datetime.now(UTC).isoformat(),
            )
            write_json_atomic(tmp / SPEC_FILE, spec.to_json())
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

        job = Job(id=job_id, type=job_type, status="queued", submitted_at=datetime.now(UTC))
        session.add(job)
        session.commit()
        os.rename(tmp, self.dirs.path(State.QUEUE, job_id))
        return job

    def collect(self, session: Session) -> list[Job]:
        """Record what the worker has started and finished. Returns the finished jobs."""
        for job_id in self.dirs.ids(State.RUNNING):
            job = session.get(Job, job_id)
            if job is not None and job.status == "queued":
                job.status = "running"
        session.commit()

        finished = []
        for job_id in self.dirs.ids(State.DONE):
            job_dir = self.dirs.path(State.DONE, job_id)
            job = session.get(Job, job_id)
            if job is None:
                log.warning("discarding result for unknown job %s", job_id)
                shutil.rmtree(job_dir, ignore_errors=True)
                continue
            result = self._read_result(job, job_dir)
            job.status = result.status
            job.finished_at = datetime.now(UTC)
            job.error_code = result.error.code if result.error else None
            job.error_message = result.error.message if result.error else None
            job.result = result.to_json()
            handler = self.on_finished.get(job.type)
            if handler is not None:
                try:
                    handler(session, job, job_dir)
                except Exception:
                    log.exception("handling finished job %s (%s) failed", job_id, job.type)
            session.commit()
            shutil.rmtree(job_dir, ignore_errors=True)
            finished.append(job)
        return finished

    def _read_result(self, job: Job, job_dir: Path) -> JobResult:
        try:
            result = JobResult.from_json(read_json_file(job_dir / RESULT_FILE))
            if result.id != job.id or result.type != job.type:
                raise ProtocolError("result is for a different job")
            return result
        except ProtocolError as exc:
            now = datetime.now(UTC).isoformat()
            return JobResult(
                id=job.id,
                type=job.type,
                status="error",
                started_at=now,
                finished_at=now,
                error=JobError("bad-result", f"The worker's result could not be read: {exc}"),
            )


def safe_output_files(job_dir: Path) -> dict[str, Path]:
    """The regular files in a finished job's output/, by name.

    Only plain files directly in output/ are returned. Symlinks, devices, sub-folders and
    odd names are skipped: a malicious apworld could plant a symlink to app.db.
    """
    output = job_dir / OUTPUT_DIR
    files: dict[str, Path] = {}
    try:
        entries = list(os.scandir(output))
    except FileNotFoundError:
        return files
    for entry in entries:
        if not is_safe_file_name(entry.name):
            continue
        if stat.S_ISREG(entry.stat(follow_symlinks=False).st_mode):
            files[entry.name] = Path(entry.path)
    return files
