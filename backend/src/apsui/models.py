"""ORM models. Import every model here so Alembic autogenerate sees it."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

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


class Game(Base):
    """A multiworld game. Exactly one is current; the rest are archived (DESIGN.md §3).
    The state only changes through apsui.lifecycle.apply()."""

    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(16))
    is_current: Mapped[bool | None] = mapped_column(Boolean, unique=True)
    """True for the current game, NULL once archived: the unique constraint allows only one."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Upload(Base):
    """One uploaded file and what the checks made of it (DESIGN.md §4). Kept after the
    file is rejected or removed: it is the upload log (#23)."""

    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"))
    kind: Mapped[str] = mapped_column(String(16))
    """yaml (apworld and rom come later)."""
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    """pending, accepted, rejected or removed."""
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    """Short and safe to show the uploader; the full detail is in `detail`."""
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    """The worker's per-document results, or the job's error."""
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    slots: Mapped[list[Slot]] = relationship(
        back_populates="upload", cascade="all, delete-orphan", order_by="Slot.document"
    )


class Slot(Base):
    """A player slot from an accepted YAML document."""

    __tablename__ = "slots"
    __table_args__ = (UniqueConstraint("game_id", "name_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"))
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id"))
    document: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(16))
    name_key: Mapped[str] = mapped_column(String(64))
    """casefold(name): Archipelago compares names without case."""
    games: Mapped[list[str]] = mapped_column(JSON)
    """Usually one; a weighted `game:` lists every game it could roll."""

    upload: Mapped[Upload] = relationship(back_populates="slots")


__all__ = ["Base", "Game", "Job", "Slot", "Upload"]
