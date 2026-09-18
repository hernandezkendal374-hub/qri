"""Idempotency helpers shared by the Alembic revisions.

The 0001 baseline creates the schema straight from ``Base.metadata``, so a
database created today already carries every column that later revisions add.
Guarding each additive step keeps ``alembic upgrade head`` correct both on a
brand-new database and on one that predates the revision.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


def has_table(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return False
    return any(existing["name"] == column for existing in inspector.get_columns(table))


def has_index(table: str, index: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return False
    return any(existing["name"] == index for existing in inspector.get_indexes(table))


def add_column_if_missing(table: str, column: sa.Column) -> None:
    if not has_column(table, column.name):
        op.add_column(table, column)


def create_index_if_missing(
    index: str, table: str, columns: Sequence[str], *, unique: bool = False
) -> None:
    if has_table(table) and not has_index(table, index):
        op.create_index(index, table, list(columns), unique=unique)


def drop_column_if_present(table: str, column: str) -> None:
    if has_column(table, column):
        op.drop_column(table, column)


def drop_index_if_present(table: str, index: str) -> None:
    if has_index(table, index):
        op.drop_index(index, table_name=table)


def drop_table_if_present(table: str) -> None:
    if has_table(table):
        op.drop_table(table)
