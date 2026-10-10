"""uploads and slots

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "uploads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("name_problems", sa.JSON(), nullable=True),
        sa.Column("job_id", sa.String(length=32), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], name=op.f("fk_uploads_game_id_games")),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_uploads_job_id_jobs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uploads")),
    )
    op.create_table(
        "slots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("upload_id", sa.Integer(), nullable=False),
        sa.Column("document", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=16), nullable=False),
        sa.Column("name_key", sa.String(length=64), nullable=False),
        sa.Column("games", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], name=op.f("fk_slots_game_id_games")),
        sa.ForeignKeyConstraint(
            ["upload_id"], ["uploads.id"], name=op.f("fk_slots_upload_id_uploads")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_slots")),
        sa.UniqueConstraint("game_id", "name_key", name=op.f("uq_slots_game_id")),
    )


def downgrade() -> None:
    op.drop_table("slots")
    op.drop_table("uploads")
