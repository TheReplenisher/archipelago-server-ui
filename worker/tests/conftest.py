from pathlib import Path

import pytest

from apsui_worker.protocol import (
    INPUT_DIR,
    SPEC_FILE,
    JobDirs,
    JobSpec,
    State,
    new_job_id,
    now,
    write_json_atomic,
)


@pytest.fixture
def dirs(tmp_path: Path) -> JobDirs:
    jobs = JobDirs(tmp_path / "jobs")
    jobs.ensure()
    return jobs


def enqueue(
    dirs: JobDirs, job_type: str, params: dict[str, object] | None = None, timeout: float = 30
) -> str:
    """What the web service does: assemble in tmp/, then rename into queue/."""
    job_id = new_job_id()
    tmp = dirs.path(State.TMP, job_id)
    (tmp / INPUT_DIR).mkdir(parents=True)
    spec = JobSpec(
        id=job_id, type=job_type, params=params or {}, timeout=timeout, submitted_at=now()
    )
    write_json_atomic(tmp / SPEC_FILE, spec.to_json())
    tmp.rename(dirs.path(State.QUEUE, job_id))
    return job_id
