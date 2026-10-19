"""Admin login (#32): first-run setup, login, logout, password change, and the
dependency that every admin route goes through."""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.exceptions import WebSocketException
from fastapi.requests import HTTPConnection
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apsui import admin_auth
from apsui.admin_auth import COOKIE, AuthError
from apsui.db import get_session
from apsui.models import Admin

router = APIRouter(prefix="/admin", tags=["admin"])

SessionDep = Annotated[Session, Depends(get_session)]
TokenCookie = Annotated[str | None, Cookie(alias=COOKIE)]


def require_admin(connection: HTTPConnection) -> Admin:
    """Every admin route's dependency: a logged-in admin, or 401 `admin-login-required`.
    WebSockets (the feed) are closed with policy violation instead. The admin is kept on
    the request's state for the audit log."""
    token = connection.cookies.get(COOKIE)
    with connection.app.state.sessionmaker() as session:
        admin = admin_auth.authenticate(session, token)
    if admin is None:
        if connection.scope["type"] == "websocket":
            raise WebSocketException(code=1008, reason="Log in as the admin")
        detail = {"code": "admin-login-required", "message": "Log in as the admin"}
        raise HTTPException(401, detail=detail)
    connection.state.admin = admin
    return admin


AdminDep = Annotated[Admin, Depends(require_admin)]


def _error(exc: AuthError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message})


def _set_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(admin_auth.SESSION_MAX.total_seconds()),
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/api",
    )


class SessionOut(BaseModel):
    password_set: bool
    """False until the first admin sets a password: the admin pages then ask for one."""
    logged_in: bool
    username: str | None = None


class PasswordIn(BaseModel):
    password: str = Field(max_length=admin_auth.MAX_PASSWORD)


class ChangePasswordIn(BaseModel):
    current: str = Field(max_length=admin_auth.MAX_PASSWORD)
    new: str = Field(max_length=admin_auth.MAX_PASSWORD)


@router.get("/session")
def get_admin_session(session: SessionDep, token: TokenCookie = None) -> SessionOut:
    """Whether a password is set, and whether this browser is logged in."""
    admin = admin_auth.authenticate(session, token)
    return SessionOut(
        password_set=admin_auth.is_password_set(session),
        logged_in=admin is not None,
        username=admin.username if admin else None,
    )


@router.post("/setup")
def setup(
    body: PasswordIn, request: Request, response: Response, session: SessionDep
) -> SessionOut:
    """First run only: set the admin password and log in. Refused (409 `already-set`)
    once it is set; from then on it changes with the current password, or from a shell."""
    try:
        admin, token = admin_auth.setup(session, body.password)
    except AuthError as exc:
        raise _error(exc) from exc
    _set_cookie(request, response, token)
    return SessionOut(password_set=True, logged_in=True, username=admin.username)


@router.post("/login")
def login(
    body: PasswordIn, request: Request, response: Response, session: SessionDep
) -> SessionOut:
    client = request.client.host if request.client else "unknown"
    limiter: admin_auth.LoginLimiter = request.app.state.admin_logins
    try:
        admin, token = admin_auth.login(session, limiter, body.password, client)
    except AuthError as exc:
        raise _error(exc) from exc
    _set_cookie(request, response, token)
    return SessionOut(password_set=True, logged_in=True, username=admin.username)


@router.post("/logout")
def logout(response: Response, session: SessionDep, token: TokenCookie = None) -> SessionOut:
    admin_auth.logout(session, token)
    response.delete_cookie(COOKIE, path="/api")
    return SessionOut(password_set=admin_auth.is_password_set(session), logged_in=False)


@router.post("/password")
def change_password(
    body: ChangePasswordIn, admin: AdminDep, session: SessionDep, token: TokenCookie = None
) -> SessionOut:
    """Change the password. Every other session ends; this one stays."""
    admin = session.merge(admin)
    try:
        admin_auth.change_password(session, admin, body.current, body.new, token)
    except AuthError as exc:
        raise _error(exc) from exc
    return SessionOut(password_set=True, logged_in=True, username=admin.username)
