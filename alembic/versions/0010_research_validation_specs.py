"""Add dual question wording and research validation specifications.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("research_questions") as batch_op:
        batch_op.add_column(sa.Column("plain_language_question", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("academic_question", sa.Text(), nullable=True))
    op.execute(
        "UPDATE research_questions SET plain_language_question = question, "
        "academic_question = question"
    )
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
    op.create_index(
        "ix_research_validation_specs_question_id",
        "research_validation_specs",
        ["question_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_validation_specs_question_id",
        table_name="research_validation_specs",
    )
    op.drop_table("research_validation_specs")
    with op.batch_alter_table("research_questions") as batch_op:
        batch_op.drop_column("academic_question")
        batch_op.drop_column("plain_language_question")
