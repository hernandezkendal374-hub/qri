"""Add theme-driven three-speed research radar.

Revision ID: 0011
Revises: 0010

Every step is guarded so the revision is a no-op on a database that the 0001
baseline already created with these tables.
"""

import sqlalchemy as sa

from alembic import op
from app.db.migration_guards import create_index_if_missing, drop_table_if_present, has_table

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE questionstatus ADD VALUE IF NOT EXISTS 'DEFERRED'")

    if not has_table("research_themes"):
        op.create_table(
            "research_themes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("theme_key", sa.String(length=128), nullable=False),
            sa.Column("name_zh", sa.String(length=255), nullable=False),
            sa.Column("name_en", sa.String(length=255), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("paper_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("claim_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("conflict_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_changed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("theme_key"),
        )
    create_index_if_missing("ix_research_themes_theme_key", "research_themes", ["theme_key"])

    if not has_table("radar_assessments"):
        op.create_table(
            "radar_assessments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("paper_id", sa.Integer(), nullable=False),
            sa.Column("theme_id", sa.Integer(), nullable=False),
            sa.Column("decision", sa.String(length=32), nullable=False),
            sa.Column("change_type", sa.String(length=32), nullable=False),
            sa.Column("relevance_score", sa.Float(), nullable=False),
            sa.Column("novelty_score", sa.Float(), nullable=False),
            sa.Column("conflict_score", sa.Float(), nullable=False),
            sa.Column("evidence_potential_score", sa.Float(), nullable=False),
            sa.Column("radar_score", sa.Float(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("assessed_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"]),
            sa.ForeignKeyConstraint(["theme_id"], ["research_themes.id"]),
            sa.UniqueConstraint("paper_id"),
        )
    for index, columns in (
        ("ix_radar_assessments_paper_id", ["paper_id"]),
        ("ix_radar_assessments_theme_id", ["theme_id"]),
        ("ix_radar_assessments_decision", ["decision"]),
        ("ix_radar_assessments_change_type", ["change_type"]),
        ("ix_radar_assessments_radar_score", ["radar_score"]),
        ("ix_radar_assessments_assessed_at", ["assessed_at"]),
    ):
        create_index_if_missing(index, "radar_assessments", columns)


def downgrade() -> None:
    drop_table_if_present("radar_assessments")
    drop_table_if_present("research_themes")
