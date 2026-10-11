"""The web service's client for the server supervisor's control socket (#70)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from apsui_server.protocol import MAX_MESSAGE_BYTES, ControlError, decode, encode

TIMEOUT = 5.0


STOP_TIMEOUT = 60.0
"""Stop waits for MultiServer to save and exit (the supervisor allows it 30s, then 10s)."""


async def request(
    socket_path: Path, message: dict[str, Any], seconds: float = TIMEOUT
) -> dict[str, Any]:
    try:
        async with asyncio.timeout(seconds):
            reader, writer = await asyncio.open_unix_connection(
                str(socket_path), limit=MAX_MESSAGE_BYTES
            )
            try:
                writer.write(encode(message))
                await writer.drain()
                line = await reader.readline()
            finally:
                writer.close()
    except (OSError, TimeoutError) as exc:
        raise ControlError(f"can't reach the server supervisor: {exc}") from exc
    return decode(line)
