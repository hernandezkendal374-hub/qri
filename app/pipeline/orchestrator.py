from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.claims.service import ClaimEvidenceExtractor
from app.comparison.service import MultiPaperComparisonService
from app.discovery.registry import PaperRegistry
from app.discovery.service import DiscoveryService
from app.extraction.research_card import ResearchCardExtractor
from app.fulltext.downloader import PDFDownloader
from app.fulltext.service import FullTextService
from app.models import (
    Claim,
    Document,
    Paper,
    PaperComparison,
    PipelineRun,
    PipelineStageRun,
    ResearchCard,
)
from app.models.entities import FullTextStatus
from app.parsing.base import DocumentParser
from app.providers.llm.base import LLMProvider
from app.providers.papers.base import PaperProvider
from app.providers.papers.unpaywall import UnpaywallProvider
from app.question_factory.service import CandidateQuestionService


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class PipelineStage(StrEnum):
    SEARCH = "SEARCH"
    FULLTEXT = "FULLTEXT"
    RESEARCH_CARD = "RESEARCH_CARD"
    CLAIMS = "CLAIMS"
    QUESTIONS = "QUESTIONS"


@dataclass(slots=True)
class StageOutcome:
    checkpoint: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)


@dataclass(slots=True)
class PipelineOutcome:
    run_id: str
    status: str
    question_ids: list[int]


