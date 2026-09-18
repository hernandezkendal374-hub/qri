"""Add per-paper full-text acquisition diagnostics.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.migration_guards import (
    drop_column_if_present,
)

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("papers")}
    if "fulltext_failure_reason" not in columns:
        op.add_column("papers", sa.Column("fulltext_failure_reason", sa.Text(), nullable=True))
    if "fulltext_attempted_at" not in columns:
        op.add_column("papers", sa.Column("fulltext_attempted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    drop_column_if_present("papers", "fulltext_attempted_at")
    drop_column_if_present("papers", "fulltext_failure_reason")
