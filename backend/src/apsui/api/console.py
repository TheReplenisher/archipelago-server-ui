from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from apsui import console
from apsui.api.game import SessionDep
from apsui.generation import output_dir
from apsui.lifecycle import GameState, current_game

router = APIRouter(prefix="/console", tags=["console"])


@router.get("/commands")
def list_commands(request: Request) -> list[console.Command]:
    """Every command the admin console offers, with what each argument is. Empty without
    a catalog (a development setup): the console still takes free text."""
    return console.commands(request.app.state.settings)


@router.get("/names", response_model=console.Names)
def get_names(request: Request, session: SessionDep) -> FileResponse:
    """The generated game's slots, and each game's item and location names, for the
    console's searchable lists. Parsed when stored, so it's served as it is."""
    if current_game(session).state not in (GameState.GENERATED, GameState.RUNNING):
        detail = {"code": "no-output", "message": "The game hasn't been generated"}
        raise HTTPException(409, detail=detail)
    path = output_dir(request.app.state.settings) / console.NAMES_FILE
    if not path.is_file():
        message = "This game was generated without the console's names"
        raise HTTPException(404, detail={"code": "no-names", "message": message})
    return FileResponse(path, media_type="application/json")
