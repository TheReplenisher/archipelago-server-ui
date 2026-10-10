"""The server supervisor: owns MultiServer and answers the web service on the control
socket (#70, #24).

Operations: status, start, stop, save. MultiServer is driven through its own console on
stdin (/save, /exit), so no Archipelago connection is needed for these. It always gets an
explicit --host: without one it looks up the host's public IP over the internet.

The game's files are in the game folder (shared with the web service):
    output/AP_<seed>.zip   what generation produced (#18); the save file lands beside it
    ap/                    XDG_DATA_HOME: Archipelago/worlds/ holds the game's locked
                           custom apworlds, put there by the web service before a start
    logs/server.log        MultiServer's output
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import contextlib
import logging
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apsui_server.protocol import (
    DEFAULT_SOCKET,
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    ControlError,
    decode,
    encode,
)

log = logging.getLogger("apsui_server")

SOCKET_MODE = 0o660
"""Owner and group only. The web service shares the server's uid (Docker) or group (LXC)."""


STOP_TIMEOUT = 30.0
"""Seconds MultiServer gets to save and exit before it is terminated."""
LOG_TAIL_LINES = 40
READY_MARKER = "Hosting game at"


def error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": code, "message": message}


class Supervisor:
    """States: stopped, starting (loading worlds and the multidata), running, stopping,
    crashed (exited without being asked to; see log_tail)."""

    def __init__(
        self,
        game_dir: Path = Path("/data/game"),
        archipelago_dir: Path = Path("/opt/archipelago"),
        port: int = 38281,
        python: str = sys.executable,
    ) -> None:
        self.game_dir, self.archipelago_dir, self.port, self.python = (
            game_dir,
            archipelago_dir,
            port,
            python,
        )
        self.state = "stopped"
        self.process: asyncio.subprocess.Process | None = None
        self.multidata: str | None = None
        self.started_at: str | None = None
        self.exit_code: int | None = None
        self.log_tail: collections.deque[str] = collections.deque(maxlen=LOG_TAIL_LINES)
        self._tasks: set[asyncio.Task[None]] = set()

    async def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        op = request.get("op")
        if op == "status":
            return self.status()
        if op == "start":
            return await self.start()
        if op == "stop":
            return await self.stop()
        if op == "save":
            return await self.save()
        return error("unknown-op", f"Unknown operation {op!r}")

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "protocol": PROTOCOL_VERSION,
            "state": self.state,
            "archipelago_version": os.environ.get("ARCHIPELAGO_VERSION"),
            "multidata": self.multidata,
            "port": self.port,
            "started_at": self.started_at,
            "exit_code": self.exit_code,
            "log_tail": list(self.log_tail) if self.state == "crashed" else [],
        }

    def _alive(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def start(self) -> dict[str, Any]:
        if self._alive():
            return error("already-running", "The server is already running")
        outputs = sorted((self.game_dir / "output").glob("AP_*.zip"))
        if len(outputs) != 1:
            return error("no-output", "There is no generated game to host")
        logs = self.game_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        env = os.environ | {"XDG_DATA_HOME": str(self.game_dir / "ap")}
        self.log_tail.clear()
        self.process = await asyncio.create_subprocess_exec(
            self.python,
            str(self.archipelago_dir / "MultiServer.py"),
            str(outputs[0]),
            "--host", "0.0.0.0",  # noqa: S104 - players connect from anywhere
            "--port", str(self.port),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=self.archipelago_dir,
            env=env,
            start_new_session=True,
        )  # fmt: skip
        self.state, self.exit_code = "starting", None
        self.multidata, self.started_at = outputs[0].name, datetime.now(UTC).isoformat()
        log.info("MultiServer started (pid %s) for %s", self.process.pid, outputs[0].name)
        self._spawn(self._watch(self.process, logs / "server.log"))
        return self.status()

    async def stop(self) -> dict[str, Any]:
        process = self.process
        if process is None or process.returncode is not None:
            self.state = "stopped"
            return self.status()
        self.state = "stopping"
        await self._send(process, "/save", "/exit")
        try:
            await asyncio.wait_for(process.wait(), STOP_TIMEOUT)
        except TimeoutError:
            log.warning("MultiServer didn't exit in %ss; terminating it", STOP_TIMEOUT)
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), 10)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
        self.state = "stopped"
        return self.status()

    async def save(self) -> dict[str, Any]:
        if not self._alive() or self.state != "running":
            return error("not-running", "The server isn't running")
        assert self.process is not None  # noqa: S101 - _alive() checked it
        await self._send(self.process, "/save")
        return self.status()

    async def _send(self, process: asyncio.subprocess.Process, *commands: str) -> None:
        if process.stdin is None:
            return
        with contextlib.suppress(ConnectionError):
            process.stdin.write("".join(f"{c}\n" for c in commands).encode())
            await process.stdin.drain()

    async def _watch(self, process: asyncio.subprocess.Process, log_path: Path) -> None:
        """Copy MultiServer's output to its log, notice when it is up, and when it exits."""
        assert process.stdout is not None  # noqa: S101 - started with stdout=PIPE
        with open(log_path, "ab") as log_file:  # noqa: ASYNC230 - small local writes
            async for raw in process.stdout:
                log_file.write(raw)
                log_file.flush()
                line = raw.decode("utf-8", "replace").rstrip()
                self.log_tail.append(line)
                if self.state == "starting" and READY_MARKER in line:
                    self.state = "running"
        self.exit_code = await process.wait()
        if process is self.process and self.state != "stopping":
            log.warning("MultiServer exited unexpectedly with %s", self.exit_code)
            self.state = "crashed"

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def shutdown(self) -> None:
        """The supervisor is stopping: save and stop MultiServer too."""
        if self._alive():
            await self.stop()


