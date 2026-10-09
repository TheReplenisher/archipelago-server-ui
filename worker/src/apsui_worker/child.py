"""Runs one job, in a child process of the worker: python -m apsui_worker.child <job dir>.

Writes child-result.json into the job directory. The worker turns that into result.json,
or reports a crash if it is missing.
"""

from __future__ import annotations

import os
import sys
import traceback
from dataclasses import asdict
from pathlib import Path

from apsui_worker.protocol import (
    INPUT_DIR,
    OUTPUT_DIR,
    SPEC_FILE,
    JobError,
    JobSpec,
    read_json_file,
    write_json_atomic,
)

CHILD_RESULT_FILE = "child-result.json"


def run(job_dir: Path) -> int:
    from apsui_worker.jobs import HANDLERS, JobContext, JobFailure

    result_path = job_dir / CHILD_RESULT_FILE
    archipelago_dir = Path(os.environ.get("APSUI_ARCHIPELAGO_DIR", "/opt/archipelago"))
    try:
        spec = JobSpec.from_json(read_json_file(job_dir / SPEC_FILE))
        handler = HANDLERS.get(spec.type)
        if handler is None:
            raise JobFailure("unknown-job-type", f"Unknown job type {spec.type!r}")
        sys.path.insert(0, str(archipelago_dir))
        ctx = JobContext(
            input_dir=job_dir / INPUT_DIR,
            output_dir=job_dir / OUTPUT_DIR,
            archipelago_dir=archipelago_dir,
        )
        ctx.output_dir.mkdir(exist_ok=True)
        output = handler(spec.params, ctx)
        write_json_atomic(result_path, {"status": "ok", "output": output})
        return 0
    except JobFailure as exc:
        error = JobError(exc.code, exc.message)
    except BaseException as exc:  # report everything, including SystemExit from AP code
        message = f"{type(exc).__name__}: {exc}".strip().splitlines()[0][:500]
        error = JobError("exception", message, traceback.format_exc())
    write_json_atomic(result_path, {"status": "error", "error": asdict(error)})
    return 1


if __name__ == "__main__":
    sys.exit(run(Path(sys.argv[1])))
