"""Add US equity research scope classification to papers.

Revision ID: 0009
Revises: 0008

Every step is guarded so the revision is a no-op on a database that the 0001
baseline already created with these columns.
"""

import sqlalchemy as sa

from alembic import op
from app.db.migration_guards import create_index_if_missing, has_column, has_index

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_COLUMN_NAMES = ("research_scope", "scope_reason", "scope_confidence", "scope_version")


def _columns() -> list[sa.Column]:
    # Built fresh on each call: a Column instance may only be bound to one table.
    return [
        sa.Column(
            "research_scope", sa.String(length=32), nullable=False, server_default="UNCLASSIFIED"
        ),
        sa.Column("scope_reason", sa.Text(), nullable=True),
        sa.Column("scope_confidence", sa.Float(), nullable=True),
        sa.Column("scope_version", sa.String(length=64), nullable=True),
    ]


def upgrade() -> None:
    missing = [column for column in _columns() if not has_column("papers", column.name)]
    if missing:
        with op.batch_alter_table("papers") as batch_op:
            for column in missing:
                batch_op.add_column(column)
    create_index_if_missing("ix_papers_research_scope", "papers", ["research_scope"])


def downgrade() -> None:
    present = [name for name in _COLUMN_NAMES if has_column("papers", name)]
    index_present = has_index("papers", "ix_papers_research_scope")
    if not present and not index_present:
        return
    with op.batch_alter_table("papers") as batch_op:
        if index_present:
            batch_op.drop_index("ix_papers_research_scope")
        for name in reversed(present):
            batch_op.drop_column(name)
