"""Starting, saving and stopping MultiServer, against a stand-in that behaves like its
console: it announces itself, then handles /save and /exit from stdin. The real
MultiServer runs in docker/compose-test.sh."""

import asyncio
import functools
import sys
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import pytest

from apsui_server import supervisor as supervisor_module
from apsui_server.supervisor import Supervisor

FAKE = """
import os, sys
from pathlib import Path
seen = Path(os.environ["XDG_DATA_HOME"]) / "commands.txt"
seen.parent.mkdir(parents=True, exist_ok=True)
print("Loading worlds", flush=True)
if "crash" in sys.argv[1]:
    print("Failed to read multiworld data", flush=True)
    sys.exit(3)
print("Hosting game at 0.0.0.0:" + sys.argv[sys.argv.index("--port") + 1], flush=True)
for line in sys.stdin:
    command = line.strip()
    with seen.open("a") as f:
        f.write(command + "\\n")
    if command == "/save":
        Path(sys.argv[1]).with_suffix(".apsave").write_text("saved")
        print("Game saved", flush=True)
    elif command == "/exit":
        sys.exit(0)
"""


def sync(test: Callable[..., Coroutine[Any, Any, None]]) -> Callable[..., None]:
    """Run an async test with asyncio.run (the package has no async test plugin)."""

    @functools.wraps(test)
    def wrapper(*args: Any, **kwargs: Any) -> None:
        asyncio.run(test(*args, **kwargs))

    return wrapper


@pytest.fixture
def make(tmp_path: Path) -> Callable[..., Supervisor]:
    archipelago = tmp_path / "archipelago"
    archipelago.mkdir()
    (archipelago / "MultiServer.py").write_text(FAKE)

    def make(output: str | None = "AP_123.zip") -> Supervisor:
        game = tmp_path / "game"
        if output:
            (game / "output").mkdir(parents=True, exist_ok=True)
            (game / "output" / output).write_bytes(b"zip")
        return Supervisor(game, archipelago, port=38999, python=sys.executable)

    return make


async def until(supervisor: Supervisor, state: str) -> dict[str, Any]:
    for _ in range(200):
        status = supervisor.status()
        if status["state"] == state:
            return status
        await asyncio.sleep(0.02)
    raise AssertionError(f"never reached {state}: {supervisor.status()}")


@sync
async def test_start_save_stop(make: Callable[..., Supervisor], tmp_path: Path) -> None:
    supervisor = make()
    started = await supervisor.handle({"op": "start"})
    assert (started["ok"], started["state"], started["multidata"]) == (
        True,
        "starting",
        "AP_123.zip",
    )
    await until(supervisor, "running")

    again = await supervisor.handle({"op": "start"})
    assert again["error"] == "already-running"

    assert (await supervisor.handle({"op": "save"}))["ok"] is True
    for _ in range(100):
        if (tmp_path / "game" / "output" / "AP_123.apsave").exists():
            break
        await asyncio.sleep(0.02)
    assert (tmp_path / "game" / "output" / "AP_123.apsave").read_text() == "saved"

    stopped = await supervisor.handle({"op": "stop"})
    assert (stopped["state"], stopped["exit_code"]) == ("stopped", 0)
    # Stop saves first, then exits; the custom worlds folder is the game's.
    commands = (tmp_path / "game" / "ap" / "commands.txt").read_text().split()
    assert commands == ["/save", "/save", "/exit"]
    assert (
        "Hosting game at 0.0.0.0:38999" in (tmp_path / "game" / "logs" / "server.log").read_text()
    )


@sync
async def test_a_crash_is_reported_with_the_log(make: Callable[..., Supervisor]) -> None:
    supervisor = make("AP_crash.zip")
    await supervisor.handle({"op": "start"})
    status = await until(supervisor, "crashed")
    assert status["exit_code"] == 3
    assert "Failed to read multiworld data" in status["log_tail"]
    # Stopping a crashed server just clears it.
    assert (await supervisor.handle({"op": "stop"}))["state"] == "stopped"


@sync
async def test_start_needs_a_generated_game(make: Callable[..., Supervisor]) -> None:
    response = await make(output=None).handle({"op": "start"})
    assert response["error"] == "no-output"


@sync
async def test_save_needs_a_running_server(make: Callable[..., Supervisor]) -> None:
    assert (await make().handle({"op": "save"}))["error"] == "not-running"


@sync
async def test_a_hung_server_is_terminated(
    make: Callable[..., Supervisor], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "archipelago" / "MultiServer.py").write_text(
        "import time\nprint('Hosting game at x', flush=True)\ntime.sleep(60)\n"
    )
    monkeypatch.setattr(supervisor_module, "STOP_TIMEOUT", 0.2)
    supervisor = make()
    await supervisor.handle({"op": "start"})
    await until(supervisor, "running")
    stopped = await supervisor.handle({"op": "stop"})
    assert stopped["state"] == "stopped" and stopped["exit_code"] != 0
