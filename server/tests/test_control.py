import asyncio
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from apsui_server.client import request
from apsui_server.protocol import ControlError
from apsui_server.supervisor import SOCKET_MODE, Supervisor, serve
from apsui_server.testing import running_supervisor


@pytest.fixture
def socket_path(tmp_path: Path) -> Iterator[Path]:
    with running_supervisor(tmp_path / "run" / "control.sock") as path:
        yield path


def test_status(socket_path: Path) -> None:
    response = request(socket_path, {"op": "status"})
    assert response["ok"] is True
    assert response["state"] == "stopped"


def test_socket_is_owner_and_group_only(socket_path: Path) -> None:
    assert stat.S_IMODE(socket_path.stat().st_mode) == SOCKET_MODE


def test_unknown_op(socket_path: Path) -> None:
    response = request(socket_path, {"op": "format-disk"})
    assert (response["ok"], response["error"]) == (False, "unknown-op")


def test_garbage_gets_bad_request(socket_path: Path) -> None:
    import socket

    with socket.socket(socket.AF_UNIX) as sock:
        sock.connect(str(socket_path))
        sock.sendall(b"not json\n")
        assert b'"bad-request"' in sock.recv(4096)


def test_stale_socket_file_is_replaced(tmp_path: Path) -> None:
    path = tmp_path / "control.sock"
    path.write_text("left over from a crash")

    async def go() -> None:
        ready = asyncio.Event()
        task = asyncio.create_task(serve(path, Supervisor(), ready))
        await ready.wait()
        assert stat.S_ISSOCK(path.stat().st_mode)
        task.cancel()

    asyncio.run(go())


def test_unreachable_supervisor_is_a_control_error(tmp_path: Path) -> None:
    with pytest.raises(ControlError):
        request(tmp_path / "nothing.sock", {"op": "status"})
