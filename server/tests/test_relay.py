"""The relay socket (#30): the web service's Archipelago connections are piped to
MultiServer's game port, only while it runs. A local echo server stands in for it."""

import asyncio
import stat
from pathlib import Path

from apsui_server.supervisor import SOCKET_MODE, Supervisor, serve


async def echo_server() -> tuple[asyncio.Server, int]:
    async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while data := await reader.read(1024):
            writer.write(data)
            await writer.drain()
        writer.close()

    server = await asyncio.start_server(echo, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def with_supervisor(tmp_path: Path, state: str) -> bytes:
    game_port_server, port = await echo_server()
    supervisor = Supervisor(tmp_path / "game", port=port)
    supervisor.state = state
    ready = asyncio.Event()
    relay = tmp_path / "run" / "ap.sock"
    task = asyncio.create_task(serve(tmp_path / "run" / "control.sock", supervisor, ready, relay))
    await ready.wait()
    assert stat.S_IMODE(relay.stat().st_mode) == SOCKET_MODE
    try:
        reader, writer = await asyncio.open_unix_connection(str(relay))
        try:
            writer.write(b"GET / HTTP/1.1\r\n\r\n")
            await writer.drain()
            async with asyncio.timeout(5):
                return await reader.read(1024)
        except ConnectionResetError:  # closed on us: refused, like an empty read
            return b""
        finally:
            writer.close()
    finally:
        task.cancel()
        game_port_server.close()


def test_the_relay_pipes_to_the_game_port_while_running(tmp_path: Path) -> None:
    assert asyncio.run(with_supervisor(tmp_path, "running")) == b"GET / HTTP/1.1\r\n\r\n"


def test_the_relay_closes_while_the_server_is_stopped(tmp_path: Path) -> None:
    assert asyncio.run(with_supervisor(tmp_path, "stopped")) == b""
