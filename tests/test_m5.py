import json

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.comparison.service import MultiPaperComparisonService
from app.db.base import Base
from app.db.session import build_engine
from app.extraction.json_parser import parse_json_model
from app.models import AICall, Claim, Paper, PaperComparison, QuestionStatus, ResearchQuestion
from app.providers.llm.fixture import FixtureLLMProvider
from app.question_factory.export import QuestionExportError, export_candidate_question
from app.question_factory.service import CandidateQuestionService
from app.schemas.comparison import CandidateQuestionSet


def setup_claims() -> tuple[Session, list[Paper], list[Claim]]:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    papers: list[Paper] = []
    claims: list[Claim] = []
    for index in range(3):
        paper = Paper(
            title=f"Momentum paper {index + 1}",
            normalized_title=f"momentum paper {index + 1}",
            authors_json=[],
            source="test",
        )
        session.add(paper)
        session.flush()
        claim = Claim(
            paper_id=paper.id,
            claim_type="AUTHOR_CLAIM",
            claim_text=f"Paper {index + 1} reports a momentum result.",
            direction="POSITIVE" if index < 2 else "MIXED",
        )
        session.add(claim)
        papers.append(paper)
        claims.append(claim)
    session.commit()
    return session, papers, claims


def comparison_json(claims: list[Claim], invalid_id: int | None = None) -> str:
    first_id = invalid_id or claims[0].id
    return json.dumps(
        {
            "common_findings": [
                {
                    "statement": "Two papers report positive momentum.",
                    "claim_ids": [first_id, claims[1].id],
                }
            ],
            "differences": [
                {
                    "statement": "The third result is mixed.",
                    "claim_ids": [claims[1].id, claims[2].id],
                }
            ],
            "contradictions": [],
            "sample_differences": [],
            "universe_differences": [],
            "signal_differences": [],
            "cost_assumption_differences": [],
            "oos_differences": [],
            "survivorship_differences": [],
            "possible_explanations": [
                {
                    "statement": "Different samples may explain the variation.",
                    "claim_ids": [claims[0].id, claims[2].id],
                }
            ],
        }
    )


def questions_json(claims: list[Claim]) -> str:
    base = {
        "family": "Momentum",
        "economic_mechanism": "Investor underreaction and information diffusion",
        "counter_mechanism": "Factor crowding, costs, and regime dependence",
        "supporting_claim_ids": [claims[0].id, claims[1].id],
        "contradicting_claim_ids": [claims[2].id],
        "required_data": ["Point-in-time US equity universe", "Delisting returns"],
        "known_risks": ["Survivorship bias", "Look-ahead bias", "Multiple testing"],
        "novelty_score": 0.7,
        "testability_score": 0.9,
        "data_availability_score": 0.8,
        "research_priority_score": 0.82,
    }
    return json.dumps(
        {
            "research_gap": "Post-2010 point-in-time evidence with realistic costs is mixed.",
            "questions": [
                {
                    **base,
                    "question": (
                        "In a point-in-time US equity universe after 2010, does 12-1 "
                        "momentum retain positive risk-adjusted returns after costs and delistings?"
                    ),
                },
                {
                    **base,
                    "question": (
                        "Does the post-2010 momentum effect weaken during high-crowding "
                        "regimes after controlling for transaction costs?"
                    ),
                },
            ],
        }
    )


@pytest.mark.asyncio
async def test_comparison_and_questions_use_known_claim_ids() -> None:
    session, papers, claims = setup_claims()
    try:
        provider = FixtureLLMProvider([comparison_json(claims), questions_json(claims)])
        comparison = await MultiPaperComparisonService(session, provider, "gpt-5.4").compare(
            papers, claims, "run-m5"
        )
        generated = await CandidateQuestionService(session, provider, "gpt-5.4").generate(
            comparison, claims, "run-m5"
        )
        assert len(generated) == 2
        assert generated[0].question_uid == "RQ-MOMENTUM-0001"
        assert generated[1].question_uid == "RQ-MOMENTUM-0002"
        assert all(q.status == QuestionStatus.HUMAN_REVIEW_REQUIRED for q in generated)
        assert comparison.research_gap
        audits = list(session.scalars(select(AICall).order_by(AICall.id)))
        assert [audit.requested_model for audit in audits] == ["gpt-5.4", "gpt-5.4"]
        assert [audit.prompt_version for audit in audits] == [
            "multi-paper-comparison-v1",
            "candidate-question-v1",
        ]
    finally:
        session.close()


@pytest.mark.asyncio
async def test_unknown_claim_id_rejects_entire_comparison() -> None:
    session, papers, claims = setup_claims()
    try:
        provider = FixtureLLMProvider([comparison_json(claims, invalid_id=999999)])
        with pytest.raises(ValueError, match="unknown Claim IDs"):
            await MultiPaperComparisonService(session, provider, "gpt-5.4").compare(papers, claims)
        assert session.scalar(select(func.count()).select_from(PaperComparison)) == 0
        audit = session.scalar(select(AICall))
        assert audit is not None and audit.status == "VALIDATION_ERROR"
    finally:
        session.close()


def test_question_set_allows_only_one_to_three_questions() -> None:
    with pytest.raises(ValidationError):
        parse_json_model('{"research_gap":"gap","questions":[]}', CandidateQuestionSet)


def test_export_gate_requires_human_approval() -> None:
    session, _, _ = setup_claims()
    try:
        question = ResearchQuestion(
            question_uid="RQ-MOMENTUM-0001",
            family="Momentum",
            question="Does momentum survive costs in a point-in-time US equity universe?",
            economic_mechanism="Underreaction",
            counter_mechanism="Crowding",
            supporting_claims_json=[1],
            contradicting_claims_json=[],
            required_data_json=["Prices"],
            known_risks_json=["Survivorship bias"],
            status=QuestionStatus.HUMAN_REVIEW_REQUIRED,
        )
        session.add(question)
        session.commit()
        with pytest.raises(QuestionExportError, match="HUMAN_APPROVED"):
            export_candidate_question(session, question)
        question.status = QuestionStatus.HUMAN_APPROVED
        session.commit()
        payload = export_candidate_question(session, question)
        assert payload["status"] == "HUMAN_APPROVED"
        assert question.status == QuestionStatus.EXPORTED
    finally:
        session.close()
