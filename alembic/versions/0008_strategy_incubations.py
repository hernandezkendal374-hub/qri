"""Add strategy incubation specifications.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.migration_guards import (
    drop_index_if_present,
    drop_table_if_present,
)

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "strategy_incubations" not in inspector.get_table_names():
        op.create_table(
            "strategy_incubations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("question_id", sa.Integer(), nullable=False),
            sa.Column("readiness_status", sa.String(length=32), nullable=False),
            sa.Column("specification_json", sa.JSON(), nullable=False),
            sa.Column("model", sa.String(length=255), nullable=False),
            sa.Column("prompt_version", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["question_id"], ["research_questions.id"]),
            sa.UniqueConstraint("question_id"),
        )
        op.create_index(
            "ix_strategy_incubations_question_id",
            "strategy_incubations",
            ["question_id"],
            unique=True,
        )


def downgrade() -> None:
    drop_index_if_present("strategy_incubations", "ix_strategy_incubations_question_id")
    drop_table_if_present("strategy_incubations")
