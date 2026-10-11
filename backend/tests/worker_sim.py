"""Plays the worker in tests: finishes every queued job with a canned result, by job
type, then lets the web service collect."""

import os
from typing import Any

from apsui_worker.protocol import (
    INPUT_DIR,
    RESULT_FILE,
    SPEC_FILE,
    JobError,
    JobResult,
    State,
    now,
    read_json_file,
    write_json_atomic,
)
from fastapi.testclient import TestClient

from apsui.jobs import JobQueue


def worker_finishes(
    client: TestClient, outputs: dict[str, Any], error: JobError | None = None
) -> list[dict[str, Any]]:
    """`outputs` maps a job type to its output, or to a function of the job's spec. With
    `error`, every job fails with it instead. Returns the specs, each with the names of
    its input files."""
    jobs: JobQueue = client.app.state.jobs  # type: ignore[attr-defined]
    specs = []
    for job_id in jobs.dirs.ids(State.QUEUE):
        done = jobs.dirs.path(State.DONE, job_id)
        os.rename(jobs.dirs.path(State.QUEUE, job_id), done)
        spec = read_json_file(done / SPEC_FILE)
        spec["inputs"] = sorted(p.name for p in (done / INPUT_DIR).iterdir())
        specs.append(spec)
        output = outputs.get(spec["type"])
        result = JobResult(
            id=job_id,
            type=spec["type"],
            status="error" if error else "ok",
            started_at=now(),
            finished_at=now(),
            output=None if error else output(spec) if callable(output) else output,
            error=error,
            log_tail="worker log tail" if error else "",
        )
        write_json_atomic(done / RESULT_FILE, result.to_json())
    with client.app.state.sessionmaker() as session:  # type: ignore[attr-defined]
        jobs.collect(session)
    return specs
