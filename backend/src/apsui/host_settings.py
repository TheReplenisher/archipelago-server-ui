"""The settings page (DESIGN.md §5, host.yaml settings; #25).

The admin's settings live in app.db (DESIGN.md §2). They reach Archipelago three ways:

- **Server** settings are written as host.yaml's `server_options` into the server's own
  Archipelago user folder before each start; MultiServer reads its defaults from there.
  The ones marked live also apply at once to a running server, through `/option`.
- **Generation** settings go into each generate job's parameters, and the YAML checks
  use the same plando options and quantity rule.
- **Uploads** settings (the slot limit, apworld approval) are read by the upload checks.
- **Archives** settings (retention) are applied each time a game is archived (#19).

The hidden ones (host, port, file paths, logtime, players, disable_save) are set by the
backend and supervisor, never here.
"""

from __future__ import annotations

import json
import logging
import shlex
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from sqlalchemy.orm import Session

from apsui.config import Settings
from apsui.models import Setting

log = logging.getLogger(__name__)

KEY = "host"

Password = Annotated[str, StringConstraints(max_length=64, pattern=r"^[^\x00-\x1f\x7f]*$")]
ReleaseMode = Literal["auto", "enabled", "disabled", "goal", "auto-enabled"]
PlandoOption = Literal["bosses", "items", "texts", "connections"]


class HostSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Server
    password: Password = ""
    server_password: Password = ""
    release_mode: ReleaseMode = "auto"
    collect_mode: ReleaseMode = "auto"
    remaining_mode: Literal["enabled", "disabled", "goal"] = "goal"
    countdown_mode: Literal["enabled", "disabled", "auto"] = "auto"
    hint_cost: int = Field(default=10, ge=0, le=100)
    location_check_points: int = Field(default=1, ge=0, le=1000)
    disable_item_cheat: bool = True
    compatibility: Literal[0, 2] = 2
    auto_shutdown: int = Field(default=0, ge=0, le=7 * 24 * 3600)
    # Generation
    spoiler: Literal[0, 1, 2, 3] = 3
    race: bool = False
    plando_options: list[PlandoOption] = ["bosses", "connections", "texts"]
    panic_method: Literal["swap", "raise", "start_inventory"] = "swap"
    # Uploads
    max_slots: int = Field(default=50, ge=1, le=1000)
    apworld_approval: Literal["manual", "auto"] = "manual"
    # Archives
    archive_limit: Literal["none", "count", "size"] = "none"
    archive_max_count: int = Field(default=20, ge=1, le=10_000)
    archive_max_size_mb: int = Field(default=10_240, ge=1, le=10_000_000)
    # Advanced
    loglevel: Literal["debug", "info", "warning", "error", "critical"] = "info"
    log_network: bool = False
    allow_quantity: bool = False


@dataclass(frozen=True)
class FieldInfo:
    key: str
    label: str
    help: str
    group: Literal["server", "generation", "uploads", "archives", "advanced"]
    kind: Literal["text", "password", "number", "bool", "choice", "multi"]
    applies: Literal["live", "start", "generation", "upload", "archive"]
    """live: at once on a running server (and at every start); else at the next one."""
    choices: list[dict[str, Any]] = field(default_factory=list)
    min: int | None = None
    max: int | None = None
    warning: str | None = None


def _choices(*pairs: tuple[Any, str]) -> list[dict[str, Any]]:
    return [{"value": v, "label": label} for v, label in pairs]


_MODES = _choices(
    ("disabled", "Disabled"),
    ("enabled", "Enabled"),
    ("auto", "Automatic on goal"),
    ("auto-enabled", "Automatic on goal, and enabled"),
    ("goal", "Allowed after goal"),
)

