"""Runtime settings, read from APSUI_* environment variables."""

from functools import lru_cache
from pathlib import Path

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
    def resolved_static_dir(self) -> Path | None:
        candidate = self.static_dir or _SOURCE_TREE_STATIC
        return candidate if (candidate / "index.html").is_file() else None


@lru_cache
def get_settings() -> Settings:
    return Settings()
