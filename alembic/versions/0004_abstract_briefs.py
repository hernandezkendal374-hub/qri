"""Add abstract-level AI briefs.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.migration_guards import (
    drop_index_if_present,
    drop_table_if_present,
)

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("abstract_briefs"):
        op.create_table(
            "abstract_briefs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("paper_id", sa.Integer(), sa.ForeignKey("papers.id"), nullable=False),
            sa.Column("summary_zh", sa.Text(), nullable=False),
            sa.Column("core_principle_zh", sa.Text(), nullable=False),
            sa.Column("economic_mechanism_zh", sa.Text(), nullable=False),
            sa.Column("methodology_zh", sa.Text(), nullable=True),
            sa.Column("reported_findings_json", sa.JSON(), nullable=False),
            sa.Column("limitations_json", sa.JSON(), nullable=False),
            sa.Column("reader_takeaway_zh", sa.Text(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("model", sa.String(255), nullable=False),
            sa.Column("prompt_version", sa.String(64), nullable=False),
            sa.Column(
                "source_scope", sa.String(32), nullable=False, server_default="TITLE_ABSTRACT"
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("paper_id", name="uq_abstract_briefs_paper_id"),
        )
        op.create_index("ix_abstract_briefs_paper_id", "abstract_briefs", ["paper_id"])


def downgrade() -> None:
    drop_index_if_present("abstract_briefs", "ix_abstract_briefs_paper_id")
    drop_table_if_present("abstract_briefs")
