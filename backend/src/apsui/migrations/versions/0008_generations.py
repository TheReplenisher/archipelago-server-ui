"""generations

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "generations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seed_name", sa.String(length=64), nullable=True),
        sa.Column("output_file", sa.String(length=255), nullable=True),
        sa.Column("players", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("culprits", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["game_id"], ["games.id"], name=op.f("fk_generations_game_id_games")
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_generations_job_id_jobs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generations")),
    )


def downgrade() -> None:
    op.drop_table("generations")
