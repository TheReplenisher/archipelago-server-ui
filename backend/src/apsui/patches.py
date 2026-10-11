"""Each slot's patch or mod file from the generated output (DESIGN.md §5, patch files;
#29). Inside the output zip, worlds name them AP_<seed>_P<player>_<name>.<ext> (most use
MultiWorld.get_out_file_name_base) or AP-<seed>-P<player>-<name> (Factorio's mod and a
few others), next to the multidata (.archipelago) and the spoiler log, which are never
offered here.

The zip came from the worker, so it is untrusted: only entries that match the pattern are
listed, and only listed entries can be downloaded.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from apsui.config import Settings
from apsui.generation import output_dir
from apsui.lifecycle import GameState, current_game
from apsui.models import Generation

CHUNK = 256 * 1024


def _pattern(seed_name: str) -> re.Pattern[str]:
    return re.compile(rf"AP[_-]{re.escape(seed_name)}[_-]P(?P<player>\d+)[_-](?P<name>[^/\\]+)")


class PatchError(Exception):
    def __init__(self, code: str, message: str, status: int = 404) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Patch:
    file: str
    player: int
    slot: str
    size: int


def output_zip(session: Session, settings: Settings) -> tuple[Path, Generation]:
    """The current game's output zip, while it has one (Generated or Running)."""
    game = current_game(session)
    if game.state not in (GameState.GENERATED, GameState.RUNNING):
        raise PatchError("no-output", "The game hasn't been generated", 409)
    generation = session.scalars(
        select(Generation)
        .where(Generation.game_id == game.id, Generation.status == "ok")
        .order_by(Generation.id.desc())
    ).first()
    if generation is None or not generation.output_file:
        raise PatchError("no-output", "The game hasn't been generated", 409)
    return output_dir(settings) / generation.output_file, generation


def list_patches(session: Session, settings: Settings) -> list[Patch]:
    path, generation = output_zip(session, settings)
    players = generation.players or []
    pattern = _pattern(generation.seed_name or "")
    patches = []
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            match = pattern.fullmatch(info.filename)
            if match is None or info.is_dir():
                continue
            player = int(match["player"])
            slot = players[player - 1] if 0 < player <= len(players) else match["name"]
            patches.append(Patch(info.filename, player, slot, info.file_size))
    return sorted(patches, key=lambda p: (p.player, p.file))


def read_patch(session: Session, settings: Settings, file: str) -> Iterator[bytes]:
    """The bytes of one listed patch file, in chunks."""
    if file not in {p.file for p in list_patches(session, settings)}:
        raise PatchError("not-found", "No such patch file")
    path, _ = output_zip(session, settings)

    def chunks() -> Iterator[bytes]:
        with zipfile.ZipFile(path) as zf, zf.open(file) as member:
            while chunk := member.read(CHUNK):
                yield chunk

    return chunks()


class _Sink:
    """A write-only stream that hands out what was written so far."""

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


def all_patches(session: Session, settings: Settings) -> tuple[str, Iterator[bytes]]:
    """Every listed patch file as one zip, streamed as it is built."""
    patches = list_patches(session, settings)
    if not patches:
        raise PatchError("no-patches", "This game has no patch files")
    path, generation = output_zip(session, settings)

    def chunks() -> Iterator[bytes]:
        sink = _Sink()
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(cast("IO[bytes]", sink), "w") as out:
            for patch in patches:
                with source.open(patch.file) as src, out.open(patch.file, "w") as dest:
                    while chunk := src.read(CHUNK):
                        dest.write(chunk)
                        yield sink.take()
                yield sink.take()
        yield sink.take()

    return f"AP_{generation.seed_name}_patches.zip", chunks()
