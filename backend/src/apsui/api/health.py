from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from apsui import __version__
from apsui.db import get_session

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: Literal["ok"]
    version: str
    database: Literal["ok"]


@router.get("/health")
def health(session: Annotated[Session, Depends(get_session)]) -> Health:
    # The full health page (services, ports, disk, AP version, isolation) is #31.
    session.execute(text("SELECT 1"))
    return Health(status="ok", version=__version__, database="ok")
