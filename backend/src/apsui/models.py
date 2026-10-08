"""ORM models. Import every model here so Alembic autogenerate sees it.

Tables arrive with the issues that need them (uploads, library, games, settings, ...).
"""

from apsui.db import Base

__all__ = ["Base"]
