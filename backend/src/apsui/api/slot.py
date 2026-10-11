from typing import Annotated, Any

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from pydantic import BaseModel, Field

from apsui.api.game import SessionDep
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
