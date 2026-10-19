"""player uploads: who sent a file from where, and its receipt

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("uploads", "apworlds"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("uploaded_from", sa.String(length=64), nullable=True))
            batch.add_column(sa.Column("receipt_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    for table in ("uploads", "apworlds"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("receipt_hash")
            batch.drop_column("uploaded_from")
