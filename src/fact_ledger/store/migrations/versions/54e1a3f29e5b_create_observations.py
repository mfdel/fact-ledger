"""create observations

Revision ID: 54e1a3f29e5b
Revises:
Create Date: 2026-09-23 17:36:27.515407
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "54e1a3f29e5b"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "observations",
        sa.Column("observation_id", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("metric_id", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("stated_precision", sa.String(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("period_type", sa.String(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("published_date", sa.Date(), nullable=False),
        sa.Column("origin_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("locator", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("reliability", sa.Integer(), nullable=False),
        sa.Column("bias_direction", sa.String(), nullable=False),
        sa.Column("stated_label", sa.String(), nullable=False),
        sa.Column("definition_status", sa.String(), nullable=False),
        sa.Column("candidate_metric_ids", sa.JSON(), nullable=False),
        sa.Column("derivation", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("observation_id"),
    )
    with op.batch_alter_table("observations", schema=None) as batch_op:
        batch_op.create_index(
            "ix_observations_entity_metric_period",
            ["entity_id", "metric_id", "period_end"],
            unique=False,
        )

    op.create_table(
        "metric_id_changes",
        sa.Column("change_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("observation_id", sa.String(), nullable=False),
        sa.Column("old_metric_id", sa.String(), nullable=False),
        sa.Column("new_metric_id", sa.String(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["observation_id"], ["observations.observation_id"]),
        sa.PrimaryKeyConstraint("change_id"),
    )


def downgrade() -> None:
    op.drop_table("metric_id_changes")
    with op.batch_alter_table("observations", schema=None) as batch_op:
        batch_op.drop_index("ix_observations_entity_metric_period")

    op.drop_table("observations")
