import json
from pathlib import Path
from typing import Any

import httpx
import pymupdf
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.fulltext.downloader import PDFDownloader
from app.models import (
    AICall,
    Claim,
    Document,
    Evidence,
    Paper,
    PaperComparison,
    PipelineRun,
    PipelineStageRun,
    ResearchCard,
    ResearchQuestion,
)
from app.parsing.pymupdf_parser import PyMuPDFParser
from app.pipeline.orchestrator import PipelineOrchestrator
from app.providers.llm.base import LLMProvider, LLMResponse
from app.providers.papers.base import PaperProvider, ProviderPaper
from app.providers.papers.unpaywall import UnpaywallProvider

MARKET_QUOTE = "The sample covers United States equities."
CLAIM_QUOTE = "The authors report that momentum predicts positive returns."


class ThreePaperProvider(PaperProvider):
    name = "fixture_papers"

    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query: str, *, limit: int = 20) -> list[ProviderPaper]:
        self.calls += 1
        return [
            ProviderPaper(
                provider=self.name,
                provider_id=str(index),
                title=f"Momentum evidence paper {index}",
                abstract="A momentum abstract.",
                doi=f"10.1234/momentum.{index}",
                pdf_url=f"https://papers.test/{index}.pdf",
                open_access=True,
                citation_count=10 - index,
                raw_metadata={"index": index},
            )
            for index in range(1, 4)
        ]


class DynamicFixtureLLM(LLMProvider):
    def __init__(self, *, fail_first_card: bool = False) -> None:
        self.fail_first_card = fail_first_card
        self.calls = 0

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls += 1
        name = (response_schema or {}).get("name")
        if name == "paper_research_card":
            if self.fail_first_card:
                self.fail_first_card = False
                raise RuntimeError("temporary fixture model outage")
            content = (Path(__file__).parent / "fixtures" / "research_card_valid.json").read_text(
                encoding="utf-8"
            )
        elif name == "claim_evidence_extraction":
            content = json.dumps(
                {
                    "claims": [
                        {
                            "claim_type": "AUTHOR_CLAIM",
                            "claim_text": "The authors report positive momentum predictability.",
                            "normalized_claim": "Momentum predicts positive returns.",
                            "direction": "POSITIVE",
                            "support_strength": 0.8,
                            "confidence": 0.9,
                            "evidence": [
                                {
                                    "source_text": CLAIM_QUOTE,
                                    "section": "Results",
                                    "confidence": 1.0,
                                }
                            ],
                        }
                    ],
                    "research_card_evidence": [
                        {
                            "research_card_field": "market",
                            "evidence": {
                                "source_text": MARKET_QUOTE,
                                "section": "Data",
                                "confidence": 1.0,
                            },
                        }
                    ],
                }
            )
        elif name == "multi_paper_comparison":
            payload = json.loads(messages[-1]["content"])
            claim_ids = [claim["claim_id"] for claim in payload["claims"]]
            content = json.dumps(
                {
                    "common_findings": [
                        {
                            "statement": "All three author claims report momentum.",
                            "claim_ids": claim_ids,
                        }
                    ],
                    "differences": [],
                    "contradictions": [],
                    "sample_differences": [],
                    "universe_differences": [],
                    "signal_differences": [],
                    "cost_assumption_differences": [],
                    "oos_differences": [],
                    "survivorship_differences": [],
                    "possible_explanations": [],
                }
            )
        elif name == "candidate_question_set":
            payload = json.loads(messages[-1]["content"])
            claim_ids = [claim["claim_id"] for claim in payload["claims"]]
            content = json.dumps(
                {
                    "research_gap": "Post-2010 evidence after costs remains unresolved.",
                    "questions": [
                        {
                            "family": "Momentum",
                            "plain_language_question": (
                                "After real costs, does US stock momentum still work?"
                            ),
                            "academic_question": (
                                "After 2010, does point-in-time US equity momentum remain "
                                "positive after costs and delisting returns?"
                            ),
                            "economic_mechanism": "Investor underreaction",
                            "counter_mechanism": "Crowding and transaction costs",
                            "supporting_claim_ids": claim_ids,
                            "contradicting_claim_ids": [],
                            "required_data": ["Point-in-time universe", "Delisting returns"],
                            "known_risks": ["Survivorship bias", "Look-ahead bias"],
                            "novelty_score": 0.7,
                            "testability_score": 0.9,
                            "data_availability_score": 0.8,
                            "research_priority_score": 0.82,
                        }
                    ],
                }
            )
        else:
            raise AssertionError(f"Unexpected response schema: {name}")
        return LLMResponse(
            content=content,
            requested_model=model,
            returned_model="fixture-model",
            input_tokens=100,
            output_tokens=50,
            raw={"fixture": True},
        )


