"""The web service's client for the server supervisor's control socket (#70)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from apsui_server.protocol import MAX_MESSAGE_BYTES, ControlError, decode, encode

TIMEOUT = 5.0


async def request(socket_path: Path, message: dict[str, Any]) -> dict[str, Any]:
    try:
        async with asyncio.timeout(TIMEOUT):
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