FIELDS: list[FieldInfo] = [
    FieldInfo("password", "Room password", "Players need it to join. Empty: no password.",
              "server", "password", "live"),
    FieldInfo("server_password", "Server password",
              "Lets a client run admin commands with !admin. Empty: nobody can.",
              "server", "password", "live"),
    FieldInfo("release_mode", "Release", "Sending out the remaining items from a player's "
              "world.", "server", "choice", "live", _MODES),
    FieldInfo("collect_mode", "Collect", "Sending a player the remaining items for their "
              "world.", "server", "choice", "live", _MODES),
    FieldInfo("remaining_mode", "!remaining", "Asking which of your items are still out "
              "there.", "server", "choice", "live",
              _choices(("enabled", "Enabled"), ("disabled", "Disabled"),
                       ("goal", "After goal"))),
    FieldInfo("countdown_mode", "!countdown", "Players starting a countdown. Automatic "
              "allows it in rooms of under 30 slots; /countdown always works for the admin.",
              "server", "choice", "live",
              _choices(("enabled", "Enabled"), ("disabled", "Disabled"),
                       ("auto", "Automatic"))),
    FieldInfo("hint_cost", "Hint cost", "Percent of a player's checks a hint costs.",
              "server", "number", "live", min=0, max=100),
    FieldInfo("location_check_points", "Points per check", "Hint points earned for each "
              "location checked.", "server", "number", "live", min=0, max=1000),
    FieldInfo("disable_item_cheat", "Turn off !getitem", "On: players can't give "
              "themselves items. Archipelago's own default is off.", "server", "bool", "live"),
    FieldInfo("compatibility", "Client compatibility", "Which client versions may connect.",
              "server", "choice", "live",
              _choices((2, "Any version (casual and co-op)"), (0, "Exact version (tournaments)"))),
    FieldInfo("auto_shutdown", "Stop when idle after (seconds)", "Stop the server after "
              "this long without a new location check; it shows as stopped (idle). 0: never.",
              "server", "number", "start", min=0, max=7 * 24 * 3600),
    FieldInfo("spoiler", "Spoiler log", "How much the spoiler log holds.", "generation",
              "choice", "generation",
              _choices((0, "None"), (1, "Item placements"), (2, "With the playthrough"),
                       (3, "With the playthrough and paths"))),
    FieldInfo("race", "Race mode", "A secure random seed, and the game marked as a race, so "
              "tools that respect it hide what would help a player.", "generation", "bool",
              "generation"),
    FieldInfo("plando_options", "Plando", "Which plando sections player YAMLs may use. "
              "Also used to check uploads.", "generation", "multi", "generation",
              _choices(("bosses", "Bosses"), ("items", "Items"), ("texts", "Texts"),
                       ("connections", "Connections"))),
    FieldInfo("panic_method", "When the fill gets stuck", "What the generator does when "
              "it can't place the remaining items.", "generation", "choice", "generation",
              _choices(("swap", "Swap items to make room"), ("raise", "Fail the generation"),
                       ("start_inventory", "Give them as starting items"))),
    FieldInfo("max_slots", "Slot limit", "The most slots one game may have.", "uploads",
              "number", "upload", min=1, max=1000),
    FieldInfo("apworld_approval", "Apworld approval", "Whether an apworld that passes its "
              "checks needs your approval. One that replaces a built-in world always does.",
              "uploads", "choice", "upload",
              _choices(("manual", "Manual"), ("auto", "Automatic"))),
    FieldInfo("archive_limit", "Archive limit", "Each time a game is archived, the oldest "
              "archives are deleted until the rest fit. The newest is always kept.",
              "archives", "choice", "archive",
              _choices(("none", "No limit"), ("count", "Number of archives"),
                       ("size", "Total size"))),
    FieldInfo("archive_max_count", "Archives to keep", "Used when the limit is the number "
              "of archives.", "archives", "number", "archive", min=1, max=10_000),
    FieldInfo("archive_max_size_mb", "Total archive size (MB)", "Used when the limit is the "
              "total size.", "archives", "number", "archive", min=1, max=10_000_000),
    FieldInfo("loglevel", "Server log level", "How much the server feed shows.", "advanced",
              "choice", "start",
              _choices(("debug", "Debug"), ("info", "Info"), ("warning", "Warning"),
                       ("error", "Error"), ("critical", "Critical"))),
    FieldInfo("log_network", "Log network traffic", "Every message to and from clients.",
              "advanced", "bool", "start", warning="Very large logs: for debugging only."),
    FieldInfo("allow_quantity", "Allow quantity", "YAMLs may ask for several slots with "
              "quantity; each one counts toward the slot limit.", "advanced", "bool",
              "upload"),
]  # fmt: skip

