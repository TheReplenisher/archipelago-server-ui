"""Runtime settings, read from APSUI_* environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from apsui.same_origin import host_pattern

# frontend/dist in a source checkout: backend/src/apsui/config.py -> repo root
_SOURCE_TREE_STATIC = Path(__file__).resolve().parents[3] / "frontend" / "dist"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APSUI_")

    data_dir: Path = Path("/data")
    """Holds app.db, the apworld library, games and archives (DESIGN.md §2, data layout)."""

    jobs_dir: Path | None = None
    """Shared with the worker. Defaults to <data_dir>/jobs."""

    game_dir_path: Annotated[
        Path | None, Field(validation_alias=AliasChoices("APSUI_GAME_DIR", "game_dir_path"))
    ] = None
    """Shared with the server service (APSUI_GAME_DIR, as the supervisor reads it). Defaults
    to <data_dir>/game; the LXC install keeps it out of the web-only data folder (#14)."""

    job_poll_interval: float = 1.0
    """Seconds between checks for finished worker jobs."""

    control_socket: Path = Path("/run/apsui/control.sock")
    """The server supervisor's control socket (#70)."""

    relay_socket: Path = Path("/run/apsui/ap.sock")
    """The supervisor's relay to MultiServer, for the slot view's Archipelago connections
    (#30)."""

    max_slots: int = 50
    """The default slot limit (DESIGN.md §4), until the admin sets one on the settings
    page (#25)."""

    apworld_approval: Literal["manual", "auto"] = "manual"
    """The default for whether an apworld that passes its checks needs the admin's approval
    (DESIGN.md §4), until the admin sets it on the settings page (#25). One that replaces a
    built-in world always does."""

    archipelago_version: str = ""
    """The pinned Archipelago version, set in the image. Empty skips the apworld version
    range check in the web service; the worker's import test still applies it."""

    isolation: str = "none"
    """How the services are isolated, for the health page: "compose" (the three hardened
    containers), "lxc" (#14), or "none" (development: everything runs as one user)."""

    public_web_port: int | None = None
    public_game_port: int | None = None
    """The ports published on the host, which the containers can't see for themselves.
    Compose passes them in; shown on the health page."""

    @field_validator("public_web_port", "public_game_port", mode="before")
    @classmethod
    def _published_port(cls, value: object) -> object:
        """Compose passes what the admin published, which may name a host address too
        (127.0.0.1:8000, [::1]:8000): keep the port."""
        if isinstance(value, str) and ":" in value:
            return value.rsplit(":", 1)[1]
        return value

    feed_poll_interval: float = 0.5
    """Seconds between checks of MultiServer's log for the server feed."""

    command_catalog: Path | None = Path("/opt/apsui/commands.json")
    """The admin console's command catalog, built into the image (#26). Without it the
    console offers free text only."""

    static_dir: Path | None = None
    """Built frontend. Defaults to frontend/dist when running from a source checkout."""

    host: str = "0.0.0.0"  # noqa: S104 - the web service is meant to be reachable
    port: int = 8000
    forwarded_allow_ips: str = "127.0.0.1"
    """Reverse proxies whose X-Forwarded-* headers are trusted."""

    allowed_hosts: Annotated[list[str], NoDecode] = []
    """Names browsers may use to reach the web UI, besides IP addresses and local-only
    names (apsui.same_origin): comma-separated, `*.example.com` for its subdomains, `*`
    for any name, which turns off the check against DNS rebinding."""

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _host_names(cls, value: object) -> object:
        if isinstance(value, str):  # from the environment
            value = [v for v in value.split(",") if v.strip()]
        if isinstance(value, list):
            return [host_pattern(v) if isinstance(v, str) else v for v in value]
        return value

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
        return self.game_dir_path or self.data_dir / "game"

    @property
    def resolved_static_dir(self) -> Path | None:
        candidate = self.static_dir or _SOURCE_TREE_STATIC
        return candidate if (candidate / "index.html").is_file() else None


@lru_cache
def get_settings() -> Settings:
    return Settings()
