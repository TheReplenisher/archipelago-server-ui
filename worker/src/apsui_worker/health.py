"""Container healthcheck: `python -m apsui_worker.health` exits 0 if the worker has shown
signs of life recently (it beats while idle and while a job runs)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from apsui_worker.protocol import HEARTBEAT_MAX_AGE, JobDirs


def main() -> int:
    dirs = JobDirs(Path(os.environ.get("APSUI_JOBS_DIR", "/data/jobs")))
    age = dirs.heartbeat_age()
    if age is None or age > HEARTBEAT_MAX_AGE:
        print(f"worker heartbeat is stale: {age}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
