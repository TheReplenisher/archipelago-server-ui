"""Runtime settings, read from APSUI_* environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# frontend/dist in a source checkout: backend/src/apsui/config.py -> repo root
_SOURCE_TREE_STATIC = Path(__file__).resolve().parents[3] / "frontend" / "dist"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APSUI_")

    data_dir: Path = Path("/data")
    """Holds app.db, the apworld library, games and archives (DESIGN.md §2, data layout)."""

    jobs_dir: Path | None = None
    """Shared with the worker. Defaults to <data_dir>/jobs."""

    job_poll_interval: float = 1.0
    """Seconds between checks for finished worker jobs."""

    control_socket: Path = Path("/run/apsui/control.sock")
    """The server supervisor's control socket (#70)."""

    max_slots: int = 50
    """The most player slots one game may have (DESIGN.md §4). Moves to the settings page
    with #25."""

    apworld_approval: Literal["manual", "auto"] = "manual"
    """Whether an apworld that passes its checks needs the admin's approval (DESIGN.md §4).
    One that replaces a built-in world always does. Moves to the settings page with #25."""

    archipelago_version: str = ""
    """The pinned Archipelago version, set in the image. Empty skips the apworld version
    range check in the web service; the worker's import test still applies it."""

    static_dir: Path | None = None
    """Built frontend. Defaults to frontend/dist when running from a source checkout."""

    host: str = "0.0.0.0"  # noqa: S104 - the web service is meant to be reachable
    port: int = 8000
    forwarded_allow_ips: str = "127.0.0.1"
    """Reverse proxies whose X-Forwarded-* headers are trusted."""

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'app.db'}"

    @property
    def resolved_jobs_dir(self) -> Path:
        return self.jobs_dir or self.data_dir / "jobs"

    @property
    def uploads_dir(self) -> Path:
        """Files waiting for their checks. Web service only."""
        return self.data_dir / "uploads"

    @property
    def library_dir(self) -> Path:
        """Approved apworlds, stored by hash. Web service only."""
        return self.data_dir / "library" / "apworlds"

    @property
    def game_dir(self) -> Path:
        """The current game's files, shared with the server service."""
        return self.data_dir / "game"

    @property
    def resolved_static_dir(self) -> Path | None:
        candidate = self.static_dir or _SOURCE_TREE_STATIC
        return candidate if (candidate / "index.html").is_file() else None


@lru_cache
def get_settings() -> Settings:
    return Settings()
