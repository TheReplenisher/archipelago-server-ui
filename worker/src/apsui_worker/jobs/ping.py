"""A job that runs no Archipelago code. Used by tests and health checks.

Params (all optional): sleep (seconds), fail (bool), crash (bool).
"""

from __future__ import annotations

import os
import platform
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apsui_worker.jobs import JobContext


def run(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    from apsui_worker.jobs import JobFailure

    time.sleep(min(float(params.get("sleep", 0)), 3600))
    if params.get("crash"):
        os._exit(3)
    if params.get("fail"):
        raise JobFailure("requested", "ping failed on request")
    return {"pong": True, "python": platform.python_version()}
