"""The audit log of admin actions (#37), newest first, filterable."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import String, cast, or_, select

from apsui import audit
from apsui.api.game import SessionDep
from apsui.models import AuditEntry

router = APIRouter(tags=["audit"])

MAX_PAGE = 200


class AuditOut(BaseModel):
    id: int
    at: datetime
    actor: str | None
    action: str
    label: str
    target: str | None
    detail: dict[str, Any] | None
    status: int
    ok: bool
    """The request succeeded (2xx or 3xx), or the shell did it."""
    client: str | None


class AuditPage(BaseModel):
    entries: list[AuditOut]
    next_before: int | None
    """Pass as `before` for the next (older) page; null on the last one."""
    actions: dict[str, str]
    """Every action and its label, for the filter."""


@router.get("/audit")
def list_audit(
    session: SessionDep,
    action: Annotated[list[str] | None, Query()] = None,
    actor: str | None = None,
    failed: bool = False,
    q: Annotated[str | None, Query(max_length=200)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    before: int | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
) -> AuditPage:
    """Admin actions, newest first. Filters: `action` (any of), `actor`, `failed` (only
    refused or failed ones), `q` (text in the target or detail), `since`/`until`.
    Page with `before`."""
    query = select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit + 1)
    if action:
        query = query.where(AuditEntry.action.in_(action))
    if actor:
        query = query.where(AuditEntry.actor == actor)
    if failed:
        query = query.where(AuditEntry.status >= 400)
    if q:
        pattern = f"%{q.replace('%', '').replace('_', '')}%"
        query = query.where(
            or_(AuditEntry.target.ilike(pattern), cast(AuditEntry.detail, String).ilike(pattern))
        )
    if since:
        query = query.where(AuditEntry.at >= since)
    if until:
        query = query.where(AuditEntry.at <= until)
    if before:
        query = query.where(AuditEntry.id < before)
    rows = list(session.scalars(query))
    more = len(rows) > limit
    rows = rows[:limit]
    return AuditPage(
        entries=[
            AuditOut(
                id=e.id,
                at=e.at,
                actor=e.actor,
                action=e.action,
                label=audit.label(e.action),
                target=e.target,
                detail=e.detail,
                status=e.status,
                ok=e.status < 400,
                client=e.client,
            )
            for e in rows
        ],
        next_before=rows[-1].id if more and rows else None,
        actions=audit.ACTIONS,
    )
