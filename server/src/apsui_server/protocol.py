"""The control channel between the web service and the server supervisor.

One request per connection, one JSON object per line each way:

    → {"op": "status"}
    ← {"ok": true, "state": "stopped", ...}
    ← {"ok": false, "error": "unknown-op", "message": "..."}
"""

from __future__ import annotations

import json
from typing import Any

DEFAULT_SOCKET = "/run/apsui/control.sock"
MAX_MESSAGE_BYTES = 64_000

PROTOCOL_VERSION = 1


class ControlError(Exception):
    """The supervisor couldn't be reached, or answered with an error."""


def encode(message: dict[str, Any]) -> bytes:
    return json.dumps(message, separators=(",", ":")).encode() + b"\n"


def decode(line: bytes) -> dict[str, Any]:
    if len(line) > MAX_MESSAGE_BYTES:
        raise ControlError("message too large")
    try:
        message = json.loads(line)
    except ValueError as exc:
        raise ControlError("not JSON") from exc
    if not isinstance(message, dict):
        raise ControlError("not a JSON object")
    return message