def make_pdf() -> bytes:
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), MARKET_QUOTE)
    page.insert_text((72, 100), CLAIM_QUOTE)
    content = pdf.tobytes()
    pdf.close()
    return content


def orchestrator(
    session: Session,
    paper_provider: ThreePaperProvider,
    llm: LLMProvider,
    downloader: PDFDownloader,
    storage: Path,
) -> PipelineOrchestrator:
    return PipelineOrchestrator(
        session=session,
        paper_providers=[paper_provider],
        llm_provider=llm,
        downloader=downloader,
        parser=PyMuPDFParser(),
        unpaywall=UnpaywallProvider(None),
        storage_dir=storage,
        primary_model="claude-sonnet-5",
        reasoning_model="gpt-5.4",
    )


@pytest.mark.asyncio
async def test_pipeline_recovers_from_failed_stage_without_duplicates(tmp_path: Path) -> None:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    paper_provider = ThreePaperProvider()
    pdf_content = make_pdf()
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content=pdf_content,
            headers={"content-type": "application/pdf"},
            request=request,
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        session = Session(engine)
        downloader = PDFDownloader(client=client)
        failing = orchestrator(
            session,
            paper_provider,
            DynamicFixtureLLM(fail_first_card=True),
            downloader,
            tmp_path / "pdfs",
        )
        with pytest.raises(RuntimeError, match="temporary fixture model outage"):
            await failing.run("momentum anomaly US equities")
        pipeline = session.scalar(select(PipelineRun))
        assert pipeline is not None
        assert pipeline.status == "FAILED"
        assert pipeline.current_stage == "RESEARCH_CARD"
        run_id = pipeline.run_id
        stages = {stage.stage: stage for stage in session.scalars(select(PipelineStageRun)).all()}
        assert stages["SEARCH"].status == "SUCCESS"
        assert stages["FULLTEXT"].status == "SUCCESS"
        assert stages["RESEARCH_CARD"].status == "FAILED"
        assert paper_provider.calls == 1

        resumed = orchestrator(
            session,
            paper_provider,
            DynamicFixtureLLM(),
            downloader,
            tmp_path / "pdfs",
        )
        outcome = await resumed.run("momentum anomaly US equities", resume_run_id=run_id)
        assert outcome.status == "COMPLETE"
        assert len(outcome.question_ids) == 1
        assert paper_provider.calls == 1
        assert session.scalar(select(func.count()).select_from(Paper)) == 3
        assert (
            session.scalar(
                select(func.count()).select_from(Document).where(Document.document_type == "PDF")
            )
            == 3
        )
        assert session.scalar(select(func.count()).select_from(ResearchCard)) == 3
        assert session.scalar(select(func.count()).select_from(Claim)) == 3
        assert session.scalar(select(func.count()).select_from(Evidence)) == 6
        assert session.scalar(select(func.count()).select_from(PaperComparison)) == 1
        assert session.scalar(select(func.count()).select_from(ResearchQuestion)) == 1
        assert session.scalar(select(func.count()).select_from(AICall)) == 9
        completed_stages = list(session.scalars(select(PipelineStageRun)))
        assert len(completed_stages) == 5
        assert all(stage.status == "SUCCESS" for stage in completed_stages)
        research_stage = next(stage for stage in completed_stages if stage.stage == "RESEARCH_CARD")
        assert research_stage.attempt_count == 2

        repeated = await resumed.run("momentum anomaly US equities", resume_run_id=run_id)
        assert repeated.status == "COMPLETE"
        assert session.scalar(select(func.count()).select_from(ResearchQuestion)) == 1
        session.close()
