"""Admin login (DESIGN.md §7, #32).

- **One admin, `admin`.** Until its password is set, whoever opens the admin pages first
  sets it (conne's decision, 2026-10-18), and the health page warns. Anyone with a shell on
  the host can set a new one with `apsui-admin set-password` (apsui.admin_cli): the way
  back in after a forgotten password, or after someone else claimed the install first.
- **Passwords** are hashed with scrypt (the standard library's; no extra dependency),
  each with its own salt, and compared in constant time.
- **Sessions** are random tokens in an `HttpOnly`, `SameSite=Strict` cookie; only their
  SHA-256 is stored, in app.db, so a web restart keeps the admin logged in. A session ends
  after a week unused or a month in all, at logout, and when the password changes (every
  session but the one that changed it; all of them when changed from the shell).
- **Logins are limited** to 10 a minute per client address, and 30 a minute in all.

apsui.same_origin still guards every request, the login form included.
"""

from __future__ import annotations

import base64
import collections
import hashlib
import hmac
import logging
import secrets
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apsui.models import Admin, AdminSession

log = logging.getLogger(__name__)

COOKIE = "apsui_admin"
USERNAME = "admin"
MIN_PASSWORD = 8
MAX_PASSWORD = 1024
SESSION_IDLE = timedelta(days=7)
SESSION_MAX = timedelta(days=30)
TOUCH_EVERY = timedelta(minutes=1)
"""How often a session's last_seen_at is written: not on every request."""
LOGINS_PER_CLIENT = 10
LOGINS_IN_ALL = 30

# scrypt at about 64 MB: well inside the web service's memory limit, and slow to guess.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**16, 8, 1
SCRYPT_MAXMEM = 128 * 1024 * 1024


class AuthError(Exception):
    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return "$".join(
        ["scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P), _b64(salt), _b64(digest)]
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        found = _scrypt(password, _unb64(salt), int(n), int(r), int(p))
    except ValueError:
        return False
    return hmac.compare_digest(found, _unb64(digest))


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode(), salt=salt, n=n, r=r, p=p, maxmem=SCRYPT_MAXMEM, dklen=32
    )


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode(), validate=True)


def check_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError("password-too-short", f"Use at least {MIN_PASSWORD} characters", 422)
    if len(password) > MAX_PASSWORD:
        raise AuthError("password-too-long", f"Use at most {MAX_PASSWORD} characters", 422)


def get_admin(session: Session) -> Admin | None:
    return session.scalars(select(Admin).where(Admin.username == USERNAME)).one_or_none()


def is_password_set(session: Session) -> bool:
    return get_admin(session) is not None


def setup(session: Session, password: str) -> tuple[Admin, str]:
    """First run: set the admin password, if nobody has yet, and log in. Returns the
    admin and a session token."""
    check_new_password(password)
    if is_password_set(session):
        raise AuthError("already-set", "The admin password is already set: log in", 409)
    now = datetime.now(UTC)
    admin = Admin(
        username=USERNAME,
        password_hash=hash_password(password),
        created_at=now,
        password_changed_at=now,
    )
    session.add(admin)
    try:
        session.commit()
    except IntegrityError as exc:  # someone else set it at the same moment
        session.rollback()
        raise AuthError("already-set", "The admin password is already set: log in", 409) from exc
    log.warning("The admin password was set from the web, for the first time")
    return admin, new_session(session, admin)


def set_password(session: Session, password: str) -> Admin:
    """From the shell (apsui-admin): set the password, creating the admin if there is
    none yet, and end every session."""
    check_new_password(password)
    now = datetime.now(UTC)
    admin = get_admin(session)
    if admin is None:
        admin = Admin(username=USERNAME, created_at=now, password_hash="")
        session.add(admin)
    admin.password_hash, admin.password_changed_at = hash_password(password), now
    session.flush()
    session.execute(delete(AdminSession).where(AdminSession.admin_id == admin.id))
    session.commit()
    return admin


def change_password(
    session: Session, admin: Admin, current: str, new: str, keep_token: str | None
) -> None:
    """From the admin pages: needs the current password; ends every other session."""
    if not verify_password(current, admin.password_hash):
        raise AuthError("wrong-password", "The current password is wrong", 403)
    check_new_password(new)
    admin.password_hash, admin.password_changed_at = hash_password(new), datetime.now(UTC)
    others = delete(AdminSession).where(AdminSession.admin_id == admin.id)
    if keep_token:
        others = others.where(AdminSession.token_hash != _key(keep_token))
    session.execute(others)
    session.commit()


class LoginLimiter:
    """Login attempts in the last minute, per client address and in all."""

    def __init__(self) -> None:
        self.by_client: dict[str, collections.deque[float]] = {}
        self.all: collections.deque[float] = collections.deque()

    def check(self, client: str) -> None:
        now = time.monotonic()
        recent = self.by_client.setdefault(client, collections.deque())
        for attempts in (recent, self.all):
            while attempts and now - attempts[0] > 60:
                attempts.popleft()
        if len(recent) >= LOGINS_PER_CLIENT or len(self.all) >= LOGINS_IN_ALL:
            raise AuthError("too-many-logins", "Too many login attempts: wait a minute", 429)
        recent.append(now)
        self.all.append(now)
        for key in [k for k, v in self.by_client.items() if not v]:
            del self.by_client[key]


def login(session: Session, limiter: LoginLimiter, password: str, client: str) -> tuple[Admin, str]:
    limiter.check(client)
    admin = get_admin(session)
    if admin is None:
        raise AuthError("password-not-set", "Set the admin password first", 409)
    if len(password) > MAX_PASSWORD or not verify_password(password, admin.password_hash):
        log.warning("Admin login refused from %s", client)
        raise AuthError("login-refused", "Wrong password", 401)
    return admin, new_session(session, admin)


def new_session(session: Session, admin: Admin) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    session.add(
        AdminSession(token_hash=_key(token), admin_id=admin.id, created_at=now, last_seen_at=now)
    )
    session.execute(  # tidy up the expired ones now and then
        delete(AdminSession).where(AdminSession.last_seen_at < now - SESSION_IDLE)
    )
    session.commit()
    return token


def authenticate(session: Session, token: str | None) -> Admin | None:
    """The admin this session token belongs to, or None."""
    if not token or len(token) > 128:
        return None
    found = session.scalars(
        select(AdminSession).where(AdminSession.token_hash == _key(token))
    ).one_or_none()
    if found is None:
        return None
    now = datetime.now(UTC)
    last_seen, created = _aware(found.last_seen_at), _aware(found.created_at)
    if now - last_seen > SESSION_IDLE or now - created > SESSION_MAX:
        session.delete(found)
        session.commit()
        return None
    if now - last_seen > TOUCH_EVERY:
        found.last_seen_at = now
        session.commit()
    return session.get(Admin, found.admin_id)


def logout(session: Session, token: str | None) -> None:
    if token:
        session.execute(delete(AdminSession).where(AdminSession.token_hash == _key(token)))
        session.commit()


def _key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _aware(moment: datetime) -> datetime:
    """SQLite hands back naive datetimes; they were stored in UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
