"""Run a real supervisor on a socket in a background thread, for tests (here and in the
web service's tests)."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Iterator
from pathlib import Path

from apsui_server.supervisor import Supervisor, serve


@contextlib.contextmanager
def running_supervisor(socket_path: Path, supervisor: Supervisor | None = None) -> Iterator[Path]:
    started = threading.Event()
    running: list[tuple[asyncio.AbstractEventLoop, asyncio.Task[None]]] = []

    async def main() -> None:
        ready = asyncio.Event()
        task = asyncio.create_task(serve(socket_path, supervisor or Supervisor(), ready))
        running.append((asyncio.get_running_loop(), task))
        await ready.wait()
        started.set()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    thread = threading.Thread(target=asyncio.run, args=(main(),), daemon=True)
    thread.start()
    if not started.wait(timeout=5):
        raise RuntimeError("supervisor did not start")
    try:
        yield socket_path
    finally:
        loop, task = running[0]
        loop.call_soon_threadsafe(task.cancel)
        thread.join(timeout=5)
