"""Static inspection of an uploaded .apworld (DESIGN.md §4, Apworlds step 1). Reads the
zip's directory and its manifest only: no code from the file runs here, or anywhere in
the web service.

The rules follow what Archipelago 0.6.8 itself does when it loads a custom world
(worlds/__init__.py, worlds/Files.py), plus limits that keep a hostile zip cheap to look
at.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import zipfile
from dataclasses import dataclass, field
from typing import Any

MAX_APWORLD_BYTES = 64 * 1024 * 1024
MAX_UNPACKED_BYTES = 256 * 1024 * 1024
MAX_ENTRIES = 5000
MAX_MANIFEST_BYTES = 64 * 1024
CONTAINER_VERSION = 7
"""The newest manifest format AP 0.6.8 understands (worlds/Files.py container_version)."""

# The file name becomes the module name, worlds.<stem>.
_MODULE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_VERSION = re.compile(r"\d+(\.\d+){0,2}")


class InspectionError(Exception):
    """The file can't be an apworld. The message is short and safe to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class Inspection:
    module: str
    """The apworld's folder and module name: worlds.<module>."""
    sha256: str
    size: int
    game: str
    world_version: str | None
    minimum_ap_version: str | None
    maximum_ap_version: str | None
    authors: list[str]
    manifest: dict[str, Any]
    files: list[dict[str, Any]] = field(default_factory=list)
    """Every entry: {"name", "size"}."""


def version_tuple(version: str) -> tuple[int, ...]:
    """Like Utils.tuplize_version: "0.6" -> (0, 6, 0)."""
    parts = [int(p) for p in version.split(".")]
    return tuple(parts + [0] * (3 - len(parts)))


def inspect_apworld(filename: str, data: bytes, ap_version: str = "") -> Inspection:
    """Check `data` is a well-formed apworld for this Archipelago, without running it.
    `ap_version` is the pinned Archipelago version; empty skips the version range check
    (the worker's import test checks it again either way)."""
    if len(data) > MAX_APWORLD_BYTES:
        raise InspectionError("too-large", "Apworld file is too large")
    if not filename.endswith(".apworld"):
        raise InspectionError("not-apworld", "The file name must end in .apworld")
    module = filename.removesuffix(".apworld")
    if not _MODULE_NAME.fullmatch(module) or module.startswith("_"):
        raise InspectionError(
            "bad-file-name", "The file name must be a Python module name, like my_game.apworld"
        )

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise InspectionError("bad-zip", "The file isn't a valid zip") from exc

    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise InspectionError("too-many-files", "The apworld has too many files")
        files = _check_entries(infos, module)
        manifest_info = _find_manifest(zf, module)
        bad = zf.testzip()
        if bad is not None:
            raise InspectionError("bad-zip", "The zip is damaged")
        manifest = _read_manifest(zf, manifest_info)

    game = manifest.get("game")
    if not isinstance(game, str) or not game.strip():
        raise InspectionError("manifest-no-game", "archipelago.json doesn't name the game")
    versions: dict[str, str | None] = {}
    for key in ("world_version", "minimum_ap_version", "maximum_ap_version"):
        value = manifest.get(key)
        if value is not None and (not isinstance(value, str) or not _VERSION.fullmatch(value)):
            raise InspectionError("manifest-bad-version", f"archipelago.json has a bad {key}")
        versions[key] = value
    compatible = manifest.get("compatible_version", 0)
    if not isinstance(compatible, int) or compatible > CONTAINER_VERSION:
        raise InspectionError(
            "manifest-too-new", "This apworld needs a newer Archipelago than the server runs"
        )
    authors = manifest.get("authors", [])
    if isinstance(authors, str):
        authors = [authors]
    if not isinstance(authors, list) or not all(isinstance(a, str) for a in authors):
        raise InspectionError("manifest-bad-authors", "archipelago.json has a bad authors list")

    if ap_version:
        current = version_tuple(ap_version)
        minimum, maximum = versions["minimum_ap_version"], versions["maximum_ap_version"]
        if minimum and version_tuple(minimum) > current:
            raise InspectionError(
                "ap-too-old", f"Needs Archipelago {minimum} or newer; the server runs {ap_version}"
            )
        if maximum and version_tuple(maximum) < current:
            raise InspectionError(
                "ap-too-new", f"Works up to Archipelago {maximum}; the server runs {ap_version}"
            )

    return Inspection(
        module=module,
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        game=game.strip(),
        world_version=versions["world_version"],
        minimum_ap_version=versions["minimum_ap_version"],
        maximum_ap_version=versions["maximum_ap_version"],
        authors=authors,
        manifest=manifest,
        files=files,
    )


def _check_entries(infos: list[zipfile.ZipInfo], module: str) -> list[dict[str, Any]]:
    files = []
    unpacked = 0
    has_init = False
    for info in infos:
        name = info.filename
        parts = name.rstrip("/").split("/")
        if name.startswith("/") or "\\" in name or ".." in parts or ":" in parts[0]:
            raise InspectionError("unsafe-path", "The zip contains an unsafe path")
        if stat.S_ISLNK(info.external_attr >> 16):
            raise InspectionError("unsafe-path", "The zip contains a symbolic link")
        if parts[0] != module and name != "archipelago.json":
            raise InspectionError(
                "bad-layout", f"Everything must be inside one folder named {module}/"
            )
        unpacked += info.file_size
        if unpacked > MAX_UNPACKED_BYTES:
            raise InspectionError("too-large", "The apworld unpacks too large")
        if info.is_dir():
            continue
        if name in (f"{module}/__init__.py", f"{module}/__init__.pyc"):
            has_init = True
        files.append({"name": name, "size": info.file_size})
    if not has_init:
        raise InspectionError("bad-layout", f"{module}/__init__.py is missing")
    return files


def _find_manifest(zf: zipfile.ZipFile, module: str) -> zipfile.ZipInfo:
    # Archipelago looks for archipelago.json at the top, then takes any file whose name
    # ends in it; the packaging tools put it inside the folder.
    for name in (f"{module}/archipelago.json", "archipelago.json"):
        try:
            return zf.getinfo(name)
        except KeyError:
            pass
    for info in zf.infolist():
        if info.filename.endswith("archipelago.json"):
            return info
    raise InspectionError("manifest-missing", "archipelago.json is missing")


def _read_manifest(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> dict[str, Any]:
    if info.file_size > MAX_MANIFEST_BYTES:
        raise InspectionError("manifest-invalid", "archipelago.json is too large")
    try:
        manifest = json.loads(zf.read(info).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise InspectionError("manifest-invalid", "archipelago.json isn't valid JSON") from exc
    if not isinstance(manifest, dict):
        raise InspectionError("manifest-invalid", "archipelago.json isn't a JSON object")
    return manifest
