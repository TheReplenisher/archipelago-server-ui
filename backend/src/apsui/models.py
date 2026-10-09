"""ORM models. Import every model here so Alembic autogenerate sees it."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apsui.db import Base


class Job(Base):
    """A worker job (DESIGN.md §2). The files travel through the jobs directory; this is the
    record of it, kept after the files are gone (upload logs, #23, read the details here)."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    """queued, running, ok, error or timeout."""
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    """The worker's full result: output, error with traceback, and the log tail."""


__all__ = ["Base", "Job"]
