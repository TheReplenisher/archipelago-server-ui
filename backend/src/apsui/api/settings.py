from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from apsui import host_settings, hosting
from apsui.api.game import SessionDep
from apsui.host_settings import HostSettings
from apsui.lifecycle import GameState, current_game

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsOut(BaseModel):
    values: HostSettings
    fields: list[dict[str, Any]]
    """Label, help, group, input kind, choices and limits of each setting, and when it
    applies: live (at once on a running server), start, generation or upload."""
    reset: list[str]
    """Stored settings that no longer validate (after an update, say) and are shown at
    their defaults until the next save."""


class Saved(BaseModel):
    values: HostSettings
    applied_now: list[str]
    """The live settings that changed and reached the running server through /option.
    Everything else applies at the next start, generation or upload."""


@router.get("")
def get_settings(request: Request, session: SessionDep) -> SettingsOut:
    values, reset = host_settings.load_checked(session, request.app.state.settings)
    return SettingsOut(values=values, fields=host_settings.fields(), reset=reset)


@router.put("")
async def put_settings(values: HostSettings, request: Request, session: SessionDep) -> Saved:
    """Save the settings. While the server runs, the live ones that changed are applied at
    once; if one can't be, it still applies at the next start."""
    settings = request.app.state.settings
    old = host_settings.load(session, settings)
    host_settings.save(session, values)
    applied = []
    if current_game(session).state == GameState.RUNNING:
        for key, line in host_settings.live_commands(old, values).items():
            try:
                await hosting.command(session, settings, line)
            except hosting.HostingError:
                continue
            applied.append(key)
    return Saved(values=values, applied_now=applied)
