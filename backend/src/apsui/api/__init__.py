from fastapi import APIRouter

from apsui.api import game, health, server

router = APIRouter(prefix="/api")
router.include_router(health.router)
router.include_router(server.router)
router.include_router(game.router)