async def serve(
    socket_path: Path, supervisor: Supervisor, ready: asyncio.Event | None = None
) -> None:
    async def connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=10)
            response = await supervisor.handle(decode(line))
        except (ControlError, TimeoutError, ValueError) as exc:
            response = {"ok": False, "error": "bad-request", "message": str(exc)}
        try:
            writer.write(encode(response))
            await writer.drain()
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    _prepare(socket_path)
    server = await asyncio.start_unix_server(
        connection, path=str(socket_path), limit=MAX_MESSAGE_BYTES
    )
    os.chmod(socket_path, SOCKET_MODE)
    log.info("control socket listening at %s", socket_path)
    if ready is not None:
        ready.set()
    try:
        async with server:
            await server.serve_forever()
    finally:
        _remove(socket_path)


# Quick local filesystem calls, kept out of the coroutines.
def _prepare(socket_path: Path) -> None:
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)  # left over from a crash


def _remove(socket_path: Path) -> None:
    socket_path.unlink(missing_ok=True)


async def run(socket_path: Path, supervisor: Supervisor) -> None:
    task = asyncio.create_task(serve(socket_path, supervisor))
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await supervisor.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Archipelago Server UI server supervisor")
    parser.add_argument(
        "--socket", type=Path, default=Path(os.environ.get("APSUI_CONTROL_SOCKET", DEFAULT_SOCKET))
    )
    parser.add_argument(
        "--game-dir", type=Path, default=Path(os.environ.get("APSUI_GAME_DIR", "/data/game"))
    )
    parser.add_argument(
        "--archipelago-dir",
        type=Path,
        default=Path(os.environ.get("APSUI_ARCHIPELAGO_DIR", "/opt/archipelago")),
    )
    parser.add_argument("--port", type=int, default=int(os.environ.get("APSUI_GAME_PORT", "38281")))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    supervisor = Supervisor(args.game_dir, args.archipelago_dir, args.port)
    asyncio.run(run(args.socket, supervisor))


if __name__ == "__main__":
    main()
