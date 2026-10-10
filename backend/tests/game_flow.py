"""Moves a game through uploads and generation in tests, playing the worker."""

import io
import zipfile
from typing import Any

from apsui_worker.protocol import OUTPUT_DIR, State
from fastapi.testclient import TestClient
from worker_sim import worker_finishes

from apsui.jobs import JobQueue


def accept_yaml(
    client: TestClient, name: str, game: str = "APQuest", apworld_ids: list[int] | None = None
) -> int:
    yaml = f"name: {name}\ngame: {game}\n{game}: {{}}\n".encode()
    response = client.post(
        "/api/uploads/yaml",
        files={"file": (f"{name.lower()}.yaml", yaml)},
        data={"apworld_ids": [str(i) for i in apworld_ids or []]},
    )
    assert response.status_code == 202, response.text
    doc = {"index": 0, "empty": False, "name": name, "name_raw": name, "games": [game]}
    worker_finishes(
        client, {"validate-yaml": {"error": None, "documents": [doc], "custom_games": [game]}}
    )
    upload_id: int = response.json()["id"]
    return upload_id


def output_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        # A fixed timestamp, so every call gives the same bytes.
        zf.writestr(zipfile.ZipInfo("AP_12345.archipelago", (2026, 1, 1, 0, 0, 0)), b"multidata")
    return buffer.getvalue()


def generated(players: list[str]) -> dict[str, Any]:
    """A generate result that also writes the output zip, as the worker would."""

    def output(spec: dict[str, Any]) -> dict[str, Any]:
        return {
            "archipelago_version": "0.6.8",
            "seed": 1,
            "seed_name": "12345",
            "zip": "AP_12345.zip",
            "players": players,
        }

    return {"generate": output}


def finish_with_zip(
    client: TestClient, players: list[str], data: bytes | None = None
) -> list[dict[str, Any]]:
    jobs: JobQueue = client.app.state.jobs  # type: ignore[attr-defined]
    for job_id in jobs.dirs.ids(State.QUEUE):
        out = jobs.dirs.path(State.QUEUE, job_id) / OUTPUT_DIR
        out.mkdir(exist_ok=True)
        (out / "AP_12345.zip").write_bytes(output_zip() if data is None else data)
    return worker_finishes(client, generated(players))


def generated_game(client: TestClient, *names: str) -> None:
    """Accept a YAML per name, lock and generate: the game ends up Generated."""
    for name in names:
        accept_yaml(client, name)
    client.post("/api/game/lock")
    client.post("/api/game/generate")
    finish_with_zip(client, list(names))
