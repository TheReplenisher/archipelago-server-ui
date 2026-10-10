"""apworlds

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "apworlds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("module", sa.String(length=255), nullable=True),
        sa.Column("game", sa.String(length=255), nullable=True),
        sa.Column("world_version", sa.String(length=32), nullable=True),
        sa.Column("minimum_ap_version", sa.String(length=32), nullable=True),
        sa.Column("maximum_ap_version", sa.String(length=32), nullable=True),
        sa.Column("authors", sa.JSON(), nullable=True),
        sa.Column("manifest", sa.JSON(), nullable=True),
        sa.Column("files", sa.JSON(), nullable=True),
        sa.Column("replaces_builtin", sa.String(length=32), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("import_result", sa.JSON(), nullable=True),
        sa.Column("job_id", sa.String(length=32), nullable=True),
        sa.Column("uploaded_by", sa.String(length=64), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name=op.f("fk_apworlds_job_id_jobs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_apworlds")),
    )
    with op.batch_alter_table("apworlds", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_apworlds_sha256"), ["sha256"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("apworlds", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_apworlds_sha256"))

    op.drop_table("apworlds")
