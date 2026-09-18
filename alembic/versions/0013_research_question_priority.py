"""Add research priority bands without changing existing questions.

Every step is guarded so the revision is a no-op on a database that the 0001
baseline already created with this column.
"""

import sqlalchemy as sa

from app.db.migration_guards import (
    add_column_if_missing,
    create_index_if_missing,
    drop_column_if_present,
    drop_index_if_present,
)

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "research_questions",
        sa.Column("priority_type", sa.String(32), nullable=True, server_default="P3_EXPLORATORY"),
    )
    create_index_if_missing(
        "ix_research_questions_priority_type", "research_questions", ["priority_type"]
    )


def downgrade() -> None:
    drop_index_if_present("research_questions", "ix_research_questions_priority_type")
    drop_column_if_present("research_questions", "priority_type")
