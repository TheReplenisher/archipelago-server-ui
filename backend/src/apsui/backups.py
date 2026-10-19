"""Backup and restore (DESIGN.md §7, #38).

A backup is one zip in data/backups/:

- `app.db`: a consistent snapshot, taken with SQLite's own backup API while the app runs;
- `library/`: the approved apworlds; `uploads/`: files waiting for a name or the admin;
- `game/`: the current game's YAMLs, output and logs;
- `archives/`: every archived game, unless the admin leaves them out (they can be big);
- `backup.json`: what it holds, the app, database and Archipelago versions, and each
  file's size and SHA-256.

Backups are made in the background and kept until deleted; one can also be uploaded (in
chunks, so a reverse proxy's body limit doesn't matter) and then restored.

Restore puts all of that back, with the app answering 503 meanwhile. It refuses while the
server runs or a generation or worker job is under way, and takes a safety backup of the
current state first (without archives). What it keeps from now, not from the backup:
**the admin's password and logins, and the audit log** (a restore mustn't rewind the
record of who did what). Then it settles what can't be resumed: checks that were running
are rejected as interrupted, a generation that was running failed, and a game that was
Running is Generated, its server stopped. A backup from an older version is migrated; one
from a newer version is refused.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import stat
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text, update
from sqlalchemy.orm import Session

from apsui import __version__, migrate
from apsui.archives import archives_dir
from apsui.config import Settings
from apsui.lifecycle import current_game
from apsui.models import Apworld, Game, Generation, Upload

log = logging.getLogger(__name__)

FORMAT = 1
MANIFEST = "backup.json"
DB_NAME = "app.db"
CHUNK = 1024 * 1024
MAX_CHUNK = 16 * 1024 * 1024
"""The largest piece of an uploaded backup in one request."""
MAX_ENTRIES = 200_000
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}\.zip$")
GAME_PARTS = ("yamls", "output", "logs")
AGAIN = "Interrupted by a restore; upload it again"
KEPT_TABLES = ("admins", "admin_sessions", "audit_log")
"""Restore keeps these as they are now (the admin's login and the audit log)."""


class BackupError(Exception):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class BackupFile:
    name: str
    size: int
    created_at: datetime
    manifest: dict[str, Any] | None
    """None while it is being made, or if it isn't a readable backup."""


def backups_dir(settings: Settings) -> Path:
    return settings.data_dir / "backups"


def incoming_dir(settings: Settings) -> Path:
    return backups_dir(settings) / ".incoming"


def path_of(settings: Settings, name: str) -> Path:
    if not _NAME.fullmatch(name) or name.startswith("."):
        raise BackupError("not-found", "No such backup", 404)
    path = backups_dir(settings) / name
    if not path.is_file():
        raise BackupError("not-found", "No such backup", 404)
    return path


def _sources(settings: Settings, include_archives: bool) -> list[tuple[str, Path]]:
    """(name in the zip, folder) for each folder a backup holds."""
    sources = [
        ("library", settings.library_dir),
        ("uploads", settings.uploads_dir),
        *((f"game/{part}", settings.game_dir / part) for part in GAME_PARTS),
    ]
    if include_archives:
        sources.append(("archives", archives_dir(settings)))
    return sources


def _regular_files(root: Path) -> Iterator[tuple[str, Path]]:
    """(relative path, file) for every regular file under root, never through a symlink:
    the game folder is shared with the server service, which runs apworld code."""
    if not root.is_dir() or root.is_symlink():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not (Path(dirpath) / d).is_symlink())
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if stat.S_ISREG(path.lstat().st_mode) and not name.startswith(".tmp"):
                yield path.relative_to(root).as_posix(), path


def snapshot_db(engine: Engine, target: Path) -> None:
    """A consistent copy of app.db while the app keeps using it."""
    raw = engine.raw_connection()
    try:
        source = raw.driver_connection
        assert isinstance(source, sqlite3.Connection)  # noqa: S101 - SQLite only
        with sqlite3.connect(target) as copy:
            source.backup(copy)
        copy.close()
    finally:
        raw.close()


