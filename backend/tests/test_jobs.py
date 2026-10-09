"""The web service's side of the job queue, run end to end against the real worker loop.

The worker runs its jobs with this interpreter (`ping` needs no Archipelago).
"""

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from apsui_worker.main import process_one
from apsui_worker.protocol import RESULT_FILE, State, write_json_atomic
from sqlalchemy.orm import Session

from apsui.db import make_engine, make_sessionmaker
from apsui.jobs import JobQueue, safe_output_files
from apsui.migrate import upgrade
from apsui.models import Job

NO_AP = Path("/nonexistent-archipelago")


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    upgrade(engine)
    with make_sessionmaker(engine)() as s:
        yield s
    engine.dispose()


@pytest.fixture
def queue(tmp_path: Path) -> JobQueue:
    q = JobQueue(tmp_path / "jobs")
    q.ensure()
    return q


def work(queue: JobQueue) -> None:
    while process_one(queue.dirs, NO_AP, max_timeout=60):
        pass


def test_submit_run_collect(session: Session, queue: JobQueue) -> None:
    job = queue.submit(session, "ping", inputs={"a.txt": b"hello"})
    assert job.status == "queued"
    assert queue.dirs.ids(State.QUEUE) == [job.id]

    work(queue)
    [finished] = queue.collect(session)

    assert finished.id == job.id
    row = session.get(Job, job.id)
    assert row is not None and row.status == "ok" and row.finished_at is not None
    assert row.result is not None and row.result["output"]["pong"] is True
    assert queue.dirs.ids(State.DONE) == []  # files are cleaned up once recorded


def test_failures_are_recorded_with_detail(session: Session, queue: JobQueue) -> None:
    job = queue.submit(session, "ping", {"sleep": "x"})
    work(queue)
    queue.collect(session)
    row = session.get(Job, job.id)
    assert row is not None
    assert (row.status, row.error_code) == ("error", "exception")
    assert row.result is not None and "Traceback" in row.result["error"]["traceback"]


def test_timeouts_are_recorded(session: Session, queue: JobQueue) -> None:
    job = queue.submit(session, "ping", {"sleep": 30}, timeout=0.5)
    work(queue)
    queue.collect(session)
    row = session.get(Job, job.id)
    assert row is not None and row.status == "timeout"


def test_running_jobs_are_marked(session: Session, queue: JobQueue) -> None:
    job = queue.submit(session, "ping")
    os.rename(queue.dirs.path(State.QUEUE, job.id), queue.dirs.path(State.RUNNING, job.id))
    queue.collect(session)
    row = session.get(Job, job.id)
    assert row is not None and row.status == "running"


def test_finished_handler_gets_the_job_directory(session: Session, queue: JobQueue) -> None:
    seen: list[tuple[str, bool]] = []
    queue.on_finished["ping"] = lambda _s, job, job_dir: seen.append(
        (job.status, (job_dir / RESULT_FILE).is_file())
    )
    queue.submit(session, "ping")
    work(queue)
    queue.collect(session)
    assert seen == [("ok", True)]


def test_a_forged_or_broken_result_is_not_trusted(session: Session, queue: JobQueue) -> None:
    job = queue.submit(session, "ping")
    other = queue.submit(session, "ping")
    work(queue)
    # A compromised worker rewrites one job's result to claim it is another job.
    done = queue.dirs.path(State.DONE, job.id) / RESULT_FILE
    forged = (queue.dirs.path(State.DONE, other.id) / RESULT_FILE).read_text()
    done.write_text(forged)
    queue.collect(session)
    row = session.get(Job, job.id)
    assert row is not None and (row.status, row.error_code) == ("error", "bad-result")


def test_symlinked_result_is_refused(session: Session, queue: JobQueue, tmp_path: Path) -> None:
    job = queue.submit(session, "ping")
    work(queue)
    secret = tmp_path / "app.db"
    secret.write_text("{}")
    result = queue.dirs.path(State.DONE, job.id) / RESULT_FILE
    result.unlink()
    result.symlink_to(secret)
    queue.collect(session)
    row = session.get(Job, job.id)
    assert row is not None and row.error_code == "bad-result"


def test_safe_output_files_skips_symlinks_and_folders(tmp_path: Path) -> None:
    out = tmp_path / "job" / "output"
    (out / "sub").mkdir(parents=True)
    (out / "AP_123.zip").write_bytes(b"zip")
    (out / ".hidden").write_text("x")
    (tmp_path / "app.db").write_text("secret")
    (out / "spoiler.txt").symlink_to(tmp_path / "app.db")
    assert list(safe_output_files(tmp_path / "job")) == ["AP_123.zip"]


@pytest.mark.parametrize("name", ["../escape", "a/b", ".hidden", ""])
def test_unsafe_input_names_are_rejected(session: Session, queue: JobQueue, name: str) -> None:
    with pytest.raises(ValueError):
        queue.submit(session, "ping", inputs={name: b"x"})
    assert queue.dirs.ids(State.TMP) == [] and queue.dirs.ids(State.QUEUE) == []


def test_restart_clears_half_assembled_jobs(queue: JobQueue) -> None:
    stray = queue.dirs.path(State.TMP, "20260101T000000000000-deadbeef")
    stray.mkdir()
    write_json_atomic(stray / "spec.json", {})
    queue.ensure()
    assert queue.dirs.ids(State.TMP) == []


def test_the_web_service_never_loads_archipelago() -> None:
    import apsui.main
    import apsui.server_control  # noqa: F401

    loaded = {"worlds", "Utils", "BaseClasses", "MultiServer", "NetUtils"} & set(sys.modules)
    assert not loaded
