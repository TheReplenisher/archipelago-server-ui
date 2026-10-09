import json
import os
from pathlib import Path

import pytest

from apsui_worker.main import claim_next, process_one, recover, run
from apsui_worker.protocol import (
    LOG_FILE,
    RESULT_FILE,
    SPEC_FILE,
    JobDirs,
    JobResult,
    ProtocolError,
    State,
    read_json_file,
)

from .conftest import enqueue

AP_DIR = Path("/nonexistent-archipelago")  # ping never imports Archipelago


def result(dirs: JobDirs, job_id: str) -> JobResult:
    return JobResult.from_json(read_json_file(dirs.path(State.DONE, job_id) / RESULT_FILE))


def test_ping_runs_and_publishes_a_result(dirs: JobDirs) -> None:
    job_id = enqueue(dirs, "ping")
    assert process_one(dirs, AP_DIR, max_timeout=60)
    res = result(dirs, job_id)
    assert res.status == "ok"
    assert res.output is not None and res.output["pong"] is True
    assert dirs.ids(State.QUEUE) == dirs.ids(State.RUNNING) == []
    job_dir = dirs.path(State.DONE, job_id)
    assert (job_dir / LOG_FILE).is_file()
    assert not (job_dir / "home").exists() and not (job_dir / "work").exists()


def test_jobs_run_oldest_first(dirs: JobDirs) -> None:
    first, second = enqueue(dirs, "ping"), enqueue(dirs, "ping")
    assert claim_next(dirs) == first
    assert claim_next(dirs) == second
    assert claim_next(dirs) is None


def test_expected_failure_has_code_and_no_traceback(dirs: JobDirs) -> None:
    job_id = enqueue(dirs, "ping", {"fail": True})
    process_one(dirs, AP_DIR, max_timeout=60)
    res = result(dirs, job_id)
    assert res.status == "error"
    assert res.error is not None
    assert (res.error.code, res.error.traceback) == ("requested", None)


def test_exception_is_reported_with_traceback(dirs: JobDirs) -> None:
    job_id = enqueue(dirs, "ping", {"sleep": "not a number"})
    process_one(dirs, AP_DIR, max_timeout=60)
    res = result(dirs, job_id)
    assert res.error is not None and res.error.code == "exception"
    assert res.error.message.startswith("ValueError")
    assert res.error.traceback is not None and "Traceback" in res.error.traceback


def test_unknown_job_type(dirs: JobDirs) -> None:
    job_id = enqueue(dirs, "no-such-job")
    process_one(dirs, AP_DIR, max_timeout=60)
    res = result(dirs, job_id)
    assert res.error is not None and res.error.code == "unknown-job-type"


def test_timeout_kills_the_job(dirs: JobDirs) -> None:
    job_id = enqueue(dirs, "ping", {"sleep": 30}, timeout=0.5)
    process_one(dirs, AP_DIR, max_timeout=60)
    res = result(dirs, job_id)
    assert res.status == "timeout"
    assert res.error is not None and res.error.code == "timeout"


def test_worker_caps_the_requested_timeout(dirs: JobDirs) -> None:
    job_id = enqueue(dirs, "ping", {"sleep": 30}, timeout=999)
    process_one(dirs, AP_DIR, max_timeout=0.5)
    assert result(dirs, job_id).status == "timeout"


def test_crash_without_result_is_reported(dirs: JobDirs) -> None:
    job_id = enqueue(dirs, "ping", {"crash": True})
    process_one(dirs, AP_DIR, max_timeout=60)
    res = result(dirs, job_id)
    assert res.error is not None and res.error.code == "crashed"
    assert "code 3" in res.error.message


def test_malformed_spec_is_failed_not_fatal(dirs: JobDirs) -> None:
    job_id = enqueue(dirs, "ping")
    (dirs.path(State.QUEUE, job_id) / SPEC_FILE).write_text("{not json")
    assert process_one(dirs, AP_DIR, max_timeout=60)
    res = result(dirs, job_id)
    assert res.error is not None and res.error.code == "bad-spec"


def test_restart_fails_interrupted_jobs(dirs: JobDirs) -> None:
    job_id = enqueue(dirs, "ping")
    assert claim_next(dirs) == job_id  # claimed, then the worker "died"
    recover(dirs)
    res = result(dirs, job_id)
    assert res.error is not None and res.error.code == "interrupted"
    assert res.type == "ping"


def test_run_once_drains_the_queue(dirs: JobDirs) -> None:
    ids = [enqueue(dirs, "ping") for _ in range(3)]
    run(dirs.root, AP_DIR, once=True)
    assert dirs.ids(State.DONE) == ids


def test_stray_files_in_state_folders_are_ignored(dirs: JobDirs) -> None:
    (dirs.root / State.QUEUE / "../../etc").mkdir(parents=True, exist_ok=True)
    (dirs.root / State.QUEUE / "notes.txt").write_text("hi")
    assert dirs.ids(State.QUEUE) == []
    with pytest.raises(ProtocolError):
        dirs.path(State.DONE, "../../app.db")


def test_reading_refuses_symlinks_and_oversized_files(tmp_path: Path) -> None:
    secret = tmp_path / "secret.json"
    secret.write_text(json.dumps({"password": "x"}))
    link = tmp_path / "result.json"
    os.symlink(secret, link)
    with pytest.raises(ProtocolError):
        read_json_file(link)
    big = tmp_path / "big.json"
    big.write_text(json.dumps("x" * 100))
    with pytest.raises(ProtocolError):
        read_json_file(big, max_bytes=50)


def test_heartbeat_continues_while_a_job_runs(
    dirs: JobDirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    import apsui_worker.runner

    monkeypatch.setattr(apsui_worker.runner, "HEARTBEAT_INTERVAL", 0.1)
    beats: list[float] = []
    enqueue(dirs, "ping", {"sleep": 0.6})
    job_id = claim_next(dirs)
    assert job_id is not None
    from apsui_worker.protocol import JobSpec
    from apsui_worker.runner import run_job

    job_dir = dirs.path(State.RUNNING, job_id)
    spec = JobSpec.from_json(read_json_file(job_dir / SPEC_FILE))
    run_job(job_dir, spec, AP_DIR, 60, beat=lambda: beats.append(1))
    assert len(beats) >= 3


def test_heartbeat_age(dirs: JobDirs) -> None:
    assert dirs.heartbeat_age() is None
    dirs.beat()
    age = dirs.heartbeat_age()
    assert age is not None and age < 5
