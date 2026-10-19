from fastapi import APIRouter, Depends

from apsui.api import (
    admin,
    apworlds,
    archives,
    audit_log,
    console,
    game,
    health,
    logs,
    server,
    settings,
    slot,
    uploads,
)
from apsui.api.admin import require_admin

router = APIRouter(prefix="/api")
# Open to everyone: the liveness check, the admin login itself, and the player pages.
router.include_router(health.router)
router.include_router(admin.router)
router.include_router(slot.router)
# Everything else is the admin's (#32).
admin_only = [Depends(require_admin)]
router.include_router(health.details_router, dependencies=admin_only)
router.include_router(server.router, dependencies=admin_only)
router.include_router(console.router, dependencies=admin_only)
router.include_router(game.router, dependencies=admin_only)
router.include_router(archives.router, dependencies=admin_only)
router.include_router(uploads.router, dependencies=admin_only)
router.include_router(apworlds.router, dependencies=admin_only)
router.include_router(logs.router, dependencies=admin_only)
router.include_router(settings.router, dependencies=admin_only)
router.include_router(audit_log.router, dependencies=admin_only)
