"""Add US equity research scope classification to papers.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("papers") as batch_op:
        batch_op.add_column(
            sa.Column(
                "research_scope",
                sa.String(length=32),
                nullable=False,
                server_default="UNCLASSIFIED",
            )
        )
        batch_op.add_column(sa.Column("scope_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("scope_confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("scope_version", sa.String(length=64), nullable=True))
        batch_op.create_index("ix_papers_research_scope", ["research_scope"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("papers") as batch_op:
        batch_op.drop_index("ix_papers_research_scope")
        batch_op.drop_column("scope_version")
        batch_op.drop_column("scope_confidence")
        batch_op.drop_column("scope_reason")
        batch_op.drop_column("research_scope")
