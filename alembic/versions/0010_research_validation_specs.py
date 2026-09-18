"""Add dual question wording and research validation specifications.

Revision ID: 0010
Revises: 0009

Every step is guarded so the revision is a no-op on a database that the 0001
baseline already created with these columns and tables.
"""

import sqlalchemy as sa

from alembic import op
from app.db.migration_guards import (
    create_index_if_missing,
    drop_index_if_present,
    drop_table_if_present,
    has_column,
    has_table,
)

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_QUESTION_COLUMNS = ("plain_language_question", "academic_question")


def upgrade() -> None:
    missing = [name for name in _QUESTION_COLUMNS if not has_column("research_questions", name)]
    if missing:
        with op.batch_alter_table("research_questions") as batch_op:
            for name in missing:
                batch_op.add_column(sa.Column(name, sa.Text(), nullable=True))
        # Backfill only the wording columns this revision introduced.
        op.execute(
            "UPDATE research_questions SET "
            + ", ".join(f"{name} = question" for name in missing)
            + " WHERE question IS NOT NULL"
        )
    if not has_table("research_validation_specs"):
        op.create_table(
            "research_validation_specs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("question_id", sa.Integer(), nullable=False),
            sa.Column("review_status", sa.String(length=32), nullable=False),
            sa.Column("specification_json", sa.JSON(), nullable=False),
            sa.Column("model", sa.String(length=255), nullable=False),
            sa.Column("prompt_version", sa.String(length=64), nullable=False),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("exported_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["question_id"], ["research_questions.id"]),
            sa.UniqueConstraint("question_id"),
        )
    create_index_if_missing(
        "ix_research_validation_specs_question_id",
        "research_validation_specs",
        ["question_id"],
        unique=True,
    )


def downgrade() -> None:
    drop_index_if_present("research_validation_specs", "ix_research_validation_specs_question_id")
    drop_table_if_present("research_validation_specs")
    present = [name for name in _QUESTION_COLUMNS if has_column("research_questions", name)]
    if present:
        with op.batch_alter_table("research_questions") as batch_op:
            for name in reversed(present):
                batch_op.drop_column(name)
