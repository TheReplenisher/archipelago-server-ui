"""The worker loop: claim the oldest queued job, run it, publish its result, repeat."""

from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path

from apsui_worker.protocol import (
    HEARTBEAT_INTERVAL,
    RESULT_FILE,
    SPEC_FILE,
    JobDirs,
    JobError,
    JobResult,
    JobSpec,
    ProtocolError,
    State,
    now,
    read_json_file,
    write_json_atomic,
)
from apsui_worker.runner import run_job

log = logging.getLogger("apsui_worker")


def claim_next(dirs: JobDirs) -> str | None:
    for job_id in dirs.ids(State.QUEUE):
        try:
            os.rename(dirs.path(State.QUEUE, job_id), dirs.path(State.RUNNING, job_id))
        except FileNotFoundError:  # claimed by another worker first
            continue
        return job_id
    return None


def finish(dirs: JobDirs, result: JobResult) -> None:
    write_json_atomic(dirs.path(State.RUNNING, result.id) / RESULT_FILE, result.to_json())
    os.rename(dirs.path(State.RUNNING, result.id), dirs.path(State.DONE, result.id))


def recover(dirs: JobDirs) -> None:
    """Fail jobs left in running/ by a worker that stopped mid-job."""
    for job_id in dirs.ids(State.RUNNING):
        log.warning("job %s was interrupted by a worker restart", job_id)
        finish(dirs, _failed(dirs, job_id, "interrupted", "The worker restarted during this job"))


def process_one(dirs: JobDirs, archipelago_dir: Path, max_timeout: float) -> bool:
    job_id = claim_next(dirs)
    if job_id is None:
        return False
    job_dir = dirs.path(State.RUNNING, job_id)
    try:
        spec = JobSpec.from_json(read_json_file(job_dir / SPEC_FILE))
    except ProtocolError as exc:
        finish(dirs, _failed(dirs, job_id, "bad-spec", str(exc)))
        return True
    log.info("job %s (%s) started", job_id, spec.type)
    result = run_job(job_dir, spec, archipelago_dir, max_timeout, beat=dirs.beat)
    log.info("job %s (%s) finished: %s", job_id, spec.type, result.status)
    finish(dirs, result)
    return True


def _failed(dirs: JobDirs, job_id: str, code: str, message: str) -> JobResult:
    job_type = "unknown"
    try:
        spec = read_json_file(dirs.path(State.RUNNING, job_id) / SPEC_FILE)
        if isinstance(spec, dict):
            job_type = str(spec.get("type", job_type))
    except ProtocolError:
        pass
    return JobResult(
        id=job_id,
        type=job_type,
        status="error",
        started_at=now(),
        finished_at=now(),
        error=JobError(code, message),
    )


def run(
    jobs_dir: Path,
    archipelago_dir: Path,
    *,
    poll_interval: float = 0.5,
    max_timeout: float = 3600,
    once: bool = False,
) -> None:
    dirs = JobDirs(jobs_dir)
    dirs.ensure()
    recover(dirs)
    while True:
        dirs.beat()
        worked = process_one(dirs, archipelago_dir, max_timeout)
        if once and not worked:
            return
        if not worked:
            time.sleep(min(poll_interval, HEARTBEAT_INTERVAL))


def main() -> None:
    env = os.environ.get
    parser = argparse.ArgumentParser(description="Archipelago Server UI worker")
    parser.add_argument("--jobs-dir", type=Path, default=Path(env("APSUI_JOBS_DIR", "/data/jobs")))
    parser.add_argument(
        "--archipelago-dir",
        type=Path,
        default=Path(env("APSUI_ARCHIPELAGO_DIR", "/opt/archipelago")),
    )
    parser.add_argument(
        "--poll-interval", type=float, default=float(env("APSUI_WORKER_POLL_INTERVAL", "0.5"))
    )
    parser.add_argument(
        "--max-timeout",
        type=float,
        default=float(env("APSUI_WORKER_MAX_TIMEOUT", "3600")),
        help="upper limit on any job's time limit, in seconds",
    )
    parser.add_argument("--once", action="store_true", help="exit when the queue is empty")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(
        args.jobs_dir,
        args.archipelago_dir,
        poll_interval=args.poll_interval,
        max_timeout=args.max_timeout,
        once=args.once,
    )


if __name__ == "__main__":
    main()
