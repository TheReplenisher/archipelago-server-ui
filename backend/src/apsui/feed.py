"""The admin's server feed (DESIGN.md §5, server feed; #27): MultiServer's output, live.

The supervisor appends everything MultiServer prints to `logs/server.log` in the game
folder, which the web service shares, so the feed follows that file: the last lines
first (the scrollback), then each line as it is written. The log holds the room
password and refused logins' passwords, so the feed is admin-only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from apsui.config import Settings

SCROLLBACK_LINES = 500
SCROLLBACK_BYTES = 256 * 1024
MAX_READ_BYTES = 1024 * 1024
"""The most read in one go; a bigger burst arrives over the next few reads."""
SEEN_BYTES = 64
"""How much of what was already read is checked again, to notice a rewritten log."""


def server_log(settings: Settings) -> Path:
    return settings.game_dir / "logs" / "server.log"


def _lines(data: bytes) -> list[str]:
    return [line.decode("utf-8", "replace").rstrip("\r") for line in data.split(b"\n")]


@dataclass
class Follower:
    """Follows one log file. A line is only handed out once its newline is written."""

    path: Path
    offset: int = 0
    inode: int | None = None
    _partial: bytes = field(default=b"", repr=False)
    _seen: bytes = field(default=b"", repr=False)  # the last bytes read, still expected there

    def _stat(self) -> os.stat_result | None:
        try:
            return self.path.stat()
        except FileNotFoundError:
            return None

    def scrollback(self) -> list[str]:
        """The last lines written, and start following from there."""
        stat = self._stat()
        self.inode, self._partial, self._seen = (stat.st_ino if stat else None), b"", b""
        if stat is None:
            self.offset = 0
            return []
        start = max(0, stat.st_size - SCROLLBACK_BYTES)
        with self.path.open("rb") as f:
            f.seek(start)
            data = f.read(stat.st_size - start)
        self.offset, self._seen = start + len(data), data[-SEEN_BYTES:]
        if start > 0:  # the read began mid-line
            data = data.partition(b"\n")[2]
        complete, newline, self._partial = data.rpartition(b"\n")
        return _lines(complete)[-SCROLLBACK_LINES:] if newline else []

    def poll(self) -> tuple[bool, list[str]]:
        """(reset, lines): new lines since the last call. When the log was truncated or
        replaced (a new game's log), reset is true and lines is a fresh scrollback."""
        stat = self._stat()
        if stat is None:
            if self.inode is None:
                return False, []
            self.scrollback()  # the log was removed
            return True, []
        if stat.st_ino != self.inode or stat.st_size < self.offset:
            return True, self.scrollback()
        if stat.st_size == self.offset:
            return False, []
        with self.path.open("rb") as f:
            f.seek(self.offset - len(self._seen))
            data = f.read(len(self._seen) + min(stat.st_size - self.offset, MAX_READ_BYTES))
        if not data.startswith(self._seen):  # truncated and written again past where we were
            return True, self.scrollback()
        data = data[len(self._seen) :]
        self.offset, self._seen = self.offset + len(data), (self._seen + data)[-SEEN_BYTES:]
        complete, newline, self._partial = (self._partial + data).rpartition(b"\n")
        return False, (_lines(complete) if newline else [])
