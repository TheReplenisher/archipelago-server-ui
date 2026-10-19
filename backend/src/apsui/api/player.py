"""The Player tab's uploads (#33): open to everyone while the game is Open and the admin
lets players upload. See apsui.player_uploads."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from apsui import host_settings
from apsui.api.game import SessionDep
from apsui.apworlds import MAX_APWORLD_BYTES, ApworldError, submit_apworld
from apsui.apworlds import label as apworld_label
from apsui.config import Settings
from apsui.lifecycle import GameState, current_game
from apsui.models import Apworld, Slot
from apsui.player_uploads import (
    PLAYER,
    PlayerError,
    UploadLimiter,
    apworld_view,
    check_apworld_room,
    new_receipt,
    own_apworld,
    own_upload,
    uploads_open,
    yaml_view,
)
from apsui.uploads import (
    MAX_YAML_BYTES,
    UploadError,
    cancel,
    remove_upload,
    rename,
    slot_count,
    submit_yaml,
)
from apsui.worlds import label as lock_label
from apsui.worlds import locks

router = APIRouter(prefix="/player", tags=["player"])

MAX_RECEIPTS = 50


def _error(exc: PlayerError | UploadError | ApworldError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message})


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _limiter(request: Request) -> UploadLimiter:
    limiter: UploadLimiter = request.app.state.player_uploads
    return limiter


class PlayerGame(BaseModel):
    state: GameState
    uploads_open: bool
    """Players can upload now: the game is Open and the admin allows it."""
    player_uploads: bool
    """The admin's *Anyone can upload* setting."""
    apworld_approval: Literal["manual", "auto"]
    """Whether players' apworlds wait for the admin."""
    max_slots: int
    slots_used: int
    taken_names: list[str]
    """Slot names already in this game: a new one must differ (without case)."""


@router.get("/game")
def player_game(request: Request, session: SessionDep) -> PlayerGame:
    settings: Settings = request.app.state.settings
    values = host_settings.load(session, settings)
    game = current_game(session)
    names = session.scalars(select(Slot.name).where(Slot.game_id == game.id).order_by(Slot.id))
    return PlayerGame(
        state=GameState(game.state),
        uploads_open=values.player_uploads and game.state == GameState.OPEN,
        player_uploads=values.player_uploads,
        apworld_approval=values.player_apworld_approval,
        max_slots=values.max_slots,
        slots_used=slot_count(session, game.id),
        taken_names=list(names),
    )


class LibraryApworld(BaseModel):
    id: int
    label: str
    game: str
    replaces_builtin: bool


class LockedWorld(BaseModel):
    world: str
    label: str


class Library(BaseModel):
    apworlds: list[LibraryApworld]
    """The approved custom apworlds a YAML can pick."""
    locked: list[LockedWorld]
    """Games this multiworld is already locked to a version of."""


@router.get("/library")
def player_library(request: Request, session: SessionDep) -> Library:
    settings: Settings = request.app.state.settings
    approved = session.scalars(
        select(Apworld).where(Apworld.status == "approved").order_by(Apworld.game, Apworld.id)
    )
    game = current_game(session)
    return Library(
        apworlds=[
            LibraryApworld(
                id=a.id,
                label=apworld_label(a),
                game=a.game or "",
                replaces_builtin=a.replaces_builtin is not None,
            )
            for a in approved
        ],
        locked=[
            LockedWorld(world=lock.world, label=lock_label(settings, lock))
            for lock in locks(session, game.id)
        ],
    )


class Receipt(BaseModel):
    kind: Literal["yaml", "apworld"]
    id: int
    receipt: str = Field(max_length=64)


class Uploaded(BaseModel):
    receipt: str
    """Keep it: it is the only way to see this upload's result, rename or withdraw it."""
    upload: dict[str, Any]