LIVE = [f.key for f in FIELDS if f.applies == "live"]


def defaults(settings: Settings) -> HostSettings:
    """Archipelago's defaults (but !getitem off), and the install's for the uploads."""
    return HostSettings(max_slots=settings.max_slots, apworld_approval=settings.apworld_approval)


def load(session: Session, settings: Settings) -> HostSettings:
    return load_checked(session, settings)[0]


def load_checked(session: Session, settings: Settings) -> tuple[HostSettings, list[str]]:
    """The stored settings, each checked on its own (#95): a value that no longer
    validates (an update dropped a choice, narrowed a range or renamed the key) falls back
    to its default, and only that one. Returns the keys that fell back, so the settings
    page can say so; they stay that way until the admin saves."""
    stored = session.get(Setting, KEY)
    base = defaults(settings).model_dump()
    values = dict(stored.value) if stored is not None else {}
    kept, reset = dict(base), []
    for key, value in values.items():
        if key not in HostSettings.model_fields:
            reset.append(key)
            continue
        try:
            HostSettings.model_validate(base | {key: value})
        except ValidationError:
            reset.append(key)
            continue
        kept[key] = value
    if reset:
        log.warning("Stored settings reset to their defaults: %s", ", ".join(reset))
    return HostSettings.model_validate(kept), reset


def save(session: Session, values: HostSettings) -> None:
    row = session.get(Setting, KEY)
    if row is None:
        session.add(Setting(key=KEY, value=values.model_dump()))
    else:
        row.value = values.model_dump()
    session.commit()


def fields() -> list[dict[str, Any]]:
    return [asdict(f) for f in FIELDS]


def server_options(values: HostSettings) -> dict[str, Any]:
    """host.yaml's server_options. Empty passwords are null: no password."""
    return {
        "password": values.password or None,
        "server_password": values.server_password or None,
        "release_mode": values.release_mode,
        "collect_mode": values.collect_mode,
        "remaining_mode": values.remaining_mode,
        "countdown_mode": values.countdown_mode,
        "hint_cost": values.hint_cost,
        "location_check_points": values.location_check_points,
        "disable_item_cheat": values.disable_item_cheat,
        "compatibility": values.compatibility,
        "auto_shutdown": values.auto_shutdown,
        "loglevel": values.loglevel,
        "log_network": int(values.log_network),
    }


def write_host_yaml(values: HostSettings, user_dir: Path) -> None:
    """The server's host.yaml, in its Archipelago user folder (XDG_DATA_HOME). JSON is
    YAML, so the values need no YAML library and can't break out of their keys."""
    user_dir.mkdir(parents=True, exist_ok=True)
    text = "server_options:\n" + "".join(
        f"  {key}: {json.dumps(value)}\n" for key, value in server_options(values).items()
    )
    (user_dir / "host.yaml").write_text(text, encoding="utf-8")
    (user_dir / "options.yaml").unlink(missing_ok=True)  # AP would read it first


def live_commands(old: HostSettings, new: HostSettings) -> dict[str, str]:
    """The /option line for each live setting that changed, by key."""
    lines = {}
    for key in LIVE:
        value = getattr(new, key)
        if value == getattr(old, key):
            continue
        if key == "disable_item_cheat":
            name, text = "item_cheat", "false" if value else "true"
        elif key in ("password", "server_password"):
            name, text = key, value or "none"
        elif key in ("release_mode", "collect_mode"):
            name, text = key, value.replace("-", "_")  # what /option accepts; same meaning
        else:
            name, text = key, str(value)
        lines[key] = f"/option {name} {shlex.quote(text)}"
    return lines


def generate_params(values: HostSettings) -> dict[str, Any]:
    return {
        "spoiler": values.spoiler,
        "race": values.race,
        "plando_options": ", ".join(values.plando_options),
        "panic_method": values.panic_method,
    }


def validate_params(values: HostSettings) -> dict[str, Any]:
    """The YAML checks use generation's plando options and the quantity rule."""
    return {
        "plando_options": ", ".join(values.plando_options),
        "allow_quantity": values.allow_quantity,
    }
