"""world locks

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "world_locks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("world", sa.String(length=255), nullable=False),
        sa.Column("apworld_id", sa.Integer(), nullable=True),
        sa.Column("upload_id", sa.Integer(), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["apworld_id"], ["apworlds.id"], name=op.f("fk_world_locks_apworld_id_apworlds")
        ),
        sa.ForeignKeyConstraint(
            ["game_id"], ["games.id"], name=op.f("fk_world_locks_game_id_games")
        ),
        sa.ForeignKeyConstraint(
            ["upload_id"], ["uploads.id"], name=op.f("fk_world_locks_upload_id_uploads")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_world_locks")),
        sa.UniqueConstraint("game_id", "world", name=op.f("uq_world_locks_game_id")),
    )
    with op.batch_alter_table("uploads", schema=None) as batch_op:
        batch_op.add_column(sa.Column("worlds", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("uploads", schema=None) as batch_op:
        batch_op.drop_column("worlds")

    op.drop_table("world_locks")