@router.post("/yaml", status_code=202)
async def player_yaml(
    request: Request,
    file: UploadFile,
    session: SessionDep,
    apworld_ids: Annotated[list[int] | None, Form()] = None,
) -> Uploaded:
    """Upload a YAML as a player. It gets every check the admin's do; poll
    POST /api/player/receipts for the result."""
    settings: Settings = request.app.state.settings
    try:
        uploads_open(session, settings)
        _limiter(request).check("yaml", _client(request))
        data = await file.read(MAX_YAML_BYTES + 1)
        token, digest = new_receipt()
        upload = submit_yaml(
            session,
            request.app.state.jobs,
            settings,
            file.filename or "",
            data,
            apworld_ids or [],
            uploaded_by=PLAYER,
            uploaded_from=_client(request),
            receipt_hash=digest,
        )
    except (PlayerError, UploadError) as exc:
        raise _error(exc) from exc
    return Uploaded(receipt=token, upload=yaml_view(session, upload))


@router.post("/apworld", status_code=202)
async def player_apworld(request: Request, file: UploadFile, session: SessionDep) -> Uploaded:
    """Upload an apworld as a player. It is inspected and import-tested, then waits for
    the admin (unless the admin approves players' apworlds automatically)."""
    settings: Settings = request.app.state.settings
    try:
        uploads_open(session, settings)
        check_apworld_room(session)
        _limiter(request).check("apworld", _client(request))
        data = await file.read(MAX_APWORLD_BYTES + 1)
        token, digest = new_receipt()
        apworld = submit_apworld(
            session,
            request.app.state.jobs,
            settings,
            file.filename or "",
            data,
            uploaded_by=PLAYER,
            uploaded_from=_client(request),
            receipt_hash=digest,
        )
    except (PlayerError, ApworldError) as exc:
        raise _error(exc) from exc
    return Uploaded(receipt=token, upload=apworld_view(apworld))


class ReceiptsIn(BaseModel):
    receipts: list[Receipt] = Field(max_length=MAX_RECEIPTS)


@router.post("/receipts")
def player_receipts(body: ReceiptsIn, session: SessionDep) -> list[dict[str, Any]]:
    """The uploads these receipts are for, as the player sees them. A receipt that matches
    nothing is left out. (POST, so receipts stay out of URLs and proxy logs.)"""
    found = []
    for receipt in body.receipts:
        try:
            if receipt.kind == "yaml":
                found.append(yaml_view(session, own_upload(session, receipt.id, receipt.receipt)))
            else:
                found.append(apworld_view(own_apworld(session, receipt.id, receipt.receipt)))
        except PlayerError:
            continue
    return found


class ReceiptIn(BaseModel):
    receipt: str = Field(max_length=64)


class NameIn(BaseModel):
    document: int
    name: str = Field(max_length=64)


class PlayerRenameIn(ReceiptIn):
    names: list[NameIn] = Field(max_length=100)


@router.post("/yaml/{upload_id}/rename", status_code=202)
def player_rename(
    upload_id: int, body: PlayerRenameIn, request: Request, session: SessionDep
) -> dict[str, Any]:
    """New slot names for the player's own upload waiting for them; it is checked again."""
    settings: Settings = request.app.state.settings
    try:
        uploads_open(session, settings)
        upload = own_upload(session, upload_id, body.receipt)
        names = {n.document: n.name for n in body.names}
        upload = rename(session, request.app.state.jobs, settings, upload.id, names)
    except (PlayerError, UploadError) as exc:
        raise _error(exc) from exc
    return yaml_view(session, upload)


@router.post("/yaml/{upload_id}/withdraw")
def player_withdraw(
    upload_id: int, body: ReceiptIn, request: Request, session: SessionDep
) -> dict[str, Any]:
    """Take back the player's own YAML while uploads are open: an accepted one frees its
    slots; one waiting for a name is cancelled."""
    settings: Settings = request.app.state.settings
    try:
        uploads_open(session, settings)
        upload = own_upload(session, upload_id, body.receipt)
        if upload.status == "needs-name":
            upload = cancel(session, settings, upload.id)
        else:
            upload = remove_upload(session, settings, upload.id)
    except (PlayerError, UploadError) as exc:
        raise _error(exc) from exc
    return yaml_view(session, upload)
