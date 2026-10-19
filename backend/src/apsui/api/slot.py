from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from apsui import patches
from apsui.api.game import PatchOut, SessionDep
from apsui.slots import COOKIE, SlotError, SlotViews

router = APIRouter(prefix="/slot", tags=["slot"])

TokenCookie = Annotated[str | None, Cookie(alias=COOKIE)]


def _views(request: Request) -> SlotViews:
    views: SlotViews = request.app.state.slot_views
    return views


def _error(exc: SlotError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message})


class LoginIn(BaseModel):
    name: str = Field(max_length=64)
    password: str = Field(default="", max_length=256)
    """The room password, not the admin's server password. Empty when the room has none."""


@router.post("/login")
async def login(
    body: LoginIn, request: Request, response: Response, session: SessionDep
) -> dict[str, str]:
    """Log in to a slot: the running server checks the name and room password. Sets a
    session cookie for this path."""
    client = request.client.host if request.client else "unknown"
    try:
        token = await _views(request).login(session, body.name, body.password, client)
    except SlotError as exc:
        raise _error(exc) from exc
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/api/slot",
    )
    return {"name": body.name}


@router.post("/logout")
def logout(request: Request, response: Response, token: TokenCookie = None) -> dict[str, bool]:
    _views(request).logout(token)
    response.delete_cookie(COOKIE, path="/api/slot")
    return {"ok": True}


@router.get("")
async def view(request: Request, session: SessionDep, token: TokenCookie = None) -> dict[str, Any]:
    """The logged-in slot's view: received items, unreceived items (as the room's
    !remaining allows), unchecked locations and hints. 503 `server-stopped` while the
    server isn't running."""
    try:
        return await _views(request).view(session, token)
    except SlotError as exc:
        raise _error(exc) from exc


async def _own_patches(
    request: Request, session: SessionDep, token: str | None
) -> list[patches.Patch]:
    try:
        name = await _views(request).slot_name(session, token)
        found = patches.list_patches(session, request.app.state.settings)
    except SlotError as exc:
        raise _error(exc) from exc
    except patches.PatchError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": exc.message}) from exc
    return [p for p in found if p.slot == name]


@router.get("/patches")
async def my_patches(
    request: Request, session: SessionDep, token: TokenCookie = None
) -> list[PatchOut]:
    """The logged-in slot's own patch or mod files (#36). Never another slot's."""
    return [
        PatchOut(file=p.file, player=p.player, slot=p.slot, size=p.size)
        for p in await _own_patches(request, session, token)
    ]


@router.get("/patches/{file}")
async def download_my_patch(
    file: str, request: Request, session: SessionDep, token: TokenCookie = None
) -> StreamingResponse:
    if file not in {p.file for p in await _own_patches(request, session, token)}:
        raise HTTPException(404, detail={"code": "not-found", "message": "No such patch file"})
    chunks: Iterator[bytes] = patches.read_patch(session, request.app.state.settings, file)
    return StreamingResponse(
        chunks,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{file}"'},
    )


@router.get("/feed")
async def player_feed(
    request: Request, session: SessionDep, token: TokenCookie = None, after: int = 0
) -> dict[str, Any]:
    """What MultiServer tells every player (#35): item sends, chat, joins, goals, …, after
    entry `after`. Never hints, and never the admin's feed. Poll it."""
    try:
        return await _views(request).feed_after(session, token, after)
    except SlotError as exc:
        raise _error(exc) from exc
