from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.session import build_engine
from app.main import create_app
from app.models import Claim, Evidence, Paper, QuestionStatus, ResearchCard, ResearchQuestion
from app.models.entities import FullTextStatus


def app_with_data(tmp_path: Path) -> tuple[FastAPI, int, int]:
    engine = build_engine(f"sqlite:///{tmp_path / 'web.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        paper = Paper(
            title="Momentum Evidence in US Equities",
            normalized_title="momentum evidence in us equities",
            abstract="This paper studies momentum with point-in-time data.",
            authors_json=[{"name": "Jane Smith"}],
            source="test",
            fulltext_status=FullTextStatus.FULLTEXT_AVAILABLE,
        )
        session.add(paper)
        session.flush()
        card = ResearchCard(
            paper_id=paper.id,
            market="United States",
            mechanism="Investor underreaction",
            model="claude-sonnet-4-6",
            prompt_version="research-card-v1",
        )
        claim = Claim(
            paper_id=paper.id,
            claim_type="AUTHOR_CLAIM",
            claim_text="The authors report positive momentum returns.",
            direction="POSITIVE",
        )
        session.add_all([card, claim])
        session.flush()
        pointer = Evidence(
            paper_id=paper.id,
            claim_id=claim.id,
            research_card_field="market",
            page_number=4,
            section="Results",
            paragraph_index=2,
            source_text="The sample covers United States equities.",
            start_offset=120,
            end_offset=160,
            confidence=1.0,
        )
        question = ResearchQuestion(
            question_uid="RQ-MOMENTUM-0001",
            family="Momentum",
            question="Does momentum survive costs in a point-in-time US equity universe?",
            economic_mechanism="Investor underreaction",
            counter_mechanism="Crowding and transaction costs",
            supporting_claims_json=[claim.id],
            contradicting_claims_json=[],
            required_data_json=["Point-in-time universe"],
            known_risks_json=["Survivorship bias"],
            novelty_score=0.7,
            testability_score=0.9,
            data_availability_score=0.8,
            research_priority_score=0.82,
            status=QuestionStatus.HUMAN_REVIEW_REQUIRED,
        )
        session.add_all([pointer, question])
        session.commit()
        paper_id, evidence_id = paper.id, pointer.id
    return create_app(factory), paper_id, evidence_id


@pytest.mark.asyncio
async def test_papers_and_detail_render_evidence_anchor(tmp_path: Path) -> None:
    app, paper_id, evidence_id = app_with_data(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        papers = await client.get("/papers")
        assert papers.status_code == 200
        assert "Momentum Evidence in US Equities" in papers.text
        assert "FULLTEXT_AVAILABLE" in papers.text
        detail = await client.get(f"/papers/{paper_id}?evidence={evidence_id}")
        assert detail.status_code == 200
        assert "Research Card" in detail.text
        assert "VERIFIED" in detail.text
        assert f'id="evidence-{evidence_id}"' in detail.text
        assert "The sample covers United States equities." in detail.text
        assert "Offset 120–160" in detail.text


@pytest.mark.asyncio
async def test_claims_link_back_to_paper_evidence(tmp_path: Path) -> None:
    app, paper_id, evidence_id = app_with_data(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/claims")
        assert response.status_code == 200
        assert "AUTHOR_CLAIM" in response.text
        assert f"/papers/{paper_id}?evidence={evidence_id}#evidence-{evidence_id}" in response.text


@pytest.mark.asyncio
async def test_questions_show_review_status_and_scores(tmp_path: Path) -> None:
    app, _, _ = app_with_data(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/questions")
        assert response.status_code == 200
        assert "RQ-MOMENTUM-0001" in response.text
        assert "等待人工审核" in response.text
        assert "生成研究验证方案" in response.text
        assert "Research Validation Spec" in response.text
        assert "生成策略并回测" not in response.text
        assert "Sharpe" not in response.text


@pytest.mark.asyncio
async def test_root_redirect_and_missing_paper(tmp_path: Path) -> None:
    app, _, _ = app_with_data(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/papers"
        assert (await client.get("/papers/999999")).status_code == 404


@pytest.mark.asyncio
async def test_legacy_strategy_mutations_are_closed(tmp_path: Path) -> None:
    app, _, _ = app_with_data(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        strategies = await client.get("/strategies", follow_redirects=False)
        assert strategies.status_code == 303
        assert strategies.headers["location"] == "/legacy-strategies"
        assert (await client.post("/questions/1/incubate")).status_code == 410
