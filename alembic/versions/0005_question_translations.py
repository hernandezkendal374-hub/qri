"""Add Chinese question translations.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.migration_guards import (
    drop_index_if_present,
    drop_table_if_present,
)

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("question_translations"):
        op.create_table(
            "question_translations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "question_id", sa.Integer(), sa.ForeignKey("research_questions.id"), nullable=False
            ),
            sa.Column("question_zh", sa.Text(), nullable=False),
            sa.Column("economic_mechanism_zh", sa.Text(), nullable=False),
            sa.Column("counter_mechanism_zh", sa.Text(), nullable=False),
            sa.Column("required_data_zh_json", sa.JSON(), nullable=False),
            sa.Column("known_risks_zh_json", sa.JSON(), nullable=False),
            sa.Column("model", sa.String(255), nullable=False),
            sa.Column("prompt_version", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("question_id", name="uq_question_translations_question_id"),
        )
        op.create_index(
            "ix_question_translations_question_id", "question_translations", ["question_id"]
        )


def downgrade() -> None:
    drop_index_if_present("question_translations", "ix_question_translations_question_id")
    drop_table_if_present("question_translations")
