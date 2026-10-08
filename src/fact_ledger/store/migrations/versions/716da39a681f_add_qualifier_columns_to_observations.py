"""add qualifier columns to observations

Revision ID: 716da39a681f
Revises: 54e1a3f29e5b
Create Date: 2026-09-30 17:25:48.699757
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "716da39a681f"
down_revision: str | None = "54e1a3f29e5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A constant server default lets SQLite add the NOT NULL column with no
    # table rebuild. segment and region are nullable text: only basis has a reading today.
    with op.batch_alter_table("observations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("segment", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("region", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("basis", sa.String(), nullable=False, server_default="reported")
        )


def downgrade() -> None:
    with op.batch_alter_table("observations", schema=None) as batch_op:
        batch_op.drop_column("basis")
        batch_op.drop_column("region")
        batch_op.drop_column("segment")