def db_revision(db_path: Path) -> str | None:
    with sqlite3.connect(db_path) as connection:
        try:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.DatabaseError:
            return None
    connection.close()
    return str(row[0]) if row else None


def create(engine: Engine, settings: Settings, include_archives: bool, label: str = "") -> Path:
    """Make a backup; returns its path. Written to a temporary name, then renamed, so a
    half-made backup is never listed as finished."""
    folder = backups_dir(settings)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    name = f"apsui-{stamp}{'-' + label if label else ''}.zip"
    final, partial = folder / name, folder / f".{name}.partial"
    db_copy = folder / f".{name}.db"
    files: dict[str, dict[str, Any]] = {}
    try:
        snapshot_db(engine, db_copy)
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as zf:
            _add(zf, DB_NAME, db_copy, files)
            for prefix, root in _sources(settings, include_archives):
                for relative, path in _regular_files(root):
                    _add(zf, f"{prefix}/{relative}", path, files)
            manifest = {
                "format": FORMAT,
                "created_at": datetime.now(UTC).isoformat(),
                "app_version": __version__,
                "archipelago_version": settings.archipelago_version or None,
                "db_revision": db_revision(db_copy),
                "archives": include_archives,
                "label": label or None,
                "files": files,
            }
            zf.writestr(MANIFEST, json.dumps(manifest, indent=1))
        partial.rename(final)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    finally:
        db_copy.unlink(missing_ok=True)
    log.info("Backup %s made (%s files)", name, len(files))
    return final


def _add(zf: zipfile.ZipFile, name: str, path: Path, files: dict[str, dict[str, Any]]) -> None:
    digest = hashlib.sha256()
    size = 0
    # Zips and apworlds don't compress further.
    stored = path.suffix in (".zip", ".apworld")
    info = zipfile.ZipInfo(name, datetime.fromtimestamp(path.stat().st_mtime).timetuple()[:6])
    info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    with path.open("rb") as src, zf.open(info, "w", force_zip64=True) as dest:
        while chunk := src.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
            dest.write(chunk)
    files[name] = {"size": size, "sha256": digest.hexdigest()}


def read_manifest(path: Path) -> dict[str, Any]:
    """The manifest of a backup file, after checking it is one this version can restore."""
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ENTRIES:
                raise BackupError("bad-backup", "This backup has too many files", 422)
            manifest = json.loads(zf.read(MANIFEST))
            names = {i.filename for i in infos}
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as exc:
        raise BackupError("bad-backup", "This isn't a backup from this app", 422) from exc
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise BackupError("bad-backup", "This isn't a backup this version can read", 422)
    files = manifest.get("files")
    if not isinstance(files, dict) or DB_NAME not in files:
        raise BackupError("bad-backup", "This backup has no database", 422)
    for name in files:
        if not isinstance(name, str) or not _safe(name) or name not in names:
            raise BackupError("bad-backup", "This backup's contents don't match it", 422)
    return manifest


def _safe(name: str) -> bool:
    parts = name.split("/")
    allowed = name == DB_NAME or parts[0] in ("library", "uploads", "game", "archives")
    return allowed and not name.startswith("/") and ".." not in parts and "" not in parts


def list_backups(settings: Settings) -> list[BackupFile]:
    folder = backups_dir(settings)
    found = []
    for path in sorted(folder.glob("*.zip"), reverse=True) if folder.is_dir() else []:
        if not path.is_file() or path.name.startswith("."):
            continue
        try:
            manifest: dict[str, Any] | None = read_manifest(path)
        except BackupError:
            manifest = None
        info = path.stat()
        created = datetime.fromtimestamp(info.st_mtime, UTC)
        found.append(BackupFile(path.name, info.st_size, created, manifest))
    return found


