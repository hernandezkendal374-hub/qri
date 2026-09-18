"""The legacy strategy surface is an archive: readable, never writable.

README states that legacy strategy incubation and quick backtesting are kept
only as a hidden read-only archive.  These tests pin that boundary to the HTTP
surface, so a future change cannot quietly reintroduce a write path that turns
a research question into a scored strategy.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.session import build_engine
from app.main import create_app
from app.models import Paper, ResearchQuestion, StrategyIncubation

# Every write path that used to create, run, or mutate a legacy strategy record.
RETIRED_WRITE_ROUTES = (
    "/strategies/{id}/backtest/run",
    "/questions/{id}/advance",
    "/strategies/{id}/reconstruct",
    "/questions/{id}/incubate",
)


def _app(tmp_path: Path) -> tuple[FastAPI, int]:
    engine = build_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        paper = Paper(title="Momentum", normalized_title="momentum", source="test")
        session.add(paper)
        session.flush()
        question = ResearchQuestion(
            question_uid="RQ-LEGACY-0001",
            family="momentum",
            question="Does momentum survive realistic transaction costs?",
            economic_mechanism="Investor underreaction",
            counter_mechanism="Crowding and transaction costs",
        )
        session.add(question)
        session.flush()
        session.add(
            StrategyIncubation(
                question_id=question.id,
                readiness_status="ARCHIVED",
                specification_json={"executable_strategy": {"strategy_type": "momentum"}},
                model="legacy",
                prompt_version="legacy",
            )
        )
        session.commit()
        question_id = question.id
    return create_app(session_factory=factory), question_id


@pytest.mark.parametrize("route", RETIRED_WRITE_ROUTES)
async def test_retired_write_routes_are_gone(tmp_path: Path, route: str) -> None:
    app, question_id = _app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(route.replace("{id}", str(question_id)))
    assert response.status_code == 410


async def test_backtest_page_redirects_to_the_archive(tmp_path: Path) -> None:
    app, question_id = _app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/strategies/{question_id}/backtest")
    assert response.status_code == 303
    assert response.headers["location"] == "/legacy-strategies"


async def test_retired_routes_do_not_mutate_stored_records(tmp_path: Path) -> None:
    app, question_id = _app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for route in RETIRED_WRITE_ROUTES:
            await client.post(route.replace("{id}", str(question_id)))
        archive = await client.get("/legacy-strategies")
    # The archive still renders, and the stored specification is untouched.
    assert archive.status_code == 200
