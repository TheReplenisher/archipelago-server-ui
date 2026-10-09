"""Runs a claimed job in a child process, with a time limit, and builds its result."""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from apsui_worker.child import CHILD_RESULT_FILE
from apsui_worker.protocol import (
    HEARTBEAT_INTERVAL,
    LOG_FILE,
    JobError,
    JobResult,
    JobSpec,
    ProtocolError,
    now,
    read_json_file,
)

LOG_TAIL_BYTES = 64_000


def run_job(
    job_dir: Path,
    spec: JobSpec,
    archipelago_dir: Path,
    max_timeout: float,
    beat: Callable[[], None] = lambda: None,
) -> JobResult:
    started = now()
    timeout = min(spec.timeout, max_timeout)
    home = job_dir / "home"
    work = job_dir / "work"
    home.mkdir(exist_ok=True)
    work.mkdir(exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "HOME": str(home),
        # AP's user folder (and so its custom worlds folder) is per job.
        "XDG_DATA_HOME": str(home),
        "APSUI_ARCHIPELAGO_DIR": str(archipelago_dir),
        "SKIP_REQUIREMENTS_UPDATE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    }
    with open(job_dir / LOG_FILE, "wb") as log:
        process = subprocess.Popen(  # noqa: S603 - fixed argv
            [sys.executable, "-m", "apsui_worker.child", str(job_dir)],
            cwd=work,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # its own process group, so a timeout kills everything
        )
        deadline = time.monotonic() + timeout
        timed_out = False
        while process.poll() is None:
            beat()  # a long generation must not look like a hung worker
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                timed_out = True
                break
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=min(HEARTBEAT_INTERVAL, remaining))

    log_tail = _tail(job_dir / LOG_FILE)
    shutil.rmtree(home, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)

    def result(**kwargs: object) -> JobResult:
        return JobResult(
            id=spec.id,
            type=spec.type,
            started_at=started,
            finished_at=now(),
            log_tail=log_tail,
            **kwargs,  # type: ignore[arg-type]
        )

    if timed_out:
        return result(
            status="timeout",
            error=JobError("timeout", f"Job took longer than {timeout:g} seconds and was stopped"),
        )
    try:
        child = read_json_file(job_dir / CHILD_RESULT_FILE)
        (job_dir / CHILD_RESULT_FILE).unlink()
        if not isinstance(child, dict):
            raise ProtocolError("child result is not an object")
        if child.get("status") == "ok":
            return result(status="ok", output=child.get("output"))
        raw = child["error"]
        return result(
            status="error",
            error=JobError(str(raw["code"]), str(raw["message"]), raw.get("traceback")),
        )
    except (ProtocolError, KeyError, TypeError):
        return result(
            status="error",
            error=JobError(
                "crashed", f"Job process exited with code {process.returncode} and no result"
            ),
        )


def _tail(path: Path) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - LOG_TAIL_BYTES))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""
