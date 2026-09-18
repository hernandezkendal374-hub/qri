"""Add persisted multi-paper comparisons.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.migration_guards import (
    drop_table_if_present,
)

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("paper_comparisons"):
        return
    op.create_table(
        "paper_comparisons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("comparison_uid", sa.String(length=64), nullable=False),
        sa.Column("paper_ids_json", sa.JSON(), nullable=False),
        sa.Column("common_findings_json", sa.JSON(), nullable=False),
        sa.Column("differences_json", sa.JSON(), nullable=False),
        sa.Column("contradictions_json", sa.JSON(), nullable=False),
        sa.Column("sample_differences_json", sa.JSON(), nullable=False),
        sa.Column("universe_differences_json", sa.JSON(), nullable=False),
        sa.Column("signal_differences_json", sa.JSON(), nullable=False),
        sa.Column("cost_assumption_differences_json", sa.JSON(), nullable=False),
        sa.Column("oos_differences_json", sa.JSON(), nullable=False),
        sa.Column("survivorship_differences_json", sa.JSON(), nullable=False),
        sa.Column("possible_explanations_json", sa.JSON(), nullable=False),
        sa.Column("research_gap", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_paper_comparisons"),
        sa.UniqueConstraint("comparison_uid", name="uq_paper_comparisons_comparison_uid"),
    )


def downgrade() -> None:
    drop_table_if_present("paper_comparisons")
