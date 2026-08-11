"""Add research priority bands without changing existing questions."""

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "research_questions",
        sa.Column("priority_type", sa.String(32), nullable=True, server_default="P3_EXPLORATORY"),
    )
    op.create_index("ix_research_questions_priority_type", "research_questions", ["priority_type"])


def downgrade() -> None:
    op.drop_index("ix_research_questions_priority_type", table_name="research_questions")
    op.drop_column("research_questions", "priority_type")
