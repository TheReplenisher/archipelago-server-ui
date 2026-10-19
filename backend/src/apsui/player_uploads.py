"""Player uploads from the Player tab (DESIGN.md §4, #33).

While the game is Open and the admin's *Anyone can upload* setting is on (the default),
players upload their own YAMLs and apworlds. They go through exactly the checks the
admin's do. Decided with conne (2026-10-18):

- A player's apworld gets the automatic checks, then waits for the admin, whatever the
  admin's own approval setting. A separate setting approves players' apworlds
  automatically, with a security warning. A built-in replacement always waits.
- Players have no account. Each upload returns a **receipt**, a random token the player's
  browser keeps; only its SHA-256 is stored. With it, and only with it, the player sees
  the upload's status and short error, gives new slot names when asked, or withdraws it.
- **Limits per client address:** 30 YAMLs per 10 minutes and 5 apworlds per hour; and at
  most 10 players' apworlds waiting for checks or approval at once.
"""

from __future__ import annotations

import collections
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apsui import host_settings
from apsui.apworlds import label as apworld_label
from apsui.config import Settings
from apsui.lifecycle import GameState, current_game
from apsui.models import Apworld, Game, Upload

PLAYER = "player"
MAX_PENDING_APWORLDS = 10


class PlayerError(Exception):
    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Window:
    count: int
    seconds: float


LIMITS = {"yaml": Window(30, 600), "apworld": Window(5, 3600)}


class UploadLimiter:
    """Player uploads per client address, per kind, in a sliding window."""

    def __init__(self) -> None:
        self.seen: dict[tuple[str, str], collections.deque[float]] = {}

    def check(self, kind: str, client: str) -> None:
        window = LIMITS[kind]
        now = time.monotonic()
        recent = self.seen.setdefault((kind, client), collections.deque())
        while recent and now - recent[0] > window.seconds:
            recent.popleft()
        if len(recent) >= window.count:
            raise PlayerError("too-many-uploads", "Too many uploads: try again later", 429)
        recent.append(now)


def new_receipt() -> tuple[str, str]:
    """A receipt for the player, and the hash to store."""
    token = secrets.token_urlsafe(24)
    return token, receipt_hash(token)


def receipt_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _matches(stored: str | None, token: str) -> bool:
    return stored is not None and hmac.compare_digest(stored, receipt_hash(token))


def uploads_open(session: Session, settings: Settings) -> Game:
    """The current game, if players may upload to it now; else a short reason."""
    game = current_game(session)
    if not host_settings.load(session, settings).player_uploads:
        raise PlayerError("player-uploads-off", "Only the admin uploads on this server", 403)
    if game.state != GameState.OPEN:
        raise PlayerError("uploads-closed", "Uploads are closed for this game", 409)
    return game


def check_apworld_room(session: Session) -> None:
    waiting = session.scalar(
        select(func.count())
        .select_from(Apworld)
        .where(Apworld.uploaded_by == PLAYER, Apworld.status.in_(("checking", "pending")))
    )
    if (waiting or 0) >= MAX_PENDING_APWORLDS:
        raise PlayerError(
            "too-many-waiting", "Too many apworlds are waiting for the admin: try later", 429
        )


def own_upload(session: Session, upload_id: int, token: str) -> Upload:
    """A YAML upload this receipt is for. Anything else is simply not found."""
    upload = session.get(Upload, upload_id)
    if upload is None or not _matches(upload.receipt_hash, token):
        raise PlayerError("not-found", "No such upload", 404)
    return upload


def own_apworld(session: Session, apworld_id: int, token: str) -> Apworld:
    apworld = session.get(Apworld, apworld_id)
    if apworld is None or not _matches(apworld.receipt_hash, token):
        raise PlayerError("not-found", "No such upload", 404)
    return apworld


def yaml_view(session: Session, upload: Upload) -> dict[str, Any]:
    """What the player sees of their YAML: never the worker's detail or traceback."""
    game = current_game(session)
    return {
        "kind": "yaml",
        "id": upload.id,
        "filename": upload.filename,
        "status": upload.status,
        "error_code": upload.error_code,
        "error_message": upload.error_message,
        "slots": [slot.name for slot in upload.slots],
        "name_problems": [
            {k: p.get(k) for k in ("document", "current", "code", "message", "suggestion")}
            for p in (upload.name_problems or [])
            if upload.status == "needs-name"
        ],
        "current_game": upload.game_id == game.id,
        "uploaded_at": upload.uploaded_at,
    }


def apworld_view(apworld: Apworld) -> dict[str, Any]:
    return {
        "kind": "apworld",
        "id": apworld.id,
        "filename": apworld.filename,
        "label": apworld_label(apworld) if apworld.game else apworld.filename,
        "game": apworld.game,
        "status": apworld.status,
        "error_code": apworld.error_code,
        "error_message": apworld.error_message,
        "replaces_builtin": apworld.replaces_builtin is not None,
        "uploaded_at": apworld.uploaded_at,
    }
