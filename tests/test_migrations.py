"""Guard the Alembic chain against the drift that broke fresh installs.

The 0001 baseline builds the schema from ``Base.metadata``, so a database
created today already has every column later revisions add.  Before these
tests existed, ``alembic upgrade head`` crashed on a brand-new database with
``duplicate column name: research_scope`` — the documented first setup step.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from alembic import command
from app.db.base import Base

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def alembic_config(tmp_path: Path) -> Iterator[tuple[Config, str]]:
    url = f"sqlite:///{tmp_path / 'migrations.db'}"
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    # env.py reads the cached Settings object, so drop the cache first.
    from app.core.config import get_settings

    get_settings.cache_clear()
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    try:
        yield config, url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


def test_upgrade_head_succeeds_on_a_fresh_database(
    alembic_config: tuple[Config, str],
) -> None:
    config, url = alembic_config
    command.upgrade(config, "head")
    tables = set(inspect(create_engine(url)).get_table_names())
    assert "papers" in tables
    assert "research_themes" in tables
    assert "community_observations" in tables


def test_migrated_schema_matches_the_orm_models(alembic_config: tuple[Config, str]) -> None:
    config, url = alembic_config
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        assert compare_metadata(context, Base.metadata) == []


def test_upgrade_is_idempotent(alembic_config: tuple[Config, str]) -> None:
    config, _ = alembic_config
    command.upgrade(config, "head")
    command.upgrade(config, "head")


def test_downgrade_to_base_then_upgrade_again(alembic_config: tuple[Config, str]) -> None:
    config, url = alembic_config
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    remaining = set(inspect(create_engine(url)).get_table_names()) - {"alembic_version"}
    assert remaining == set()
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        assert compare_metadata(context, Base.metadata) == []
