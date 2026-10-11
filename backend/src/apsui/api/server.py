import asyncio
import contextlib
from typing import Annotated
from urllib.parse import urlsplit

from apsui_server.protocol import ControlError
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apsui import feed, hosting
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


class ConsoleLine(BaseModel):
    text: str


@router.post("/server/command")
async def send_command(
    line: ConsoleLine, request: Request, session: Annotated[Session, Depends(get_session)]
) -> ServerStatus:
    """Send one line to MultiServer's console, as typed on its own console: a /command, or
    chat as the server. The output goes to MultiServer's log (the live feed is #27)."""
    try:
        response = await hosting.command(session, request.app.state.settings, line.text)
    except hosting.HostingError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": exc.message}) from exc
    fields = {k: v for k, v in response.items() if k in ServerStatus.model_fields}
    return ServerStatus.model_validate(fields | {"reachable": True})


def _same_origin(websocket: WebSocket) -> bool:
    """Browsers let any page open a WebSocket anywhere, so one from another site (which
    sends its Origin) is refused: the feed holds the room password. Clients that aren't
    browsers send no Origin."""
    origin = websocket.headers.get("origin")
    if origin is None:
        return True
    return urlsplit(origin).netloc.lower() == websocket.headers.get("host", "").lower()


@router.websocket("/server/feed")
async def server_feed(websocket: WebSocket) -> None:
    """MultiServer's output, live: {"reset": true, "lines": [...]} with the scrollback
    first (and again when a new log starts), then {"reset": false, "lines": [...]} as
    lines are written."""
    if not _same_origin(websocket):
        await websocket.close(code=1008)  # policy violation
        return
    await websocket.accept()
    settings: Settings = websocket.app.state.settings
    follower = feed.Follower(feed.server_log(settings))

    async def follow() -> None:
        await websocket.send_json({"reset": True, "lines": follower.scrollback()})
        while True:
            await asyncio.sleep(settings.feed_poll_interval)
            reset, lines = follower.poll()
            if reset or lines:
                await websocket.send_json({"reset": reset, "lines": lines})

    async def until_closed() -> None:
        while (await websocket.receive())["type"] != "websocket.disconnect":
            pass

    tasks = [asyncio.create_task(follow()), asyncio.create_task(until_closed())]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done:
        with contextlib.suppress(WebSocketDisconnect):  # it left mid-send
            task.result()
