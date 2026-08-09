"""Add resumable pipeline stage checkpoints.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("pipeline_runs")}
    additions = [
        (
            "run_type",
            sa.Column("run_type", sa.String(32), nullable=False, server_default="END_TO_END"),
        ),
        ("status", sa.Column("status", sa.String(32), nullable=False, server_default="RUNNING")),
        ("current_stage", sa.Column("current_stage", sa.String(32), nullable=True)),
    ]
    for name, column in additions:
        if name not in columns:
            op.add_column("pipeline_runs", column)
    if not inspector.has_table("pipeline_stage_runs"):
        op.create_table(
            "pipeline_stage_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("run_id", sa.String(64), nullable=False),
            sa.Column("stage", sa.String(32), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("ended_at", sa.DateTime(), nullable=True),
            sa.Column("metrics_json", sa.JSON(), nullable=False),
            sa.Column("error_json", sa.JSON(), nullable=True),
            sa.Column("checkpoint_json", sa.JSON(), nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_pipeline_stage_runs"),
        )
        op.create_index("ix_pipeline_stage_runs_run_id", "pipeline_stage_runs", ["run_id"])
        op.create_index(
            "uq_pipeline_stage_run",
            "pipeline_stage_runs",
            ["run_id", "stage"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("pipeline_stage_runs"):
        op.drop_index("uq_pipeline_stage_run", table_name="pipeline_stage_runs")
        op.drop_index("ix_pipeline_stage_runs_run_id", table_name="pipeline_stage_runs")
        op.drop_table("pipeline_stage_runs")
    columns = {column["name"] for column in inspector.get_columns("pipeline_runs")}
    for name in ("current_stage", "status", "run_type"):
        if name in columns:
            op.drop_column("pipeline_runs", name)
