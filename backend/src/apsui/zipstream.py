"""Zips streamed to the browser while they are built (patch files, archives)."""

from __future__ import annotations

CHUNK = 256 * 1024


class Sink:
    """A write-only stream that hands out what was written so far: give it to
    zipfile.ZipFile and yield take() as the zip grows."""

    def __init__(self) -> None:
        self.parts: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.parts.append(bytes(data))
        return len(data)

    def flush(self) -> None:
        pass

    def take(self) -> bytes:
        data, self.parts = b"".join(self.parts), []
        return data
