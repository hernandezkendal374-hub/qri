"""Initial QRI schema baseline.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

from alembic import op
from app import models  # noqa: F401
from app.db.base import Base

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the independently versioned QRI schema."""
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """Drop only QRI-owned tables in dependency-safe order."""
    Base.metadata.drop_all(bind=op.get_bind())