def making(settings: Settings) -> bool:
    folder = backups_dir(settings)
    return folder.is_dir() and any(folder.glob(".*.partial"))


def delete(settings: Settings, name: str) -> None:
    path_of(settings, name).unlink()


# ---- Uploading a backup, in pieces


def start_incoming(settings: Settings) -> str:
    folder = incoming_dir(settings)
    folder.mkdir(parents=True, exist_ok=True)
    upload_id = os.urandom(12).hex()
    (folder / upload_id).touch()
    return upload_id


def _incoming(settings: Settings, upload_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{24}", upload_id):
        raise BackupError("not-found", "No such upload", 404)
    path = incoming_dir(settings) / upload_id
    if not path.is_file():
        raise BackupError("not-found", "No such upload", 404)
    return path


def append_incoming(settings: Settings, upload_id: str, offset: int, data: bytes) -> int:
    """Add the next piece; returns the size so far. Pieces must come in order."""
    path = _incoming(settings, upload_id)
    if len(data) > MAX_CHUNK:
        raise BackupError("too-large", "A piece can be at most 16 MB", 413)
    size = path.stat().st_size
    if offset != size:
        raise BackupError("wrong-offset", f"Expected the piece at {size}", 409)
    free = shutil.disk_usage(path.parent).free
    if len(data) > free - 512 * 1024 * 1024:  # keep half a GB for everything else
        raise BackupError("disk-full", "Not enough disk space for this backup", 507)
    with path.open("ab") as out:
        out.write(data)
    return size + len(data)


def finish_incoming(settings: Settings, upload_id: str, filename: str) -> Path:
    """Check the uploaded file is a backup, and keep it with the others."""
    path = _incoming(settings, upload_id)
    try:
        read_manifest(path)
    except BackupError:
        path.unlink(missing_ok=True)
        raise
    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(filename).stem)[:80].strip("._") or "uploaded"
    name, n = f"{stem}.zip", 1
    while (backups_dir(settings) / name).exists():
        n += 1
        name = f"{stem}-{n}.zip"
    target = backups_dir(settings) / name
    path.rename(target)
    return target


# ---- Restore


def check_can_restore(session: Session, jobs_busy: bool) -> None:
    game = current_game(session)
    if game.state == "running":
        raise BackupError("server-running", "Stop the server before restoring a backup")
    if game.state == "generating":
        raise BackupError("generating", "Wait for the generation to finish")
    if jobs_busy:
        raise BackupError("worker-busy", "Wait for the worker to finish its checks")


def restore(engine: Engine, settings: Settings, name: str) -> dict[str, Any]:
    """Put a stored backup back. The caller has made the app answer 503 meanwhile and
    checked check_can_restore. Returns the backup's manifest."""
    source = path_of(settings, name)
    manifest = read_manifest(source)
    scripts = ScriptDirectory.from_config(migrate.alembic_config())
    revision = manifest.get("db_revision")
    if not isinstance(revision, str):
        raise BackupError("bad-backup", "This backup's database has no version", 422)
    if revision not in {script.revision for script in scripts.walk_revisions()}:
        raise BackupError("newer-backup", "This backup is from a newer version of the app")

    create(engine, settings, include_archives=False, label="before-restore")
    staging = settings.data_dir / ".restore"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        _extract(source, manifest, staging)
        kept = _read_kept(engine)
        _restore_db(engine, staging / DB_NAME)
        migrate.upgrade(engine)
        _write_kept(engine, kept)
        _swap(staging / "library", settings.library_dir)
        _swap(staging / "uploads", settings.uploads_dir)
        if manifest.get("archives"):
            _swap(staging / "archives", archives_dir(settings))
        for part in GAME_PARTS:  # copied, so they take the game folder's group (LXC)
            _swap(staging / "game" / part, settings.game_dir / part, copy=True)
        with Session(engine) as session:
            settle(session)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    log.warning("Restored backup %s (database revision %s)", name, revision)
    return manifest


