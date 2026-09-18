"""Add reversible research-question archiving.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.migration_guards import (
    drop_column_if_present,
)

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("research_questions")}
    if "archived_at" not in columns:
        op.add_column("research_questions", sa.Column("archived_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    drop_column_if_present("research_questions", "archived_at")
