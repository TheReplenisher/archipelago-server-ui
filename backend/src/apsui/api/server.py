from typing import Annotated

from apsui_server.protocol import ControlError
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apsui import hosting
from apsui.config import Settings
from apsui.db import get_session
from apsui.server_control import request

router = APIRouter(tags=["server"])


class ServerStatus(BaseModel):
    reachable: bool
    state: str | None = None
    """stopped, starting, running, stopping or crashed."""
    archipelago_version: str | None = None
    multidata: str | None = None
    port: int | None = None
    started_at: str | None = None
    exit_code: int | None = None
    log_tail: list[str] = []
    """MultiServer's last lines, when it crashed."""


def get_settings(req: Request) -> Settings:
    settings: Settings = req.app.state.settings
    return settings


@router.get("/server")
async def server_status(settings: Annotated[Settings, Depends(get_settings)]) -> ServerStatus:
    """Whether the server service answers on the control socket, and what MultiServer is
    doing. Start and Stop are game actions (POST /api/game/start, /stop)."""
    try:
        response = await request(settings.control_socket, {"op": "status"})
    except ControlError:
        return ServerStatus(reachable=False)
    fields = {k: v for k, v in response.items() if k in ServerStatus.model_fields}
    return ServerStatus.model_validate(fields | {"reachable": bool(response.get("ok"))})


@router.post("/server/save")
async def save_server(
    request: Request, session: Annotated[Session, Depends(get_session)]
) -> ServerStatus:
    """Write the save file without stopping the server."""
    try:
        response = await hosting.save(session, request.app.state.settings)
    except hosting.HostingError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": exc.message}) from exc
    fields = {k: v for k, v in response.items() if k in ServerStatus.model_fields}
    return ServerStatus.model_validate(fields | {"reachable": True})
