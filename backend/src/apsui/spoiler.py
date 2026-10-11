"""The spoiler log from the generated output (DESIGN.md §5, spoiler log; #28). Archipelago
writes it as AP_<seed>_Spoiler.txt at the top of the output zip, unless the game was
generated without one.

The zip came from the worker, so it is untrusted: only that exact entry is read.
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy.orm import Session

from apsui.config import Settings
from apsui.patches import CHUNK, PatchError, output_zip


@dataclass(frozen=True)
class Spoiler:
    file: str
    size: int


def find_spoiler(session: Session, settings: Settings) -> Spoiler:
    path, generation = output_zip(session, settings)
    name = f"AP_{generation.seed_name}_Spoiler.txt"
    with zipfile.ZipFile(path) as zf:
        if name not in zf.namelist():
            raise PatchError("no-spoiler", "This game was generated without a spoiler log")
        return Spoiler(name, zf.getinfo(name).file_size)


def read_spoiler(session: Session, settings: Settings) -> tuple[str, Iterator[bytes]]:
    """The spoiler log's name and its bytes, in chunks."""
    spoiler = find_spoiler(session, settings)
    path, _ = output_zip(session, settings)

    def chunks() -> Iterator[bytes]:
        with zipfile.ZipFile(path) as zf, zf.open(spoiler.file) as member:
            while chunk := member.read(CHUNK):
                yield chunk

    return spoiler.file, chunks()
