"""The job protocol shared by the web service and the worker.

Jobs pass through a directory both services mount. Each job is one directory that moves
between state folders by atomic rename, so neither side ever sees a half-written job:

    tmp/<id>/      the web service assembles spec.json and input/
    queue/<id>/    ready; renamed here when complete
    running/<id>/  claimed by the worker (rename, so only one worker gets it)
    done/<id>/     result.json, log.txt and output/ written; renamed here when finished

The web service treats everything under done/ as untrusted: the worker runs apworld code.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

PROTOCOL_VERSION = 1

SPEC_FILE = "spec.json"
RESULT_FILE = "result.json"
LOG_FILE = "log.txt"
INPUT_DIR = "input"
OUTPUT_DIR = "output"

HEARTBEAT_FILE = "worker.heartbeat"
"""In the jobs root. The worker touches it every few seconds, also while a job runs."""
HEARTBEAT_INTERVAL = 5.0
HEARTBEAT_MAX_AGE = 30.0

MAX_RESULT_BYTES = 1_000_000
"""The web service refuses larger result files."""

DEFAULT_TIMEOUTS: dict[str, float] = {
    "ping": 60,
    "list-worlds": 300,
    "validate-yaml": 120,
    "test-apworld": 300,
}
"""Seconds. The worker also caps every job at its own maximum."""

_ID_RE = re.compile(r"^\d{8}T\d{12}-[0-9a-f]{8}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,199}$")

Status = Literal["ok", "error", "timeout"]


class State(StrEnum):
    TMP = "tmp"
    QUEUE = "queue"
    RUNNING = "running"
    DONE = "done"


class ProtocolError(ValueError):
    """A job file is missing, malformed or from another protocol version."""


def new_job_id() -> str:
    """Sortable by submission time, so the queue is first in, first out."""
    return f"{datetime.now(UTC):%Y%m%dT%H%M%S%f}-{secrets.token_hex(4)}"


def is_job_id(value: str) -> bool:
    return bool(_ID_RE.match(value))


def is_safe_file_name(name: str) -> bool:
    """A plain file name: no separators, no leading dot, nothing that could escape a folder."""
    return bool(_NAME_RE.match(name)) and name not in {".", ".."} and "/" not in name


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class JobDirs:
    root: Path

    def path(self, state: State, job_id: str) -> Path:
        if not is_job_id(job_id):
            raise ProtocolError(f"not a job id: {job_id!r}")
        return self.root / state / job_id

    def ensure(self) -> None:
        for state in State:
            (self.root / state).mkdir(parents=True, exist_ok=True)

    def beat(self) -> None:
        (self.root / HEARTBEAT_FILE).touch()

    def heartbeat_age(self) -> float | None:
        """Seconds since the worker last showed signs of life, or None if it never has."""
        try:
            mtime = (self.root / HEARTBEAT_FILE).stat().st_mtime
        except FileNotFoundError:
            return None
        return max(0.0, time.time() - mtime)

    def ids(self, state: State) -> list[str]:
        """Job ids in a state folder, oldest first. Anything else in the folder is ignored."""
        try:
            names = os.listdir(self.root / state)
        except FileNotFoundError:
            return []
        return sorted(name for name in names if is_job_id(name))


@dataclass(frozen=True)
class JobSpec:
    id: str
    type: str
    params: dict[str, Any]
    timeout: float
    submitted_at: str
    version: int = PROTOCOL_VERSION

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: object) -> JobSpec:
        if not isinstance(data, dict) or data.get("version") != PROTOCOL_VERSION:
            raise ProtocolError("unsupported job spec")
        try:
            spec = cls(
                id=str(data["id"]),
                type=str(data["type"]),
                params=dict(data["params"]),
                timeout=float(data["timeout"]),
                submitted_at=str(data["submitted_at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolError(f"malformed job spec: {exc}") from exc
        if not is_job_id(spec.id) or spec.timeout <= 0:
            raise ProtocolError("malformed job spec")
        return spec


@dataclass(frozen=True)
class JobError:
    code: str
    """Short and stable, e.g. "timeout", "exception", "unknown-job-type"."""
    message: str
    """One line, safe to show an admin."""
    traceback: str | None = None


@dataclass(frozen=True)
class JobResult:
    id: str
    type: str
    status: Status
    started_at: str
    finished_at: str
    output: dict[str, Any] | None = None
    error: JobError | None = None
    log_tail: str = ""
    version: int = PROTOCOL_VERSION

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: object) -> JobResult:
        if not isinstance(data, dict) or data.get("version") != PROTOCOL_VERSION:
            raise ProtocolError("unsupported job result")
        try:
            raw_error = data.get("error")
            error = None
            if raw_error is not None:
                error = JobError(
                    code=str(raw_error["code"]),
                    message=str(raw_error["message"]),
                    traceback=None
                    if raw_error.get("traceback") is None
                    else str(raw_error["traceback"]),
                )
            status = data["status"]
            if status not in ("ok", "error", "timeout"):
                raise ValueError(f"status {status!r}")
            output = data.get("output")
            if output is not None and not isinstance(output, dict):
                raise ValueError("output is not an object")
            return cls(
                id=str(data["id"]),
                type=str(data["type"]),
                status=status,
                started_at=str(data["started_at"]),
                finished_at=str(data["finished_at"]),
                output=output,
                error=error,
                log_tail=str(data.get("log_tail", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolError(f"malformed job result: {exc}") from exc


def write_json_atomic(path: Path, data: object) -> None:
    """Write, flush and rename, so a reader never sees a partial file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_json_file(path: Path, max_bytes: int = MAX_RESULT_BYTES) -> object:
    """Read a JSON file that something untrusted may have written.

    Refuses symlinks and anything but a regular file, and anything over max_bytes.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ProtocolError(f"can't open {path.name}: {exc.strerror}") from exc
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ProtocolError(f"{path.name} is not a regular file")
        raw = f.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ProtocolError(f"{path.name} is larger than {max_bytes} bytes")
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise ProtocolError(f"{path.name} is not valid JSON") from exc
