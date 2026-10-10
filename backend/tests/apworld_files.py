"""Builds .apworld files in memory for the tests."""

import io
import json
import zipfile
from typing import Any

MANIFEST: dict[str, Any] = {
    "game": "Sample Game",
    "world_version": "1.2.0",
    "minimum_ap_version": "0.6.0",
    "authors": ["Someone"],
    "compatible_version": 7,
    "version": 7,
}


def make_apworld(
    module: str = "sample_game",
    manifest: dict[str, Any] | str | None = None,
    files: dict[str, bytes] | None = None,
) -> bytes:
    """A zip with <module>/__init__.py and <module>/archipelago.json, unless `files` (names
    relative to the zip root) says otherwise. manifest=None uses MANIFEST; a str is written
    as is."""
    if files is None:
        body = manifest if isinstance(manifest, str) else json.dumps(manifest or MANIFEST)
        files = {
            f"{module}/__init__.py": b"from worlds.AutoWorld import World\n",
            f"{module}/archipelago.json": body.encode(),
        }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buffer.getvalue()