class PipelineOrchestrator:
    def __init__(
        self,
        *,
        session: Session,
        paper_providers: list[PaperProvider],
        llm_provider: LLMProvider,
        downloader: PDFDownloader,
        parser: DocumentParser,
        unpaywall: UnpaywallProvider,
        storage_dir: Path,
        primary_model: str,
        reasoning_model: str,
        limit_per_provider: int = 20,
    ) -> None:
        self.session = session
        self.paper_providers = paper_providers
        self.llm_provider = llm_provider
        self.downloader = downloader
        self.parser = parser
        self.unpaywall = unpaywall
        self.storage_dir = storage_dir
        self.primary_model = primary_model
        self.reasoning_model = reasoning_model
        self.limit_per_provider = limit_per_provider

    async def run(
        self,
        query: str,
        *,
        top: int = 3,
        resume_run_id: str | None = None,
    ) -> PipelineOutcome:
        if top != 3:
            raise ValueError("M6 end-to-end POC requires top=3 for three-paper comparison")
        pipeline = self._get_or_create_run(query, resume_run_id)
        if pipeline.status == "COMPLETE":
            checkpoint = self._checkpoint(pipeline.run_id, PipelineStage.QUESTIONS)
            return PipelineOutcome(
                pipeline.run_id, pipeline.status, checkpoint.get("question_ids", [])
            )
        await self._run_stage(
            pipeline,
            PipelineStage.SEARCH,
            lambda: self._search(pipeline, query),
        )
        await self._run_stage(
            pipeline,
            PipelineStage.FULLTEXT,
            lambda: self._fulltext(pipeline, top),
        )
        await self._run_stage(
            pipeline,
            PipelineStage.RESEARCH_CARD,
            lambda: self._research_cards(pipeline),
        )
        await self._run_stage(
            pipeline,
            PipelineStage.CLAIMS,
            lambda: self._claims(pipeline),
        )
        question_outcome = await self._run_stage(
            pipeline,
            PipelineStage.QUESTIONS,
            lambda: self._questions(pipeline),
        )
        pipeline.status = "COMPLETE"
        pipeline.current_stage = None
        pipeline.ended_at = utcnow()
        self.session.commit()
        return PipelineOutcome(
            pipeline.run_id,
            pipeline.status,
            question_outcome.checkpoint.get("question_ids", []),
        )

    def _get_or_create_run(self, query: str, resume_run_id: str | None) -> PipelineRun:
        if resume_run_id:
            pipeline = self.session.scalar(
                select(PipelineRun).where(PipelineRun.run_id == resume_run_id)
            )
            if not pipeline:
                raise ValueError(f"Unknown pipeline run_id: {resume_run_id}")
            if pipeline.query != query:
                raise ValueError("Resume query does not match the original pipeline query")
            return pipeline
        pipeline = PipelineRun(
            query=query,
            run_type="END_TO_END",
            status="RUNNING",
        )
        self.session.add(pipeline)
        self.session.commit()
        return pipeline

    async def _run_stage(
        self,
        pipeline: PipelineRun,
        name: PipelineStage,
        operation: Callable[[], Awaitable[StageOutcome]],
    ) -> StageOutcome:
        stage = self.session.scalar(
            select(PipelineStageRun).where(
                PipelineStageRun.run_id == pipeline.run_id,
                PipelineStageRun.stage == name.value,
            )
        )
        if stage and stage.status == "SUCCESS":
            return StageOutcome(stage.checkpoint_json, stage.metrics_json)
        if not stage:
            stage = PipelineStageRun(run_id=pipeline.run_id, stage=name.value)
            self.session.add(stage)
        stage.status = "RUNNING"
        stage.attempt_count = (stage.attempt_count or 0) + 1
        stage.started_at = utcnow()
        stage.ended_at = None
        stage.error_json = None
        pipeline.status = "RUNNING"
        pipeline.current_stage = name.value
        self.session.commit()
        try:
            outcome = await operation()
            stage = self._stage(pipeline.run_id, name)
            stage.status = "SUCCESS"
            stage.ended_at = utcnow()
            stage.checkpoint_json = outcome.checkpoint
            stage.metrics_json = outcome.metrics
            self.session.commit()
            return outcome
        except Exception as exc:
            self.session.rollback()
            stage = self._stage(pipeline.run_id, name)
            reloaded_pipeline = self.session.scalar(
                select(PipelineRun).where(PipelineRun.run_id == pipeline.run_id)
            )
            assert reloaded_pipeline is not None
            stage.status = "FAILED"
            stage.ended_at = utcnow()
            stage.error_json = {"type": type(exc).__name__, "message": str(exc)}
            reloaded_pipeline.status = "FAILED"
            reloaded_pipeline.current_stage = name.value
            self.session.commit()
            raise

    async def _search(self, pipeline: PipelineRun, query: str) -> StageOutcome:
        result = await DiscoveryService(self.paper_providers).search(
            query, limit_per_provider=self.limit_per_provider
        )
        papers = PaperRegistry(self.session).register(result.groups)
        pipeline.discovered_count = len(result.records)
        pipeline.deduplicated_count = len(papers)
        pipeline.error_count += len(result.errors)
        self.session.commit()
        return StageOutcome(
            {"paper_ids": [paper.id for paper in papers]},
            {
                "discovered": len(result.records),
                "deduplicated": len(papers),
                "provider_errors": result.errors,
            },
        )

    async def _fulltext(self, pipeline: PipelineRun, top: int) -> StageOutcome:
        paper_ids = self._checkpoint(pipeline.run_id, PipelineStage.SEARCH)["paper_ids"]
        papers = list(
            self.session.scalars(
                select(Paper)
                .where(Paper.id.in_(paper_ids))
                .order_by(Paper.citation_count.desc().nullslast(), Paper.id)
            )
        )
        service = FullTextService(
            self.session,
            self.downloader,
            self.parser,
            self.unpaywall,
            self.storage_dir,
        )
        successes: list[int] = []
        attempted = 0
        downloaded_successes = 0
        for paper in papers:
            if len(successes) >= top:
                break
            existing = self.session.scalar(
                select(Document).where(
                    Document.paper_id == paper.id,
                    Document.document_type == "PDF",
                    Document.parsed_text.is_not(None),
                )
            )
            if paper.fulltext_status == FullTextStatus.FULLTEXT_AVAILABLE and existing:
                successes.append(paper.id)
                continue
            attempted += 1
            result = await service.acquire(paper)
            if result.status == FullTextStatus.FULLTEXT_AVAILABLE:
                successes.append(paper.id)
                downloaded_successes += 1
        if len(successes) < top:
            raise RuntimeError(f"Only {len(successes)} of {top} required full texts are available")
        pipeline.fulltext_success_count = len(successes)
        pipeline.fulltext_failure_count = attempted - downloaded_successes
        self.session.commit()
        return StageOutcome(
            {"paper_ids": successes},
            {"fulltext_success": len(successes), "download_attempts": attempted},
        )

    async def _research_cards(self, pipeline: PipelineRun) -> StageOutcome:
        paper_ids = self._checkpoint(pipeline.run_id, PipelineStage.FULLTEXT)["paper_ids"]
        extractor = ResearchCardExtractor(self.session, self.llm_provider, self.primary_model)
        card_ids: list[int] = []
        created = 0
        for paper_id in paper_ids:
            card = self.session.scalar(
                select(ResearchCard).where(ResearchCard.paper_id == paper_id)
            )
            if not card:
                paper = self.session.get(Paper, paper_id)
                document = self.session.scalar(
                    select(Document).where(
                        Document.paper_id == paper_id, Document.document_type == "PDF"
                    )
                )
                assert paper is not None and document is not None
                card = await extractor.extract(paper, document, pipeline.run_id)
                created += 1
            card_ids.append(card.id)
        pipeline.research_card_count = len(card_ids)
        pipeline.ai_call_count += created
        self.session.commit()
        return StageOutcome(
            {"card_ids": card_ids, "paper_ids": paper_ids},
            {"cards": len(card_ids), "created": created},
        )

    async def _claims(self, pipeline: PipelineRun) -> StageOutcome:
        checkpoint = self._checkpoint(pipeline.run_id, PipelineStage.RESEARCH_CARD)
        extractor = ClaimEvidenceExtractor(
            self.session,
            self.llm_provider,
            self.parser,
            self.primary_model,
        )
        claim_ids: list[int] = []
        calls = 0
        for paper_id, card_id in zip(checkpoint["paper_ids"], checkpoint["card_ids"], strict=True):
            existing = list(self.session.scalars(select(Claim).where(Claim.paper_id == paper_id)))
            if not existing:
                paper = self.session.get(Paper, paper_id)
                card = self.session.get(ResearchCard, card_id)
                document = self.session.scalar(
                    select(Document).where(
                        Document.paper_id == paper_id, Document.document_type == "PDF"
                    )
                )
                assert paper is not None and card is not None and document is not None
                await extractor.extract(paper, document, card, pipeline.run_id)
                calls += 1
                existing = list(
                    self.session.scalars(select(Claim).where(Claim.paper_id == paper_id))
                )
            if not existing:
                raise RuntimeError(f"Paper {paper_id} produced no locally evidenced Claims")
            claim_ids.extend(claim.id for claim in existing)
        pipeline.claim_count = len(claim_ids)
        pipeline.ai_call_count += calls
        self.session.commit()
        return StageOutcome(
            {"claim_ids": claim_ids, "paper_ids": checkpoint["paper_ids"]},
            {"claims": len(claim_ids), "model_calls": calls},
        )

    async def _questions(self, pipeline: PipelineRun) -> StageOutcome:
        checkpoint = self._checkpoint(pipeline.run_id, PipelineStage.CLAIMS)
        papers = [self.session.get(Paper, paper_id) for paper_id in checkpoint["paper_ids"]]
        claims = list(
            self.session.scalars(select(Claim).where(Claim.id.in_(checkpoint["claim_ids"])))
        )
        valid_papers = [paper for paper in papers if paper is not None]
        comparison = self.session.scalar(
            select(PaperComparison)
            .where(PaperComparison.paper_ids_json == sorted(checkpoint["paper_ids"]))
            .order_by(PaperComparison.id.desc())
        )
        calls = 0
        if not comparison:
            comparison = await MultiPaperComparisonService(
                self.session, self.llm_provider, self.reasoning_model
            ).compare(valid_papers, claims, pipeline.run_id)
            calls += 1
        questions = await CandidateQuestionService(
            self.session, self.llm_provider, self.reasoning_model
        ).generate(comparison, claims, pipeline.run_id)
        calls += 1
        pipeline.question_count = len(questions)
        pipeline.ai_call_count += calls
        self.session.commit()
        return StageOutcome(
            {
                "comparison_id": comparison.id,
                "question_ids": [question.id for question in questions],
            },
            {"questions": len(questions), "reasoning_calls": calls},
        )

    def _checkpoint(self, run_id: str, stage: PipelineStage) -> dict:
        return self._stage(run_id, stage).checkpoint_json

    def _stage(self, run_id: str, stage: PipelineStage) -> PipelineStageRun:
        value = self.session.scalar(
            select(PipelineStageRun).where(
                PipelineStageRun.run_id == run_id,
                PipelineStageRun.stage == stage.value,
            )
        )
        if not value:
            raise RuntimeError(f"Missing pipeline stage checkpoint: {stage.value}")
        return value
