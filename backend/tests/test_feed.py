"""The admin's server feed (#27): MultiServer's log, followed."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from apsui import feed
from apsui.config import Settings
from apsui.feed import Follower
from apsui.main import create_app


def test_scrollback_then_new_lines(tmp_path: Path) -> None:
    log = tmp_path / "server.log"
    log.write_bytes(b"one\ntwo\nha")
    follower = Follower(log)
    assert follower.scrollback() == ["one", "two"]
    assert follower.poll() == (False, [])  # nothing new
    with log.open("ab") as f:
        f.write(b"lf done\r\nthree\nfou")
    assert follower.poll() == (False, ["half done", "three"])
    with log.open("ab") as f:
        f.write(b"r\n")
    assert follower.poll() == (False, ["four"])


def test_scrollback_keeps_the_last_lines(tmp_path: Path) -> None:
    log = tmp_path / "server.log"
    log.write_text("".join(f"line {i}\n" for i in range(1000)))
    lines = Follower(log).scrollback()
    assert (len(lines), lines[0], lines[-1]) == (feed.SCROLLBACK_LINES, "line 500", "line 999")


def test_a_long_log_is_read_from_a_line_start(tmp_path: Path) -> None:
    log = tmp_path / "server.log"
    log.write_bytes(b"x" * (feed.SCROLLBACK_BYTES + 10) + b"\nlast\n")
    assert Follower(log).scrollback() == ["last"]


def test_a_new_log_resets(tmp_path: Path) -> None:
    log = tmp_path / "server.log"
    follower = Follower(log)
    assert follower.scrollback() == []
    assert follower.poll() == (False, [])
    log.write_text("hosting\n")
    assert follower.poll() == (True, ["hosting"])
    log.write_text("new game\n")  # truncated and rewritten
    assert follower.poll() == (True, ["new game"])
    replacement = tmp_path / "next.log"
    replacement.write_text("replaced\nand longer than before\n")
    replacement.replace(log)  # another file at the same path
    assert follower.poll() == (True, ["replaced", "and longer than before"])
    log.unlink()
    assert follower.poll() == (True, [])
    assert follower.poll() == (False, [])


def test_invalid_utf8_is_replaced(tmp_path: Path) -> None:
    log = tmp_path / "server.log"
    log.write_bytes(b"caf\xe9\n")
    assert Follower(log).scrollback() == ["caf�"]


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    settings.job_poll_interval = 3600
    settings.feed_poll_interval = 0.01
    with TestClient(create_app(settings)) as c:
        yield c


def test_the_feed_streams_the_log(client: TestClient, settings: Settings) -> None:
    log = feed.server_log(settings)
    log.parent.mkdir(parents=True)
    log.write_text("Hosting game at 0.0.0.0:38281\n")
    with client.websocket_connect("/api/server/feed") as ws:
        assert ws.receive_json() == {"reset": True, "lines": ["Hosting game at 0.0.0.0:38281"]}
        with log.open("a") as f:
            f.write('Notice (all): Cheat console: sending "Hammer" to Knight\n')
        message: dict[str, Any] = ws.receive_json()
        assert message == {
            "reset": False,
            "lines": ['Notice (all): Cheat console: sending "Hammer" to Knight'],
        }


@pytest.mark.parametrize("origin", [None, "http://testserver", "HTTP://TestServer"])
def test_the_feed_accepts_its_own_page(client: TestClient, origin: str | None) -> None:
    headers = {"origin": origin} if origin else {}
    with client.websocket_connect("/api/server/feed", headers=headers) as ws:
        assert ws.receive_json() == {"reset": True, "lines": []}


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": "http://evil.example"},
        {"origin": "http://testserver.evil.example"},
        {"origin": "null"},
        {"origin": "https://evil.example", "sec-fetch-site": "cross-site"},
        # DNS rebinding: the attacker's own name, now pointing here, is its own origin.
        {"host": "evil.example", "origin": "http://evil.example"},
    ],
)
def test_the_feed_refuses_other_sites(client: TestClient, headers: dict[str, str]) -> None:
    """Any page can open a WebSocket anywhere; the feed holds the room password."""
    with (
        pytest.raises(WebSocketDisconnect) as refused,
        client.websocket_connect("/api/server/feed", headers=headers),
    ):
        pass
    assert refused.value.code == 1008
