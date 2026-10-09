"""A blocking client for the control socket, and `python -m apsui_server.client status`,
which the container healthcheck runs."""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

from apsui_server.protocol import (
    DEFAULT_SOCKET,
    MAX_MESSAGE_BYTES,
    ControlError,
    decode,
    encode,
)


def request(socket_path: Path, message: dict[str, Any], timeout: float = 5) -> dict[str, Any]:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(socket_path))
            sock.sendall(encode(message))
            data = b""
            while not data.endswith(b"\n") and len(data) <= MAX_MESSAGE_BYTES:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
    except OSError as exc:
        raise ControlError(f"can't reach the server supervisor at {socket_path}: {exc}") from exc
    return decode(data)


def main() -> int:
    op = sys.argv[1] if len(sys.argv) > 1 else "status"
    path = Path(os.environ.get("APSUI_CONTROL_SOCKET", DEFAULT_SOCKET))
    try:
        response = request(path, {"op": op})
    except ControlError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(json.dumps(response))
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
