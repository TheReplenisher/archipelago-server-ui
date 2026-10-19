"""The audit log of admin actions (DESIGN.md §7, #37): who did what, when, from where,
and how it went.

Recorded by middleware, so no admin route can be missed: every request that changes
something (any method but GET/HEAD/OPTIONS) and came from a logged-in admin, plus the
login routes themselves (failed logins too), and opening the spoiler log. The action is
the route's endpoint, labelled in ACTIONS; the target comes from the path (`apworld 3`).
A route can add facts with `note(request, ...)`; passwords never go in.

Kept for 90 days, and at most 20 000 entries; older ones are pruned as new ones come.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from apsui.models import Admin, AuditEntry

log = logging.getLogger(__name__)

KEEP_FOR = timedelta(days=90)
KEEP_AT_MOST = 20_000
PRUNE_EVERY = 100
"""Prune once every this many entries, not on every write."""

ACTIONS: dict[str, str] = {
    # admin login (#32)
    "setup": "Set the admin password (first run)",
    "login": "Logged in",
    "logout": "Logged out",
    "change_password": "Changed the admin password",
    "set_password_shell": "Set the admin password from the shell",
    # game lifecycle
    "lock": "Locked uploads",
    "unlock": "Unlocked uploads",
    "generate": "Started generation",
    "discard": "Discarded the output",
    "start_server": "Started the server",
    "stop_server": "Stopped the server",
    "save_server": "Saved the server",
    "send_command": "Sent a console command",
    "download_spoiler": "Opened the spoiler log",
    # archives
    "archive_game": "Archived the game",
    "restore_archive": "Restored an archive",
    "delete_archive": "Deleted an archive",
    # uploads
    "upload_yaml": "Uploaded a YAML",
    "delete_upload": "Removed an upload",
    "rename_upload": "Renamed slots",
    "cancel_upload": "Cancelled an upload",
    "upload_apworld": "Uploaded an apworld",
    "approve_apworld": "Approved an apworld",
    "reject_apworld": "Rejected an apworld",
    "override_world": "Changed a game's locked version",
    # settings
    "put_settings": "Changed settings",
    # backups (#38)
    "create_backup": "Made a backup",
    "delete_backup": "Deleted a backup",
    "finish_upload": "Uploaded a backup",
    "restore_backup": "Restored a backup",
}
"""Each audited endpoint's label. One missing from here still logs, by its name."""

LOGIN_ROUTES = frozenset({"setup", "login"})
"""Logged whether or not the admin was logged in: a refused login matters most."""
AUDITED_READS = frozenset({"download_spoiler"})
"""GETs worth recording."""
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_TARGETS = {
    "game_id": "game",
    "apworld_id": "apworld",
    "upload_id": "upload",
    "item_id": "item",
}
_PASSWORD_OPTION = re.compile(r"^(\s*/option\s+(?:server_)?password\b).*$", re.IGNORECASE)


def note(request: Request, **facts: Any) -> None:
    """Add facts to this request's audit entry. Never pass a password."""
    detail: dict[str, Any] = getattr(request.state, "audit", None) or {}
    detail.update(facts)
    request.state.audit = detail


def redact_command(text: str) -> str:
    """A console line, without the password of `/option password …`."""
    return _PASSWORD_OPTION.sub(r"\1 ••••", text)


def record(
    session: Session,
    *,
    actor: str | None,
    action: str,
    status: int,
    target: str | None = None,
    detail: dict[str, Any] | None = None,
    client: str | None = None,
) -> AuditEntry:
    entry = AuditEntry(
        at=datetime.now(UTC),
        actor=actor,
        action=action[:64],
        target=target[:255] if target else None,
        detail=detail or None,
        status=status,
        client=client[:64] if client else None,
    )
    session.add(entry)
    session.flush()
    if entry.id % PRUNE_EVERY == 0:
        prune(session)
    session.commit()
    return entry


def prune(session: Session) -> None:
    session.execute(delete(AuditEntry).where(AuditEntry.at < datetime.now(UTC) - KEEP_FOR))
    newest = session.scalar(select(func.max(AuditEntry.id))) or 0
    session.execute(delete(AuditEntry).where(AuditEntry.id <= newest - KEEP_AT_MOST))


def _target(path_params: dict[str, Any]) -> str | None:
    parts = [f"{_TARGETS.get(k, k)} {v}" for k, v in path_params.items() if k in _TARGETS]
    if "file" in path_params:
        parts.append(str(path_params["file"]))
    if "name" in path_params:
        parts.append(str(path_params["name"]))
    if "path" in path_params:
        parts.append(str(path_params["path"]))
    return ", ".join(parts) or None


async def middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Records the request after it is answered, if it is an admin action."""
    response = await call_next(request)
    name = getattr(request.scope.get("endpoint"), "__name__", None)
    path = request.url.path
    if name is None or not path.startswith("/api/") or path.startswith("/api/slot"):
        return response
    admin: Admin | None = getattr(request.state, "admin", None)
    if not (name in LOGIN_ROUTES and path.startswith("/api/admin/")):
        if admin is None:
            return response
        if request.method in SAFE_METHODS and name not in AUDITED_READS:
            return response
    try:
        with request.app.state.sessionmaker() as session:
            record(
                session,
                actor=admin.username if admin else None,
                action=name,
                status=response.status_code,
                target=_target(request.scope.get("path_params") or {}),
                detail=getattr(request.state, "audit", None),
                client=request.client.host if request.client else None,
            )
    except Exception:
        log.exception("writing the audit log failed")
    return response


def label(action: str) -> str:
    return ACTIONS.get(action, action)
