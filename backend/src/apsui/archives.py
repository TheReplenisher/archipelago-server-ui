"""Archives (DESIGN.md §3, #19).

ARCHIVE ends the current game: the server is saved and stopped, the game's files move to
archives/<game id>/, and a new Open game becomes current. An archive holds the accepted
YAMLs, the output (multidata zip with its spoiler log, the save file, the console's
names), the server log, the apworlds the game was locked to, and archive.json: the slots,
worlds, generation log and upload log, so a downloaded archive stands on its own.

Restore brings an archive back as the current game, in the state it was archived from
(Running comes back Generated). The current game has to be empty first; otherwise the
admin chooses to archive it or delete it. Retention deletes the oldest archives after each
ARCHIVE, by count or by total size (the settings page).

The game folder is shared with the server service, which runs apworld code, so only
regular files are copied out of it, never through a symlink.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import stat
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Literal, cast

from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from apsui import host_settings, hosting, upload_log
from apsui.apworlds import library_path
from apsui.config import Settings
from apsui.generation import summary as generation_summary
from apsui.lifecycle import Action, GameState, TransitionError, apply, current_game
from apsui.models import Game, Generation, Job, Slot, Upload, WorldLock
from apsui.uploads import unsettled_count
from apsui.worlds import label as world_label
from apsui.worlds import locks
from apsui.zipstream import CHUNK, Sink

log = logging.getLogger(__name__)

FORMAT = 1
META_FILE = "archive.json"
GAME_PARTS = ("yamls", "output", "logs")
"""What is kept from the game folder. ap/ (the server's worlds and host.yaml) is rebuilt at
every start."""
APWORLDS = "apworlds"
YAMLS = "yamls"
_UNSAFE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')


class ArchiveError(Exception):
    def __init__(
        self, code: str, message: str, status: int = 409, extra: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra or {}


def archives_dir(settings: Settings) -> Path:
    return settings.data_dir / "archives"


def archive_path(settings: Settings, game_id: int) -> Path:
    return archives_dir(settings) / str(game_id)


def is_empty(session: Session, game: Game) -> bool:
    """Nothing was ever uploaded to it or generated: there is nothing to keep."""
    uploads = session.scalar(select(func.count()).where(Upload.game_id == game.id))
    generations = session.scalar(select(func.count()).where(Generation.game_id == game.id))
    return not uploads and not generations


def _check_settled(session: Session, game: Game) -> None:
    if game.state == GameState.GENERATING:
        raise ArchiveError("generating", "Wait for the generation to finish")
    if unsettled_count(session, game.id):
        raise ArchiveError("uploads-pending", "Some uploads are still being checked or need a name")


async def _stop_server(session: Session, settings: Settings, game: Game) -> Game:
    if game.state != GameState.RUNNING:
        return game
    try:
        return await hosting.stop(session, settings)
    except hosting.HostingError as exc:
        raise ArchiveError(exc.code, exc.message, exc.status) from exc


async def archive(session: Session, settings: Settings, keep: frozenset[int] = frozenset()) -> Game:
    """ARCHIVE the current game; returns the new, empty current game. Archives in `keep`
    are spared by retention."""
    game = current_game(session)
    _check_settled(session, game)
    if is_empty(session, game):
        raise ArchiveError("nothing-to-archive", "This game has no uploads to archive")
    game = await _stop_server(session, settings, game)
    archived_from = GameState(game.state)

    root = archives_dir(settings)
    tmp = root / f".tmp-{game.id}"
    final = archive_path(settings, game.id)
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        yaml_files = yaml_names(session, game)
        for part in GAME_PARTS:
            if part == YAMLS:
                _copy_yamls(settings.game_dir / YAMLS, tmp / YAMLS, yaml_files)
            else:
                _copy_files(settings.game_dir / part, tmp / part)
        for lock in locks(session, game.id):
            if lock.apworld is not None:
                source = library_path(settings, lock.apworld)
                _copy_files(source, tmp / APWORLDS / f"{lock.apworld.module}.apworld")
        meta = _meta(session, settings, game, archived_from) | {"yaml_files": yaml_files}
        (tmp / META_FILE).write_text(json.dumps(meta, indent=1), encoding="utf-8")
        size = _size(tmp)
        shutil.rmtree(final, ignore_errors=True)  # left by an interrupted restore
        tmp.rename(final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    game.archived_from, game.archive_size = archived_from, size
    try:
        apply(session, game, Action.ARCHIVE)
    except TransitionError as exc:
        shutil.rmtree(final, ignore_errors=True)
        raise ArchiveError(exc.code, str(exc)) from exc
    _clear_game_dir(settings)
    log.info("Archived game %s (%s bytes)", game.id, size)
    enforce_retention(session, settings, keep | {game.id})
    return current_game(session)


async def delete_current(session: Session, settings: Settings) -> Game:
    """Delete the current game and everything in it; returns the new, empty current game."""
    game = current_game(session)
    _check_settled(session, game)
    game = await _stop_server(session, settings, game)
    _delete_rows(session, game)
    session.commit()
    _clear_game_dir(settings)
    log.info("Deleted the current game %s", game.id)
    return current_game(session)


def delete_archive(session: Session, settings: Settings, game_id: int) -> None:
    game = get_archived(session, game_id)
    shutil.rmtree(archive_path(settings, game.id), ignore_errors=True)
    _delete_rows(session, game)
    session.commit()
    log.info("Deleted archive %s", game_id)


async def restore(
    session: Session,
    settings: Settings,
    game_id: int,
    current: Literal["archive", "delete"] | None = None,
) -> Game:
    """Make an archived game current again. A current game with anything in it is first
    archived or deleted, as the admin chose; without a choice, nothing changes."""
    restoring = get_archived(session, game_id)
    source = archive_path(settings, game_id)
    if not source.is_dir():
        raise ArchiveError("archive-missing", "This archive's files are missing", 410)
    now = current_game(session)
    if now.state == GameState.GENERATING:
        raise ArchiveError("generating", "Wait for the generation to finish")
    if not is_empty(session, now):
        if current is None:
            raise ArchiveError(
                "current-game",
                "Archive or delete the current game first",
                extra={"current": _current_summary(session, now)},
            )
        if current == "archive":
            await archive(session, settings, keep=frozenset({game_id}))
        else:
            await delete_current(session, settings)
        now = current_game(session)

    target = {GameState.OPEN: GameState.OPEN, GameState.LOCKED: GameState.LOCKED}.get(
        GameState(restoring.archived_from or GameState.GENERATED), GameState.GENERATED
    )
    _clear_game_dir(settings)
    try:
        for part in GAME_PARTS:
            if part == YAMLS:
                _restore_yamls(source / YAMLS, settings.game_dir / YAMLS, _yaml_files(source))
            else:
                _copy_files(source / part, settings.game_dir / part)
        _restore_library(session, settings, restoring, source)
        session.delete(now)  # the empty game it replaces
        session.flush()
        apply(session, restoring, Action.RESTORE, target=target)
    except BaseException:
        session.rollback()
        _clear_game_dir(settings)
        raise
    restoring.archive_size = None
    session.commit()
    shutil.rmtree(source, ignore_errors=True)
    log.info("Restored game %s as %s", game_id, target)
    return restoring


def enforce_retention(session: Session, settings: Settings, keep: frozenset[int]) -> list[int]:
    """Delete the oldest archives, except those in `keep`, until the rest fit the limit."""
    values = host_settings.load(session, settings)
    if values.archive_limit == "none":
        return []
    archived = list(
        session.scalars(
            select(Game).where(Game.state == GameState.ARCHIVED).order_by(Game.archived_at)
        )
    )
    max_size = values.archive_max_size_mb * 1024 * 1024

    def over() -> bool:
        if values.archive_limit == "count":
            return len(archived) > values.archive_max_count
        return sum(g.archive_size or 0 for g in archived) > max_size

    deleted = []
    for game in list(archived):
        if not over():
            break
        if game.id in keep:
            continue
        archived.remove(game)
        delete_archive(session, settings, game.id)
        deleted.append(game.id)
    if deleted:
        log.info("Retention deleted archives %s", deleted)
    return deleted


@dataclass(frozen=True)
class ArchiveFile:
    path: str
    size: int


def list_archives(session: Session) -> list[Game]:
    return list(
        session.scalars(
            select(Game).where(Game.state == GameState.ARCHIVED).order_by(Game.archived_at.desc())
        )
    )


def files(settings: Settings, game_id: int) -> list[ArchiveFile]:
    root = archive_path(settings, game_id)
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            info = path.lstat()
            if stat.S_ISREG(info.st_mode):
                found.append(ArchiveFile(path.relative_to(root).as_posix(), info.st_size))
    return found


def read_meta(settings: Settings, game_id: int) -> dict[str, Any]:
    try:
        data = json.loads((archive_path(settings, game_id) / META_FILE).read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def open_file(session: Session, settings: Settings, game_id: int, path: str) -> Path:
    """One file of an archive, if the listing has it: nothing else can be named."""
    get_archived(session, game_id)
    if path not in {f.path for f in files(settings, game_id)}:
        raise ArchiveError("not-found", "No such file in this archive", 404)
    return archive_path(settings, game_id) / path


def download(session: Session, settings: Settings, game_id: int) -> tuple[str, Iterator[bytes]]:
    """The whole archive as one zip, streamed as it is built."""
    game = get_archived(session, game_id)
    root = archive_path(settings, game_id)
    listing = files(settings, game_id)
    seed = read_meta(settings, game_id).get("seed_name")
    name = f"archive-{game.id}" + (f"-AP_{seed}" if isinstance(seed, str) and seed else "")

    def chunks() -> Iterator[bytes]:
        sink = Sink()
        with zipfile.ZipFile(cast("IO[bytes]", sink), "w") as out:
            for item in listing:
                with (root / item.path).open("rb") as src, out.open(item.path, "w") as dest:
                    while chunk := src.read(CHUNK):
                        dest.write(chunk)
                        yield sink.take()
                yield sink.take()
        yield sink.take()

    return f"{name}.zip", chunks()


def get_archived(session: Session, game_id: int) -> Game:
    game = session.get(Game, game_id)
    if game is None or game.state != GameState.ARCHIVED:
        raise ArchiveError("not-found", "No such archive", 404)
    return game


def _current_summary(session: Session, game: Game) -> dict[str, Any]:
    slots = session.scalar(select(func.count()).where(Slot.game_id == game.id)) or 0
    return {"id": game.id, "state": game.state, "slots": slots}


def _meta(
    session: Session, settings: Settings, game: Game, archived_from: GameState
) -> dict[str, Any]:
    generations = list(
        session.scalars(
            select(Generation).where(Generation.game_id == game.id).order_by(Generation.id)
        )
    )
    latest = next((g for g in reversed(generations) if g.status == "ok"), None)
    uploads = list(session.scalars(select(Upload).where(Upload.game_id == game.id)))
    slots = session.scalars(select(Slot).where(Slot.game_id == game.id).order_by(Slot.id))
    meta: dict[str, Any] = jsonable_encoder(
        {
            "format": FORMAT,
            "game_id": game.id,
            "created_at": game.created_at,
            "archived_at": datetime.now(UTC),
            "archived_from": archived_from,
            "archipelago_version": settings.archipelago_version or None,
            "seed_name": latest.seed_name if latest else None,
            "slots": [{"name": s.name, "games": s.games} for s in slots],
            "worlds": [
                {"world": lock.world, "label": world_label(settings, lock)}
                for lock in locks(session, game.id)
            ],
            "generations": [generation_summary(session, g) for g in generations],
            "uploads": [upload_log.detail(session, u) for u in uploads],
        }
    )
    return meta


def yaml_names(session: Session, game: Game) -> dict[str, int]:
    """The archive's name for each accepted YAML, by upload ID (#105): its slots' names,
    `Alice.yaml` or `Alice+Bob.yaml`, so the archive means something to someone browsing
    it. Characters a file name can't hold become `_`; a clash gets `-2`, `-3`."""
    names: dict[str, int] = {}
    taken: set[str] = set()
    uploads = session.scalars(
        select(Upload)
        .where(Upload.game_id == game.id, Upload.status == "accepted")
        .order_by(Upload.id)
    )
    for upload in uploads:
        slots = sorted(upload.slots, key=lambda slot: slot.document)
        stem = "+".join(slot.name for slot in slots) or f"upload-{upload.id}"
        stem = _UNSAFE.sub("_", stem).strip().lstrip(".")[:100] or f"upload-{upload.id}"
        name, n = f"{stem}.yaml", 1
        while name.casefold() in taken:
            n += 1
            name = f"{stem}-{n}.yaml"
        taken.add(name.casefold())
        names[name] = upload.id
    return names


def _copy_yamls(source: Path, dest: Path, names: dict[str, int]) -> None:
    """The game's `<upload id>.yaml` files, under their archive names. Anything else in the
    folder keeps its own name."""
    by_file = {f"{upload_id}.yaml": name for name, upload_id in names.items()}
    if not source.is_dir() or source.is_symlink():
        return
    for entry in sorted(os.scandir(source), key=lambda e: e.name):
        _copy_files(Path(entry.path), dest / by_file.get(entry.name, entry.name))


def _yaml_files(source: Path) -> dict[str, int]:
    """archive.json's map of YAML file to upload ID; archives from Alpha 1 have none."""
    try:
        meta = json.loads((source / META_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    files = meta.get("yaml_files") if isinstance(meta, dict) else None
    if not isinstance(files, dict):
        return {}
    return {k: v for k, v in files.items() if isinstance(k, str) and type(v) is int}


def _restore_yamls(source: Path, dest: Path, names: dict[str, int]) -> None:
    """Back to `<upload id>.yaml`, which the game folder uses."""
    if not source.is_dir() or source.is_symlink():
        return
    for entry in sorted(os.scandir(source), key=lambda e: e.name):
        upload_id = names.get(entry.name)
        _copy_files(Path(entry.path), dest / (f"{upload_id}.yaml" if upload_id else entry.name))


def _restore_library(session: Session, settings: Settings, game: Game, source: Path) -> None:
    """Put back any locked apworld missing from the library, from the archive's copy."""
    for lock in locks(session, game.id):
        if lock.apworld is None:
            continue
        target = library_path(settings, lock.apworld)
        copy = source / APWORLDS / f"{lock.apworld.module}.apworld"
        if not target.is_file() and copy.is_file():
            _copy_files(copy, target)


def _delete_rows(session: Session, game: Game) -> None:
    job_ids = {
        *session.scalars(select(Upload.job_id).where(Upload.game_id == game.id)),
        *session.scalars(select(Generation.job_id).where(Generation.game_id == game.id)),
    } - {None}
    session.execute(delete(Slot).where(Slot.game_id == game.id))
    session.execute(delete(WorldLock).where(WorldLock.game_id == game.id))
    session.execute(delete(Generation).where(Generation.game_id == game.id))
    session.execute(delete(Upload).where(Upload.game_id == game.id))
    if job_ids:
        session.execute(delete(Job).where(Job.id.in_(job_ids)))
    session.delete(game)


def _clear_game_dir(settings: Settings) -> None:
    """Empty the game folder, but keep the folder: it is a mount point under Compose.

    The game's own parts must go. Elsewhere (ap/, the server's Archipelago user folder) the
    web service may not be allowed to remove what MultiServer made: AP copies its default
    files there with their extended attributes, SELinux label included. Those are left;
    the game-specific parts of ap/ are rebuilt at every start."""
    root = settings.game_dir
    root.mkdir(parents=True, exist_ok=True)
    for entry in os.scandir(root):
        path = Path(entry.path)
        if not entry.is_dir(follow_symlinks=False):
            path.unlink()
        elif entry.name in GAME_PARTS:
            shutil.rmtree(path)
        else:
            shutil.rmtree(path, onexc=_leave_unremovable)


def _leave_unremovable(func: Any, path: str, exc: BaseException) -> None:
    """Denied, or a folder still holding something denied: leave it."""
    if not isinstance(exc, OSError):
        raise exc
    log.warning("Left %s in the game folder: %s", path, exc)


def _copy_files(source: Path, dest: Path) -> None:
    """Copy a regular file, or the regular files under a folder, without following
    symlinks anywhere."""
    try:
        info = source.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISREG(info.st_mode):
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as src, dest.open("wb") as out:
            shutil.copyfileobj(src, out, CHUNK)
        return
    if not stat.S_ISDIR(info.st_mode):
        return
    dest.mkdir(parents=True, exist_ok=True)
    for entry in sorted(os.scandir(source), key=lambda e: e.name):
        _copy_files(Path(entry.path), dest / entry.name)


def _size(root: Path) -> int:
    return sum(
        (Path(dirpath) / name).lstat().st_size
        for dirpath, _dirs, names in os.walk(root)
        for name in names
    )
