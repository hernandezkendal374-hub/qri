import json
from pathlib import Path

import pymupdf
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.claims.service import ClaimEvidenceExtractor
from app.db.base import Base
from app.db.session import build_engine
from app.evidence.verification import field_verification_status
from app.extraction.json_parser import parse_json_model
from app.models import Claim, Document, Evidence, Paper, ResearchCard
from app.parsing.pymupdf_parser import PyMuPDFParser
from app.providers.llm.fixture import FixtureLLMProvider
from app.schemas.claims import ClaimEvidenceExtraction

QUOTE = "Momentum predicts positive future returns."


def setup_paper(tmp_path: Path) -> tuple[Session, Paper, Document, ResearchCard]:
    path = tmp_path / "evidence.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), QUOTE)
    second = pdf.new_page()
    second.insert_text((72, 72), "A robustness test uses a later sample.")
    pdf.save(path)
    pdf.close()
    parser = PyMuPDFParser()
    parsed = parser.parse(path)
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    paper = Paper(
        title="Evidence paper",
        normalized_title="evidence paper",
        authors_json=[],
        source="test",
    )
    session.add(paper)
    session.flush()
    document = Document(
        paper_id=paper.id,
        document_type="PDF",
        local_path=str(path),
        content_hash="abc",
        parser_version=parsed.parser_version,
        parsed_text=parsed.text,
    )
    card = ResearchCard(
        paper_id=paper.id,
        market="United States",
        mechanism="Investor underreaction",
        model="fixture-request",
        prompt_version="research-card-v1",
    )
    session.add_all([document, card])
    session.commit()
    return session, paper, document, card


def response(quote: str = QUOTE, claim_type: str = "AUTHOR_CLAIM") -> str:
    return json.dumps(
        {
            "claims": [
                {
                    "claim_type": claim_type,
                    "claim_text": "The authors report positive momentum predictability.",
                    "normalized_claim": "Momentum predicts positive returns.",
                    "direction": "POSITIVE",
                    "support_strength": 0.8,
                    "confidence": 0.9,
                    "evidence": [{"source_text": quote, "section": "Results", "confidence": 0.9}],
                }
            ],
            "research_card_evidence": [
                {
                    "research_card_field": "market",
                    "evidence": {
                        "source_text": QUOTE,
                        "section": "Results",
                        "confidence": 0.8,
                    },
                }
            ],
        }
    )


@pytest.mark.asyncio
async def test_claim_requires_and_links_verbatim_evidence(tmp_path: Path) -> None:
    session, paper, document, card = setup_paper(tmp_path)
    try:
        extractor = ClaimEvidenceExtractor(
            session,
            FixtureLLMProvider([response()]),
            PyMuPDFParser(),
            "fixture-request",
        )
        result = await extractor.extract(paper, document, card, "run-m4")
        assert result.claims_created == 1
        assert result.evidence_created == 2
        claim = session.scalar(select(Claim))
        assert claim is not None
        assert claim.claim_type == "AUTHOR_CLAIM"
        pointer = session.scalar(select(Evidence).where(Evidence.claim_id == claim.id))
        assert pointer is not None
        assert pointer.page_number == 1
        assert document.parsed_text[pointer.start_offset : pointer.end_offset] == QUOTE
        assert field_verification_status(session, card, "market") == "VERIFIED"
        assert field_verification_status(session, card, "mechanism") == "UNVERIFIED"
    finally:
        session.close()


@pytest.mark.asyncio
async def test_fabricated_quote_cannot_create_claim(tmp_path: Path) -> None:
    session, paper, document, card = setup_paper(tmp_path)
    try:
        extractor = ClaimEvidenceExtractor(
            session,
            FixtureLLMProvider([response("This quote was invented.")]),
            PyMuPDFParser(),
            "fixture-request",
        )
        result = await extractor.extract(paper, document, card)
        assert result.claims_created == 0
        assert result.rejected_quotes == 1
        assert session.scalar(select(func.count()).select_from(Claim)) == 0
        assert session.scalar(select(func.count()).select_from(Evidence)) == 1
    finally:
        session.close()


def test_system_conclusion_is_rejected_by_schema() -> None:
    with pytest.raises(ValidationError):
        parse_json_model(response(claim_type="SYSTEM_CONCLUSION"), ClaimEvidenceExtraction)


def test_unknown_research_card_field_is_rejected(tmp_path: Path) -> None:
    session, _, _, card = setup_paper(tmp_path)
    try:
        with pytest.raises(ValueError, match="Unknown Research Card field"):
            field_verification_status(session, card, "invented_field")
    finally:
        session.close()
