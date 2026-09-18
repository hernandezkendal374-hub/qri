"""Add incremental knowledge, scout assessments, and community shadow mode.

This migration is additive.  Existing Paper, Claim, Evidence, ResearchCard,
run, and legacy strategy records are intentionally left untouched.
"""

import sqlalchemy as sa

from alembic import op
from app.db.migration_guards import (
    add_column_if_missing,
    create_index_if_missing,
    drop_column_if_present,
    drop_index_if_present,
    drop_table_if_present,
    has_table,
)

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def _add_column(table: str, column: sa.Column) -> None:
    # SQLite can add nullable columns to the already populated database.  The
    # ORM supplies defaults for new writes, while old rows remain valid.  The
    # guard makes this a no-op when the 0001 baseline already created the
    # column straight from ``Base.metadata``.
    add_column_if_missing(table, column)


def upgrade() -> None:
    for column in (
        sa.Column("family", sa.String(128), nullable=True),
        sa.Column("plain_language_summary", sa.Text(), nullable=True),
        sa.Column("academic_summary", sa.Text(), nullable=True),
        sa.Column("known_claims_json", sa.JSON(), nullable=True),
        sa.Column("known_conflicts_json", sa.JSON(), nullable=True),
        sa.Column("open_questions_json", sa.JSON(), nullable=True),
        sa.Column("active_research_questions_json", sa.JSON(), nullable=True),
        sa.Column("last_material_change_at", sa.DateTime(), nullable=True),
        sa.Column("last_scanned_at", sa.DateTime(), nullable=True),
        sa.Column("research_maturity", sa.String(32), nullable=True),
        sa.Column("evidence_density", sa.Float(), nullable=True),
    ):
        _add_column("research_themes", column)

    for column in (
        sa.Column("incremental_value_score", sa.Float(), nullable=True, server_default="0"),
        sa.Column("claim_conflict_score", sa.Float(), nullable=True, server_default="0"),
        sa.Column("falsification_value_score", sa.Float(), nullable=True, server_default="0"),
        sa.Column("investment_relevance_hint", sa.Float(), nullable=True, server_default="0"),
        sa.Column("duplicate_knowledge_penalty", sa.Float(), nullable=True, server_default="0"),
    ):
        _add_column("radar_assessments", column)
    create_index_if_missing(
        "ix_radar_assessments_incremental_value_score",
        "radar_assessments",
        ["incremental_value_score"],
    )

    if not has_table("knowledge_deltas"):
        op.create_table(
            "knowledge_deltas",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("delta_uid", sa.String(64), nullable=False),
            sa.Column("theme_id", sa.Integer(), nullable=False),
            sa.Column("paper_id", sa.Integer(), nullable=True),
            sa.Column("source_id", sa.String(255), nullable=True),
            sa.Column("source_type", sa.String(32), nullable=False),
            sa.Column("delta_type", sa.String(48), nullable=False),
            sa.Column("affected_claim_ids_json", sa.JSON(), nullable=True),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("materiality_score", sa.Float(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["theme_id"], ["research_themes.id"]),
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"]),
            sa.UniqueConstraint("delta_uid"),
        )
    for name, columns in (
        ("ix_knowledge_deltas_theme_id", ["theme_id"]),
        ("ix_knowledge_deltas_paper_id", ["paper_id"]),
        ("ix_knowledge_deltas_source_id", ["source_id"]),
        ("ix_knowledge_deltas_delta_type", ["delta_type"]),
        ("ix_knowledge_deltas_materiality_score", ["materiality_score"]),
        ("ix_knowledge_deltas_created_at", ["created_at"]),
    ):
        create_index_if_missing(name, "knowledge_deltas", columns)

    if not has_table("scout_assessments"):
        op.create_table(
            "scout_assessments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("paper_id", sa.Integer(), nullable=False),
            sa.Column("theme_id", sa.Integer(), nullable=False),
            sa.Column("research_value_score", sa.Float(), nullable=False),
            sa.Column("investment_relevance_score", sa.Float(), nullable=False),
            sa.Column("novelty", sa.Float(), nullable=False),
            sa.Column("evidence_potential", sa.Float(), nullable=False),
            sa.Column("conflict_potential", sa.Float(), nullable=False),
            sa.Column("falsification_potential", sa.Float(), nullable=False),
            sa.Column("data_availability_hint", sa.Float(), nullable=False),
            sa.Column("implementation_feasibility_hint", sa.Float(), nullable=False),
            sa.Column("recommend_deep_research", sa.Boolean(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"]),
            sa.ForeignKeyConstraint(["theme_id"], ["research_themes.id"]),
            sa.UniqueConstraint("paper_id"),
        )
    for name, columns in (
        ("ix_scout_assessments_paper_id", ["paper_id"]),
        ("ix_scout_assessments_theme_id", ["theme_id"]),
        ("ix_scout_assessments_created_at", ["created_at"]),
    ):
        create_index_if_missing(name, "scout_assessments", columns)

    if not has_table("investment_relevance"):
        op.create_table(
            "investment_relevance",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("paper_id", sa.Integer(), nullable=True),
            sa.Column("theme_id", sa.Integer(), nullable=True),
            sa.Column("question_id", sa.Integer(), nullable=True),
            sa.Column("hypothesis_convertibility", sa.Float(), nullable=False),
            sa.Column("data_availability", sa.Float(), nullable=False),
            sa.Column("holding_period_fit", sa.Float(), nullable=False),
            sa.Column("implementation_complexity", sa.Float(), nullable=False),
            sa.Column("forward_validation_feasibility", sa.Float(), nullable=False),
            sa.Column("capital_fit", sa.Float(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"]),
            sa.ForeignKeyConstraint(["theme_id"], ["research_themes.id"]),
            sa.ForeignKeyConstraint(["question_id"], ["research_questions.id"]),
        )
    for name, columns in (
        ("ix_investment_relevance_paper_id", ["paper_id"]),
        ("ix_investment_relevance_theme_id", ["theme_id"]),
        ("ix_investment_relevance_question_id", ["question_id"]),
    ):
        create_index_if_missing(name, "investment_relevance", columns)

    if not has_table("falsification_tasks"):
        op.create_table(
            "falsification_tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("task_uid", sa.String(64), nullable=False),
            sa.Column("theme_id", sa.Integer(), nullable=True),
            sa.Column("claim_id", sa.Integer(), nullable=True),
            sa.Column("observation_id", sa.Integer(), nullable=True),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("attack_dimension", sa.String(32), nullable=False),
            sa.Column("required_data_json", sa.JSON(), nullable=True),
            sa.Column("required_code_json", sa.JSON(), nullable=True),
            sa.Column("required_checks_json", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["theme_id"], ["research_themes.id"]),
            sa.ForeignKeyConstraint(["claim_id"], ["claims.id"]),
            sa.UniqueConstraint("task_uid"),
        )
    for name, columns in (
        ("ix_falsification_tasks_theme_id", ["theme_id"]),
        ("ix_falsification_tasks_claim_id", ["claim_id"]),
        ("ix_falsification_tasks_observation_id", ["observation_id"]),
        ("ix_falsification_tasks_status", ["status"]),
    ):
        create_index_if_missing(name, "falsification_tasks", columns)

    if not has_table("community_observations"):
        op.create_table(
            "community_observations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("observation_uid", sa.String(64), nullable=False),
            sa.Column("source_provider", sa.String(64), nullable=False),
            sa.Column("source_tier", sa.String(32), nullable=False),
            sa.Column("target_theme_id", sa.Integer(), nullable=True),
            sa.Column("target_paper_id", sa.Integer(), nullable=True),
            sa.Column("target_claim_id", sa.Integer(), nullable=True),
            sa.Column("observation_type", sa.String(48), nullable=False),
            sa.Column("observation_text", sa.Text(), nullable=False),
            sa.Column("implementation_conditions", sa.Text(), nullable=True),
            sa.Column("author_name", sa.String(255), nullable=True),
            sa.Column("author_reputation", sa.Integer(), nullable=True),
            sa.Column("votes", sa.Integer(), nullable=True),
            sa.Column("accepted_answer", sa.Boolean(), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=False),
            sa.Column("captured_at", sa.DateTime(), nullable=False),
            sa.Column("edited_at", sa.DateTime(), nullable=True),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("code_links_json", sa.JSON(), nullable=True),
            sa.Column("data_links_json", sa.JSON(), nullable=True),
            sa.Column("verification_status", sa.String(32), nullable=False),
            sa.Column("independence_score", sa.Float(), nullable=False),
            sa.Column("reproducibility_score", sa.Float(), nullable=False),
            sa.Column("attack_dimension", sa.String(32), nullable=False),
            sa.Column("generated_test_task_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["target_theme_id"], ["research_themes.id"]),
            sa.ForeignKeyConstraint(["target_paper_id"], ["papers.id"]),
            sa.ForeignKeyConstraint(["target_claim_id"], ["claims.id"]),
            sa.UniqueConstraint("observation_uid"),
            sa.UniqueConstraint("content_hash"),
        )
    for name, columns in (
        ("ix_community_observations_target_theme_id", ["target_theme_id"]),
        ("ix_community_observations_target_paper_id", ["target_paper_id"]),
        ("ix_community_observations_target_claim_id", ["target_claim_id"]),
        ("ix_community_observations_verification_status", ["verification_status"]),
        ("ix_community_observations_captured_at", ["captured_at"]),
    ):
        create_index_if_missing(name, "community_observations", columns)


def downgrade() -> None:
    drop_table_if_present("community_observations")
    drop_table_if_present("falsification_tasks")
    drop_table_if_present("investment_relevance")
    drop_table_if_present("scout_assessments")
    drop_table_if_present("knowledge_deltas")
    drop_index_if_present("radar_assessments", "ix_radar_assessments_incremental_value_score")
    for column in (
        "incremental_value_score",
        "claim_conflict_score",
        "falsification_value_score",
        "investment_relevance_hint",
        "duplicate_knowledge_penalty",
    ):
        drop_column_if_present("radar_assessments", column)
    for column in (
        "family",
        "plain_language_summary",
        "academic_summary",
        "known_claims_json",
        "known_conflicts_json",
        "open_questions_json",
        "active_research_questions_json",
        "last_material_change_at",
        "last_scanned_at",
        "research_maturity",
        "evidence_density",
    ):
        drop_column_if_present("research_themes", column)
