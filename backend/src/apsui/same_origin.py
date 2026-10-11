"""Keeps pages on other websites out of the web UI and its API.

Alpha 1 has no admin login, and the admin's browser can reach the UI, so any page it
opens could send requests there too. Three checks, on every request:

- **The Host header must name this server**, which stops DNS rebinding: a page on a name
  the attacker controls, re-pointed at this server's address, would otherwise be
  same-origin with the UI, free to read it as well as write to it. IP addresses and
  local-only names always pass; any other name must be listed in APSUI_ALLOWED_HOSTS.
- **Unsafe requests and WebSocket handshakes from another origin are refused.** Forms and
  fetch() can POST anywhere without a CORS preflight, uploads included. The browser's own
  Sec-Fetch-Site decides, but browsers send it only to HTTPS and localhost; over plain
  HTTP (the default install) the Origin header does. Clients that aren't browsers send
  neither and pass: they could reach the API directly anyway.
- **No page may show the UI in a frame** (clickjacking): clicks inside a frame are
  same-origin.

GETs from other sites pass the second check, so links into the UI still work. They can't
read the response, and no GET changes anything.
"""

import ipaddress
from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.websockets import WebSocketClose

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

LOCAL_SUFFIXES = (".localhost", ".local", ".home.arpa", ".internal")
"""Special-use names public DNS never answers for (RFC 6761, RFC 6762, RFC 8375, and
.internal, reserved by ICANN in 2024), so no attacker can point one at a page of theirs."""

FRAME_HEADERS = {"X-Frame-Options": "DENY", "Content-Security-Policy": "frame-ancestors 'none'"}

UNKNOWN_HOST = """\
This server doesn't answer to the name {name}.

If that is how you reach it, add the name to APSUI_ALLOWED_HOSTS and restart the web
service (see Settings in the README). Names are checked so that other websites can't
reach this one through a name of their own (DNS rebinding). IP addresses and local names
such as myserver.local always work.
"""


def hostname(host: str) -> str:
    """The name in a Host header as compared here: lower case, without the port or a
    trailing dot. Empty if there is none."""
    try:
        return (urlsplit(f"//{host}").hostname or "").rstrip(".")
    except ValueError:  # an unclosed "[", say
        return ""


def host_pattern(value: str) -> str:
    """One APSUI_ALLOWED_HOSTS entry, normalised the same way: `apsui.example.com`,
    `*.example.com` (its subdomains, not itself) or `*` (any name)."""
    name = hostname(value.strip())
    if not name or "/" in value:
        raise ValueError(f"{value!r} isn't a host name (give names, not URLs)")
    return name


def host_allowed(name: str, allowed: Iterable[str] = ()) -> bool:
    if not name:
        return False
    try:
        ipaddress.ip_address(name)
    except ValueError:
        pass
    else:
        return True  # a rebinding page needs a name; an address is the server's own
    if name == "localhost" or name.endswith(LOCAL_SUFFIXES):
        return True
    return any(
        p == "*" or p == name or (p.startswith("*.") and name.endswith(p[1:])) for p in allowed
    )


def cross_origin(headers: Headers) -> bool:
    """Whether a browser sent this request from a page on another origin."""
    site = headers.get("sec-fetch-site")
    if site is not None:
        return site not in ("same-origin", "none")  # "none": typed or bookmarked
    origin = headers.get("origin")
    if origin is None:
        return False  # not a browser
    try:
        netloc = urlsplit(origin).netloc
    except ValueError:
        return True
    # Host and port both: another app on this machine is another origin. "null"
    # (sandboxed frames, no-referrer pages) has no netloc, so never matches.
    return netloc.lower() != headers.get("host", "").lower()


class SameOriginGuard:
    """The three checks above, as ASGI middleware for HTTP and WebSocket alike."""

    def __init__(self, app: ASGIApp, allowed_hosts: Iterable[str] = ()) -> None:
        self.app = app
        self.allowed_hosts = tuple(allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        websocket = scope["type"] == "websocket"
        refusal: ASGIApp | None = None
        name = hostname(headers.get("host", ""))
        if not host_allowed(name, self.allowed_hosts):
            refusal = PlainTextResponse(UNKNOWN_HOST.format(name=repr(name or "")), 400)
        elif (websocket or scope["method"] not in SAFE_METHODS) and cross_origin(headers):
            message = "Refused: this request came from a page on another website."
            refusal = JSONResponse({"detail": {"code": "cross-origin", "message": message}}, 403)
        if refusal is not None:
            if websocket:
                refusal = WebSocketClose(code=1008)  # policy violation
            await refusal(scope, receive, send)
            return
        if websocket:
            await self.app(scope, receive, send)
            return

        async def send_unframeable(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                for key, value in FRAME_HEADERS.items():
                    response_headers.setdefault(key, value)
            await send(message)

        await self.app(scope, receive, send_unframeable)
