"""Job handlers, by job type.

A handler takes the job's params and a context, returns a JSON-serialisable dict, and
raises JobFailure for an expected, user-facing failure. Any other exception is reported
with its traceback. Handlers import Archipelago inside the function, never at module
level, so the registry can be loaded without AP.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apsui_worker.jobs import generate, list_worlds, ping, test_apworld, validate_yaml


@dataclass(frozen=True)
class JobContext:
    input_dir: Path
    output_dir: Path
    archipelago_dir: Path


class JobFailure(Exception):
    """An expected failure, reported as error code + one-line message (no traceback)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


Handler = Callable[[dict[str, Any], JobContext], dict[str, Any]]

HANDLERS: dict[str, Handler] = {
    "ping": ping.run,
    "list-worlds": list_worlds.run,
    "validate-yaml": validate_yaml.run,
    "test-apworld": test_apworld.run,
    "generate": generate.run,
}
