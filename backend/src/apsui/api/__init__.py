from fastapi import APIRouter

from apsui.api import health

router = APIRouter(prefix="/api")
router.include_router(health.router)
