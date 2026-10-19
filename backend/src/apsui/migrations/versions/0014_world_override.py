"""admin override of a locked world version

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("world_locks") as batch:
        batch.add_column(sa.Column("overridden_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("rechecked", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("world_locks") as batch:
        batch.drop_column("rechecked")
        batch.drop_column("overridden_at")
