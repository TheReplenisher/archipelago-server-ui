"""The supervisor's control socket. MultiServer itself is started and stopped in #24."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
from pathlib import Path
from typing import Any

from apsui_server.protocol import (
    DEFAULT_SOCKET,
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    ControlError,
    decode,
    encode,
)

log = logging.getLogger("apsui_server")

SOCKET_MODE = 0o660
"""Owner and group only. The web service shares the server's uid (Docker) or group (LXC)."""


class Supervisor:
    def __init__(self) -> None:
        self.state = "stopped"

    async def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        op = request.get("op")
        if op == "status":
            return {
                "ok": True,
                "protocol": PROTOCOL_VERSION,
                "state": self.state,
                "archipelago_version": os.environ.get("ARCHIPELAGO_VERSION"),
            }
        return {"ok": False, "error": "unknown-op", "message": f"Unknown operation {op!r}"}


async def serve(
    socket_path: Path, supervisor: Supervisor, ready: asyncio.Event | None = None
) -> None:
    async def connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=10)
            response = await supervisor.handle(decode(line))
        except (ControlError, TimeoutError, ValueError) as exc:
            response = {"ok": False, "error": "bad-request", "message": str(exc)}
        try:
            writer.write(encode(response))
            await writer.drain()
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    _prepare(socket_path)
    server = await asyncio.start_unix_server(
        connection, path=str(socket_path), limit=MAX_MESSAGE_BYTES
    )
    os.chmod(socket_path, SOCKET_MODE)
    log.info("control socket listening at %s", socket_path)
    if ready is not None:
        ready.set()
    try:
        async with server:
            await server.serve_forever()
    finally:
        _remove(socket_path)


# Quick local filesystem calls, kept out of the coroutines.
def _prepare(socket_path: Path) -> None:
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)  # left over from a crash


def _remove(socket_path: Path) -> None:
    socket_path.unlink(missing_ok=True)


async def run(socket_path: Path) -> None:
    task = asyncio.create_task(serve(socket_path, Supervisor()))
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    with contextlib.suppress(asyncio.CancelledError):
        await task


def main() -> None:
    parser = argparse.ArgumentParser(description="Archipelago Server UI server supervisor")
    parser.add_argument(
        "--socket", type=Path, default=Path(os.environ.get("APSUI_CONTROL_SOCKET", DEFAULT_SOCKET))
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run(args.socket))


if __name__ == "__main__":
    main()
