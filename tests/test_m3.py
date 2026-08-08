from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.extraction.json_parser import parse_json_model
from app.extraction.research_card import ResearchCardExtractor
from app.models import AICall, Document, Paper, ResearchCard
from app.providers.llm.base import LLMProvider, LLMResponse
from app.providers.llm.fixture import FixtureLLMProvider
from app.schemas.research import ResearchCardExtraction

FIXTURE = Path(__file__).parent / "fixtures" / "research_card_valid.json"


def make_session() -> tuple[Session, Paper, Document]:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    paper = Paper(
        title="A full text paper",
        normalized_title="a full text paper",
        authors_json=[],
        source="test",
    )
    session.add(paper)
    session.flush()
    document = Document(
        paper_id=paper.id,
        document_type="PDF",
        content_hash="abc",
        parser_version="test",
        parsed_text="Complete paper content.",
    )
    session.add(document)
    session.commit()
    return session, paper, document


def test_llm_json_parser_accepts_code_fence() -> None:
    content = f"```json\n{FIXTURE.read_text(encoding='utf-8')}\n```"
    parsed = parse_json_model(content, ResearchCardExtraction)
    assert parsed.card.market == "United States"
    assert parsed.card.universe is None


def test_llm_json_parser_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        parse_json_model('{"card": {}, "invented": true}', ResearchCardExtraction)


@pytest.mark.asyncio
async def test_extraction_persists_card_and_ai_audit() -> None:
    session, paper, document = make_session()
    try:
        provider = FixtureLLMProvider([FIXTURE.read_text(encoding="utf-8")])
        card = await ResearchCardExtractor(session, provider, "fixture-request").extract(
            paper, document, "run-1"
        )
        assert card.market == "United States"
        assert card.universe is None
        assert card.model == "fixture-request"
        audit = session.scalar(select(AICall))
        assert audit is not None
        assert audit.status == "SUCCESS"
        assert audit.returned_model == "fixture-model"
        assert audit.response_hash
    finally:
        session.close()


@pytest.mark.asyncio
async def test_malformed_response_is_audited_without_card() -> None:
    session, paper, document = make_session()
    try:
        provider = FixtureLLMProvider(["not json"])
        with pytest.raises(ValueError, match="No JSON object"):
            await ResearchCardExtractor(session, provider, "fixture-request").extract(
                paper, document
            )
        assert session.scalar(select(func.count()).select_from(ResearchCard)) == 0
        audit = session.scalar(select(AICall))
        assert audit is not None
        assert audit.status == "PARSE_ERROR"
    finally:
        session.close()


@pytest.mark.asyncio
async def test_abstract_document_cannot_be_analyzed_as_full_text() -> None:
    session, paper, document = make_session()
    try:
        document.document_type = "ABSTRACT"
        session.commit()
        provider = FixtureLLMProvider([FIXTURE.read_text(encoding="utf-8")])
        with pytest.raises(ValueError, match="requires parsed PDF full text"):
            await ResearchCardExtractor(session, provider, "fixture-request").extract(
                paper, document
            )
        assert session.scalar(select(func.count()).select_from(AICall)) == 0
    finally:
        session.close()


class RaisingProvider(LLMProvider):
    async def complete(self, **kwargs) -> LLMResponse:
        raise RuntimeError("provider unavailable")


@pytest.mark.asyncio
async def test_provider_failure_is_audited() -> None:
    session, paper, document = make_session()
    try:
        with pytest.raises(RuntimeError, match="provider unavailable"):
            await ResearchCardExtractor(session, RaisingProvider(), "unavailable-model").extract(
                paper, document
            )
        audit = session.scalar(select(AICall))
        assert audit is not None
        assert audit.status == "API_ERROR"
        assert audit.requested_model == "unavailable-model"
    finally:
        session.close()
