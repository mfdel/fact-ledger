"""add cited_origin_id to observations

Revision ID: b3c81d4e7a20
Revises: 716da39a681f
Create Date: 2026-10-02 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3c81d4e7a20"
down_revision: str | None = "716da39a681f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable, so old rows stay valid and mean "the source is the origin".
    with op.batch_alter_table("observations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cited_origin_id", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("observations", schema=None) as batch_op:
        batch_op.drop_column("cited_origin_id")
