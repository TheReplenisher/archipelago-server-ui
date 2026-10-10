import shutil
from pathlib import Path
from typing import Annotated, Literal

from apsui_server.protocol import ControlError
from apsui_worker.protocol import HEARTBEAT_MAX_AGE, JobDirs, State
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from apsui import __version__
from apsui.config import Settings
from apsui.db import get_session
from apsui.server_control import request as control_request

router = APIRouter(tags=["health"])

SessionDep = Annotated[Session, Depends(get_session)]


class Health(BaseModel):
    status: Literal["ok"]
    version: str
    database: Literal["ok"]


@router.get("/health")
def health(session: SessionDep) -> Health:
    """Liveness, for container healthchecks. The health page uses /api/health/details."""
    session.execute(text("SELECT 1"))
    return Health(status="ok", version=__version__, database="ok")


class ServiceHealth(BaseModel):
    name: Literal["web", "worker", "server"]
    up: bool
    detail: str
    """One line: what it is doing, or why it looks down."""


class DiskUse(BaseModel):
    name: str
    path: str
    total: int
    used: int
    free: int


class Port(BaseModel):
    name: str
    port: int | None
    """Published on the host; null when the container wasn't told."""


class HealthDetails(BaseModel):
    version: str
    archipelago_version: str | None
    isolation: str
    isolation_warning: str | None
    services: list[ServiceHealth]
    ports: list[Port]
    disks: list[DiskUse]


def _worker(settings: Settings) -> ServiceHealth:
    dirs = JobDirs(settings.resolved_jobs_dir)
    age = dirs.heartbeat_age()
    queued, running = len(dirs.ids(State.QUEUE)), len(dirs.ids(State.RUNNING))
    jobs = f"{queued} queued, {running} running"
    if age is None:
        return ServiceHealth(name="worker", up=False, detail=f"Never seen; {jobs}")
    if age > HEARTBEAT_MAX_AGE:
        return ServiceHealth(name="worker", up=False, detail=f"Silent for {age:.0f}s; {jobs}")
    return ServiceHealth(name="worker", up=True, detail=f"Heartbeat {age:.0f}s ago; {jobs}")


async def _server(settings: Settings) -> tuple[ServiceHealth, dict[str, object]]:
    try:
        status = await control_request(settings.control_socket, {"op": "status"})
    except ControlError:
        return ServiceHealth(name="server", up=False, detail="Not answering"), {}
    detail = f"MultiServer {status.get('state', 'unknown')}"
    return ServiceHealth(name="server", up=bool(status.get("ok")), detail=detail), status


def _disk(name: str, path: Path) -> DiskUse | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return DiskUse(name=name, path=str(path), total=usage.total, used=usage.used, free=usage.free)


ISOLATION_WARNINGS = {
    "compose": None,
    "lxc": None,
    "none": "Services aren't isolated: uploaded apworlds run with the same access as the "
    "web service. Use only for development.",
}


@router.get("/health/details")
async def health_details(request: Request, session: SessionDep) -> HealthDetails:
    """The health page (admin): each service, published ports, disk use, the Archipelago
    version and the isolation mode."""
    settings: Settings = request.app.state.settings
    session.execute(text("SELECT 1"))
    server, status = await _server(settings)
    services = [
        ServiceHealth(name="web", up=True, detail=f"v{__version__}, database ok"),
        _worker(settings),
        server,
    ]
    disks = [
        d
        for d in (
            _disk("Data", settings.data_dir),
            _disk("Job queue", settings.resolved_jobs_dir),
            _disk("Current game", settings.game_dir),
        )
        if d is not None
    ]
    return HealthDetails(
        version=__version__,
        archipelago_version=settings.archipelago_version
        or str(status.get("archipelago_version") or "")
        or None,
        isolation=settings.isolation,
        isolation_warning=ISOLATION_WARNINGS.get(
            settings.isolation, f"Unknown isolation mode {settings.isolation!r}"
        ),
        services=services,
        ports=[
            Port(name="Web UI", port=settings.public_web_port),
            Port(name="Game (Archipelago clients)", port=settings.public_game_port),
        ],
        disks=disks,
    )
