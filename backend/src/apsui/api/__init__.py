from fastapi import APIRouter

from apsui.api import health, server

router = APIRouter(prefix="/api")
router.include_router(health.router)
router.include_router(server.router)
