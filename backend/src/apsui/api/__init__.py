from fastapi import APIRouter

from apsui.api import game, health, server, uploads

router = APIRouter(prefix="/api")
router.include_router(health.router)
router.include_router(server.router)
router.include_router(game.router)
router.include_router(uploads.router)
