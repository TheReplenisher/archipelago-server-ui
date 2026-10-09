from typing import Annotated

from apsui_server.protocol import ControlError
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from apsui.config import Settings
from apsui.server_control import request

router = APIRouter(tags=["server"])


class ServerStatus(BaseModel):
    reachable: bool
    state: str | None = None
    archipelago_version: str | None = None


def get_settings(req: Request) -> Settings:
    settings: Settings = req.app.state.settings
    return settings


@router.get("/server")
async def server_status(settings: Annotated[Settings, Depends(get_settings)]) -> ServerStatus:
    """Whether the server service answers on the control socket, and what it reports.
    Start / Stop / Save are #24."""
    try:
        response = await request(settings.control_socket, {"op": "status"})
    except ControlError:
        return ServerStatus(reachable=False)
    return ServerStatus(
        reachable=bool(response.get("ok")),
        state=response.get("state"),
        archipelago_version=response.get("archipelago_version"),
    )