def _extract(source: Path, manifest: dict[str, Any], staging: Path) -> None:
    """Every listed file, checked against its size and hash; nothing else."""
    with zipfile.ZipFile(source) as zf:
        for name, expected in manifest["files"].items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            with zf.open(name) as src, target.open("wb") as out:
                while chunk := src.read(CHUNK):
                    digest.update(chunk)
                    size += len(chunk)
                    out.write(chunk)
            if size != expected.get("size") or digest.hexdigest() != expected.get("sha256"):
                raise BackupError("bad-backup", f"{name} in the backup is damaged", 422)


def _read_kept(engine: Engine) -> dict[str, list[dict[str, Any]]]:
    with engine.connect() as connection:
        kept = {}
        for table in KEPT_TABLES:
            rows = connection.execute(text(f"SELECT * FROM {table}"))  # noqa: S608 - fixed names
            kept[table] = [dict(row._mapping) for row in rows]
        return kept


def _write_kept(engine: Engine, kept: dict[str, list[dict[str, Any]]]) -> None:
    with engine.begin() as connection:
        for table in reversed(KEPT_TABLES):
            connection.execute(text(f"DELETE FROM {table}"))  # noqa: S608 - fixed names
        for table in KEPT_TABLES:
            for row in kept[table]:
                columns = ", ".join(row)
                values = ", ".join(f":{c}" for c in row)
                insert = f"INSERT INTO {table} ({columns}) VALUES ({values})"  # noqa: S608
                connection.execute(text(insert), row)


def _restore_db(engine: Engine, staged: Path) -> None:
    """Copy the backup's database into the live one, in place: SQLite's backup API, so
    the app's connections stay valid."""
    engine.dispose()
    raw = engine.raw_connection()
    try:
        live = raw.driver_connection
        assert isinstance(live, sqlite3.Connection)  # noqa: S101 - SQLite only
        with sqlite3.connect(staged) as backup:
            backup.backup(live)
        backup.close()
    finally:
        raw.close()
    engine.dispose()


def _swap(new: Path, live: Path, copy: bool = False) -> None:
    """Replace a folder's contents with the backup's (empty if the backup has none). The
    folder itself stays: under Compose the game folder is a mount point. With `copy`, the
    files are written anew rather than moved: in the LXC the game folder is shared with
    the server's user through its setgid group, which a rename wouldn't give them."""
    live.mkdir(parents=True, exist_ok=True)
    for entry in os.scandir(live):
        path = Path(entry.path)
        if entry.is_dir(follow_symlinks=False):
            shutil.rmtree(path)
        else:
            path.unlink()
    if not new.is_dir():
        return
    for entry in os.scandir(new):
        if not copy:
            shutil.move(entry.path, live / entry.name)
        elif entry.is_dir(follow_symlinks=False):
            shutil.copytree(entry.path, live / entry.name, copy_function=shutil.copyfile)
        else:
            shutil.copyfile(entry.path, live / entry.name)


def settle(session: Session) -> None:
    """What was under way when the backup was made can't resume: settle it."""
    now = datetime.now(UTC)
    interrupted = {"error_code": "interrupted", "checked_at": now}
    session.execute(
        update(Upload)
        .where(Upload.status == "pending")
        .values(status="rejected", error_message=AGAIN, **interrupted)
    )
    session.execute(
        update(Apworld)
        .where(Apworld.status == "checking")
        .values(
            status="rejected",
            error_message=AGAIN,
            decided_at=now,
            **interrupted,
        )
    )
    session.execute(
        update(Generation)
        .where(Generation.status == "running")
        .values(
            status="failed",
            finished_at=now,
            error_code="interrupted",
            error_message="Interrupted by a restore",
        )
    )
    session.execute(
        update(Game).where(Game.state == "generating").values(state="locked", updated_at=now)
    )
    session.execute(
        update(Game).where(Game.state == "running").values(state="generated", updated_at=now)
    )
    session.commit()
