"""The demo dataset has to be real enough to judge the project by.

`qri demo` exists so somebody can see QRI working before committing to a
Postgres instance and a paid model endpoint. That only helps if the fixture
exercises the same invariants as a real run -- in particular the evidence
quotes must genuinely be verbatim spans of the stored full text, because
verbatim-anchored evidence is the project's core claim.
"""

from __future__ import annotations

from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.session import build_engine
from app.demo import DEMO_SOURCE, seed_demo_database
from app.demo.seed import DEMO_FULLTEXT
from app.evidence.locator import EvidenceLocator
from app.main import create_app
from app.models import (
    Claim,
    Document,
    Evidence,
    Paper,
    RadarAssessment,
    ResearchQuestion,
    ResearchTheme,
    ResearchValidationSpec,
)
from app.parsing.base import ParsedDocument, ParsedPage
from app.schemas.validation import ResearchValidationSpecification


def _factory(tmp_path: Path) -> sessionmaker:
    engine = build_engine(f"sqlite:///{tmp_path / 'demo.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def test_seed_populates_every_stage_of_the_funnel(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        counts = seed_demo_database(session)
        assert session.query(Paper).count() == counts["papers"]
        assert session.query(ResearchTheme).count() == counts["themes"]
        assert session.query(Claim).count() == counts["claims"]
        assert session.query(ResearchQuestion).count() == counts["questions"]
        assert session.query(ResearchValidationSpec).count() == counts["briefs"]
        deep = session.query(RadarAssessment).filter(RadarAssessment.decision == "DEEP").count()
        assert deep == counts["deep"]


def test_every_demo_record_is_tagged_as_demo_data(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        seed_demo_database(session)
        sources = {paper.source for paper in session.scalars(select(Paper))}
        assert sources == {DEMO_SOURCE}


def test_demo_evidence_quotes_are_verbatim_spans_of_the_full_text(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        seed_demo_database(session)
        document = session.scalar(select(Document))
        assert document is not None and document.parsed_text == DEMO_FULLTEXT
        rows = list(session.scalars(select(Evidence)))
        assert rows

        parsed = ParsedDocument(
            text=DEMO_FULLTEXT,
            pages=[
                ParsedPage(
                    page_number=1,
                    text=DEMO_FULLTEXT,
                    start_offset=0,
                    end_offset=len(DEMO_FULLTEXT),
                )
            ],
            parser_version="demo-fixture",
        )
        locator = EvidenceLocator(parsed)
        for evidence in rows:
            # Stored offsets point at the quote itself...
            assert DEMO_FULLTEXT[evidence.start_offset : evidence.end_offset] == (
                evidence.source_text
            )
            # ...and the real locator independently finds the same span.
            located = locator.locate(evidence.source_text)
            assert located.start_offset == evidence.start_offset
            assert located.end_offset == evidence.end_offset


def test_demo_research_brief_validates_against_the_real_schema(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        seed_demo_database(session)
        spec = session.scalar(select(ResearchValidationSpec))
        assert spec is not None
        # Raises if the fixture drifts from the production schema.
        ResearchValidationSpecification.model_validate(spec.specification_json)


def test_seeding_twice_replaces_rather_than_duplicates(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        first = seed_demo_database(session)
        second = seed_demo_database(session)
        assert first == second
        assert session.query(Paper).count() == first["papers"]
        assert session.query(ResearchQuestion).count() == first["questions"]


async def test_every_page_renders_with_the_demo_dataset(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        seed_demo_database(session)
    app = create_app(session_factory=factory)
    transport = httpx.ASGITransport(app=app)
    pages = (
        "/dashboard",
        "/papers",
        "/claims",
        "/questions",
        "/daily-best",
        "/themes",
        "/community-attack-radar",
        "/legacy-strategies",
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for page in pages:
            response = await client.get(page)
            assert response.status_code == 200, page


async def test_dashboard_counts_rows_that_reached_scout(tmp_path: Path) -> None:
    """prioritize() rewrites every SCOUT decision, so the metric must not
    filter on decision == "SCOUT" alone or it reads zero after a finished run."""
    factory = _factory(tmp_path)
    with factory() as session:
        seed_demo_database(session)
        still_scout = (
            session.query(RadarAssessment).filter(RadarAssessment.decision == "SCOUT").count()
        )
        assert still_scout == 0, "a completed funnel leaves no bare SCOUT rows"
    app = create_app(session_factory=factory)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/dashboard")).text
    assert "Scout" in body
    # 3 rows reached Scout: 2 promoted to DEEP, 1 archived after Scout.
    assert ">3<" in body.replace(" ", "").replace("\n", "")
