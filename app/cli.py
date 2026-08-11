import asyncio
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import typer
from sqlalchemy import exists, func, or_, select

from app.claims.service import ClaimEvidenceExtractor
from app.comparison.service import MultiPaperComparisonService
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.discovery.registry import PaperRegistry
from app.discovery.service import DiscoveryService
from app.extraction.abstract_brief import AbstractBriefExtractor
from app.extraction.research_card import ResearchCardExtractor
from app.fulltext.downloader import PDFDownloader
from app.fulltext.service import FullTextService
from app.funnel.runner import create_funnel_run, execute_funnel
from app.models import (
    AbstractBrief,
    Claim,
    Document,
    Paper,
    PaperComparison,
    PipelineRun,
    QuestionTranslation,
    ResearchCard,
    ResearchQuestion,
)
from app.models.entities import FullTextStatus
from app.parsing.pymupdf_parser import PyMuPDFParser
from app.pipeline.orchestrator import PipelineOrchestrator
from app.providers.llm.openai_compatible import OpenAICompatibleProvider
from app.providers.papers.arxiv import ArxivProvider
from app.providers.papers.crossref import CrossrefProvider
from app.providers.papers.openalex import OpenAlexProvider
from app.providers.papers.semantic_scholar import SemanticScholarProvider
from app.providers.papers.unpaywall import UnpaywallProvider
from app.question_factory.service import CandidateQuestionService
from app.question_factory.translation import QuestionTranslationService
from app.scope.us_equity import (
    ELIGIBLE_SCOPES,
    SCOPE_VERSION,
    US_EQUITY_CORE,
    apply_scope,
)

app = typer.Typer(help="QRI literature intelligence CLI")
DAILY_QUERIES = (
    "US equity factor investing anomalies",
    "momentum anomaly US equities",
    "value anomaly US stock market",
    "low volatility anomaly equities",
    "quality profitability factor US equities",
    "post earnings announcement drift US stocks",
    "short interest securities lending equity returns",
    "market microstructure transaction costs equity anomalies",
    "machine learning asset pricing US equities",
    "alternative data equity return prediction",
    "institutional ownership limits to arbitrage US stocks",
    "factor crowding anomaly decay publication",
)


def _uncompared_claimed_paper_ids(session, limit: int = 1) -> list[int]:
    compared_ids = {
        paper_id
        for paper_ids in session.scalars(select(PaperComparison.paper_ids_json))
        for paper_id in (paper_ids or [])
    }
    statement = (
        select(Paper.id)
        .join(Claim, Claim.paper_id == Paper.id)
        .where(Paper.research_scope == US_EQUITY_CORE)
        .group_by(Paper.id)
        .order_by(Paper.citation_count.desc().nullslast(), Paper.id.desc())
        .limit(limit)
    )
    if compared_ids:
        statement = statement.where(Paper.id.notin_(compared_ids))
    return list(session.scalars(statement))


@app.callback()
def main() -> None:
    """Quant Research Intelligence."""


@app.command()
def search(query: str, limit: int = typer.Option(20, min=1, max=100)) -> None:
    """Search public scholarly APIs, deduplicate, persist, and show papers."""
    settings = get_settings()
    key = settings.semantic_scholar_api_key
    openalex_key = settings.openalex_api_key
    providers = [
        SemanticScholarProvider(
            api_key=key.get_secret_value() if key else None,
            timeout=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
        ),
        OpenAlexProvider(
            api_key=openalex_key.get_secret_value() if openalex_key else None,
            timeout=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
        ),
        CrossrefProvider(
            timeout=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
        ),
        ArxivProvider(
            timeout=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
        ),
    ]
    result = asyncio.run(DiscoveryService(providers).search(query, limit_per_provider=limit))
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        run = PipelineRun(
            query=query,
            discovered_count=len(result.records),
            deduplicated_count=len(result.groups),
            error_count=len(result.errors),
        )
        session.add(run)
        papers = PaperRegistry(session).register(result.groups)
        run.ended_at = datetime.now(UTC).replace(tzinfo=None)
        run.status = "COMPLETE"
        session.commit()
        typer.echo(f"Discovered: {len(result.records)}")
        typer.echo(f"After deduplication: {len(result.groups)}")
        typer.echo(f"With abstract: {sum(bool(p.abstract) for p in papers)}")
        fulltext_count = sum(p.fulltext_status.value == "FULLTEXT_AVAILABLE" for p in papers)
        typer.echo(f"With full text: {fulltext_count}")
        for index, paper in enumerate(papers, 1):
            typer.echo(f"{index:>2}. {paper.title} [{paper.publication_date or 'date unknown'}]")
        for provider, error in result.errors.items():
            typer.echo(f"Warning {provider}: {error}", err=True)


@app.command()
def daily(target: int = typer.Option(100, min=1, max=100)) -> None:
    """Collect TARGET new papers with rotating queries and no paid LLM analysis."""
    settings = get_settings()
    key = settings.semantic_scholar_api_key
    openalex_key = settings.openalex_api_key
    providers = [
        SemanticScholarProvider(
            api_key=key.get_secret_value() if key else None,
            timeout=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
        ),
        OpenAlexProvider(
            api_key=openalex_key.get_secret_value() if openalex_key else None,
            timeout=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
        ),
        CrossrefProvider(
            timeout=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
        ),
        ArxivProvider(
            timeout=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
        ),
    ]
    per_provider = min(100, max(25, (target + 1) // 2))
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        registry = PaperRegistry(session)
        start_index = date.today().toordinal() % len(DAILY_QUERIES)
        new_count = 0
        registered_count = 0
        discovered_count = 0
        errors: dict[str, str] = {}
        used_queries: list[str] = []
        for offset in range(len(DAILY_QUERIES)):
            if new_count >= target:
                break
            query = DAILY_QUERIES[(start_index + offset) % len(DAILY_QUERIES)]
            used_queries.append(query)
            result = asyncio.run(
                DiscoveryService(providers).search(query, limit_per_provider=per_provider)
            )
            discovered_count += len(result.records)
            errors.update(
                {f"{query} / {provider}": error for provider, error in result.errors.items()}
            )
            remaining = target - new_count
            selected_groups = result.groups[:remaining]
            before = session.scalar(select(func.count()).select_from(Paper)) or 0
            papers = registry.register(selected_groups)
            after = session.scalar(select(func.count()).select_from(Paper)) or 0
            registered_count += len(papers)
            new_count += after - before
        run = PipelineRun(
            query=" | ".join(used_queries),
            run_type="DAILY_DISCOVERY",
            status="COMPLETE",
            current_stage=None,
            ended_at=datetime.now(UTC).replace(tzinfo=None),
            discovered_count=discovered_count,
            deduplicated_count=new_count,
            error_count=len(errors),
        )
        session.add(run)
        session.commit()
        typer.echo(
            f"Daily collection complete: {registered_count} processed, "
            f"{new_count}/{target} new"
        )
        typer.echo(f"Queries: {' | '.join(used_queries)}")
        for source, error in errors.items():
            typer.echo(f"Warning {source}: {error}", err=True)


@app.command("daily-funnel")
def daily_funnel() -> None:
    """Run the UI-visible, cost-controlled daily research funnel."""
    Base.metadata.create_all(engine)
    run, created = create_funnel_run(SessionLocal)
    if not created:
        typer.echo(f"Daily funnel is already running: {run.run_id}")
        return
    typer.echo(f"Daily funnel started: {run.run_id}")
    execute_funnel(run.run_id, SessionLocal)
    with SessionLocal() as session:
        completed = session.scalar(select(PipelineRun).where(PipelineRun.run_id == run.run_id))
        typer.echo(
            f"Daily funnel {completed.status}: {completed.deduplicated_count} new papers, "
            f"{completed.research_card_count} cards, {completed.claim_count} claims, "
            f"{completed.question_count} questions, {completed.ai_call_count} AI calls"
        )


@app.command("resume-funnel")
def resume_funnel(run_id: str | None = None) -> None:
    """Resume an interrupted daily funnel from its first unfinished stage."""
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        statement = select(PipelineRun).where(PipelineRun.run_type == "DAILY_FUNNEL")
        if run_id:
            statement = statement.where(PipelineRun.run_id == run_id)
        else:
            statement = statement.where(PipelineRun.status == "RUNNING")
        run = session.scalar(statement.order_by(PipelineRun.id.desc()))
        if not run:
            typer.echo("No interrupted daily funnel was found.", err=True)
            raise typer.Exit(code=1)
        run.status = "RUNNING"
        run.ended_at = None
        session.commit()
    typer.echo(f"Resuming daily funnel: {run.run_id}")
    execute_funnel(run.run_id, SessionLocal)


@app.command()
def fetch(top: int = typer.Option(3, min=1, max=20)) -> None:
    """Acquire and parse up to TOP legal open-access full texts."""
    settings = get_settings()
    unpaywall = UnpaywallProvider(
        settings.unpaywall_email,
        timeout=settings.http_timeout_seconds,
        max_retries=settings.http_max_retries,
    )
    downloader = PDFDownloader(timeout=max(settings.http_timeout_seconds, 45.0))
    parser = PyMuPDFParser()

    async def run() -> None:
        with SessionLocal() as session:
            retry_before = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)
            papers = session.scalars(
                select(Paper)
                .where(
                    Paper.research_scope.in_(ELIGIBLE_SCOPES),
                    Paper.fulltext_status != FullTextStatus.FULLTEXT_AVAILABLE,
                    or_(
                        Paper.fulltext_attempted_at.is_(None),
                        Paper.fulltext_attempted_at < retry_before,
                    ),
                    or_(
                        Paper.arxiv_id.is_not(None),
                        Paper.pdf_url.is_not(None),
                        Paper.doi.is_not(None),
                    ),
                )
                .order_by(Paper.citation_count.desc().nullslast(), Paper.id)
            ).all()
            service = FullTextService(
                session,
                downloader,
                parser,
                unpaywall,
                storage_dir=Path("data/pdfs"),
                openalex=OpenAlexProvider(
                    api_key=(
                        settings.openalex_api_key.get_secret_value()
                        if settings.openalex_api_key
                        else None
                    ),
                    timeout=settings.http_timeout_seconds,
                    max_retries=settings.http_max_retries,
                ),
            )
            successes = 0
            attempted = 0
            max_attempts = max(10, top * 10)
            for paper in papers:
                if successes >= top or attempted >= max_attempts:
                    break
                attempted += 1
                result = await service.acquire(paper)
                if result.status == FullTextStatus.FULLTEXT_AVAILABLE:
                    successes += 1
                    typer.echo(
                        f"OK {paper.id}: {result.page_count} pages, "
                        f"{result.character_count} chars — {paper.title}"
                    )
                else:
                    typer.echo(f"SKIP {paper.id}: {result.status.value} — {paper.title}", err=True)
            session.add(
                PipelineRun(
                    query=f"[FULLTEXT] top={top}",
                    status="COMPLETE",
                    started_at=datetime.now(UTC).replace(tzinfo=None),
                    ended_at=datetime.now(UTC).replace(tzinfo=None),
                    discovered_count=attempted,
                    fulltext_success_count=successes,
                    fulltext_failure_count=attempted - successes,
                    error_count=attempted - successes,
                )
            )
            session.commit()
            typer.echo(f"Parsed full texts: {successes}/{top} (attempted {attempted})")

    asyncio.run(run())


@app.command()
def briefs(top: int = typer.Option(10, min=1, max=100)) -> None:
    """Generate Chinese abstract-level explanations for papers without a brief."""
    settings = get_settings()
    if not settings.llm_base_url or not settings.llm_api_key:
        typer.echo("LLM is not configured.", err=True)
        raise typer.Exit(code=2)
    provider = OpenAICompatibleProvider(
        settings.llm_base_url,
        settings.llm_api_key.get_secret_value(),
        timeout=max(settings.http_timeout_seconds, 60.0),
    )

    async def run() -> None:
        with SessionLocal() as session:
            pending_scope = list(
                session.scalars(
                    select(Paper).where(
                        or_(
                            Paper.scope_version.is_(None),
                            Paper.scope_version != SCOPE_VERSION,
                        )
                    )
                )
            )
            for paper in pending_scope:
                apply_scope(paper)
            session.commit()
            papers = list(
                session.scalars(
                    select(Paper)
                    .where(
                        Paper.abstract.is_not(None),
                        Paper.research_scope.in_(ELIGIBLE_SCOPES),
                        ~exists(select(AbstractBrief.id).where(AbstractBrief.paper_id == Paper.id)),
                        ~exists(select(ResearchCard.id).where(ResearchCard.paper_id == Paper.id)),
                    )
                    .order_by(Paper.citation_count.desc().nullslast(), Paper.id)
                    .limit(top)
                )
            )
            extractor = AbstractBriefExtractor(session, provider, settings.primary_model)
            success = 0
            for paper in papers:
                try:
                    await extractor.extract(paper)
                    success += 1
                    typer.echo(f"OK {paper.id}: Abstract Brief — {paper.title}")
                except Exception as exc:
                    typer.echo(f"ERROR {paper.id}: {type(exc).__name__}: {exc}", err=True)
            typer.echo(f"Abstract Briefs: {success}/{len(papers)}")

    asyncio.run(run())


@app.command("scope-papers")
def scope_papers(force: bool = False) -> None:
    """Classify papers for the US-equity strategy funnel without using AI."""
    with SessionLocal() as session:
        statement = select(Paper)
        if not force:
            statement = statement.where(
                or_(Paper.scope_version.is_(None), Paper.scope_version != SCOPE_VERSION)
            )
        papers = list(session.scalars(statement))
        counts: dict[str, int] = {}
        for paper in papers:
            decision = apply_scope(paper)
            counts[decision.scope] = counts.get(decision.scope, 0) + 1
        session.commit()
    typer.echo(f"Scoped papers: {len(papers)} — {counts}")


@app.command()
def analyze(top: int = typer.Option(3, min=1, max=20)) -> None:
    """Generate strict Research Cards from verified parsed PDF full text."""
    settings = get_settings()
    if not settings.llm_base_url or not settings.llm_api_key:
        typer.echo(
            "LLM is not configured. Set LLM_BASE_URL and LLM_API_KEY in .env. "
            "No fixture output was written to the research database.",
            err=True,
        )
        raise typer.Exit(code=2)
    provider = OpenAICompatibleProvider(
        settings.llm_base_url,
        settings.llm_api_key.get_secret_value(),
        timeout=max(settings.http_timeout_seconds, 60.0),
    )

    async def run() -> None:
        with SessionLocal() as session:
            rows = session.execute(
                select(Paper, Document)
                .join(Document, Document.paper_id == Paper.id)
                .where(
                    Paper.research_scope.in_(ELIGIBLE_SCOPES),
                    Paper.fulltext_status == FullTextStatus.FULLTEXT_AVAILABLE,
                    Document.document_type == "PDF",
                    ~exists(select(ResearchCard.id).where(ResearchCard.paper_id == Paper.id)),
                )
                .order_by(Paper.id)
                .limit(top)
            ).all()
            pipeline = PipelineRun(query=f"[RESEARCH_CARD] top={top}")
            session.add(pipeline)
            session.commit()
            successes = 0
            errors = 0
            extractor = ResearchCardExtractor(session, provider, settings.primary_model)
            for paper, document in rows:
                try:
                    await extractor.extract(paper, document, pipeline.run_id)
                    successes += 1
                    typer.echo(f"OK {paper.id}: Research Card — {paper.title}")
                except Exception as exc:
                    errors += 1
                    typer.echo(f"ERROR {paper.id}: {type(exc).__name__}: {exc}", err=True)
            pipeline.ended_at = datetime.now(UTC).replace(tzinfo=None)
            pipeline.status = "COMPLETE"
            pipeline.ai_call_count = len(rows)
            pipeline.error_count = errors
            pipeline.research_card_count = successes
            session.commit()
            typer.echo(f"Research Cards: {successes}/{len(rows)}")

    asyncio.run(run())


@app.command()
def claims(top: int = typer.Option(3, min=1, max=20)) -> None:
    """Extract AUTHOR_CLAIM records with locally verified Evidence Pointers."""
    settings = get_settings()
    if not settings.llm_base_url or not settings.llm_api_key:
        typer.echo(
            "LLM is not configured. Set LLM_BASE_URL and LLM_API_KEY in .env. "
            "No fixture claims were written to the research database.",
            err=True,
        )
        raise typer.Exit(code=2)
    provider = OpenAICompatibleProvider(
        settings.llm_base_url,
        settings.llm_api_key.get_secret_value(),
        timeout=max(settings.http_timeout_seconds, 60.0),
    )

    async def run() -> None:
        with SessionLocal() as session:
            rows = session.execute(
                select(Paper, Document, ResearchCard)
                .join(Document, Document.paper_id == Paper.id)
                .join(ResearchCard, ResearchCard.paper_id == Paper.id)
                .where(
                    Document.document_type == "PDF",
                    ~exists(select(Claim.id).where(Claim.paper_id == Paper.id)),
                )
                .order_by(Paper.id)
                .limit(top)
            ).all()
            pipeline = PipelineRun(query=f"[CLAIM_EVIDENCE] top={top}")
            session.add(pipeline)
            session.commit()
            extractor = ClaimEvidenceExtractor(
                session, provider, PyMuPDFParser(), settings.primary_model
            )
            claim_count = 0
            errors = 0
            for paper, document, card in rows:
                try:
                    result = await extractor.extract(paper, document, card, pipeline.run_id)
                    claim_count += result.claims_created
                    typer.echo(
                        f"OK {paper.id}: {result.claims_created} claims, "
                        f"{result.evidence_created} evidence pointers, "
                        f"{result.rejected_quotes} rejected quotes"
                    )
                except Exception as exc:
                    errors += 1
                    typer.echo(f"ERROR {paper.id}: {type(exc).__name__}: {exc}", err=True)
            pipeline.ended_at = datetime.now(UTC).replace(tzinfo=None)
            pipeline.status = "COMPLETE"
            pipeline.ai_call_count = len(rows)
            pipeline.error_count = errors
            pipeline.claim_count = claim_count
            session.commit()
            typer.echo(f"Claims created: {claim_count} from {len(rows)} papers")

    asyncio.run(run())


@app.command()
def questions() -> None:
    """Compare one to three claimed papers and generate Candidate Research Questions."""
    settings = get_settings()
    if not settings.llm_base_url or not settings.llm_api_key:
        typer.echo(
            "LLM is not configured. Set LLM_BASE_URL and LLM_API_KEY in .env. "
            "No fixture comparisons or questions were written.",
            err=True,
        )
        raise typer.Exit(code=2)
    provider = OpenAICompatibleProvider(
        settings.llm_base_url,
        settings.llm_api_key.get_secret_value(),
        timeout=max(settings.http_timeout_seconds, 180.0),
    )

    async def run() -> None:
        Base.metadata.create_all(engine)
        with SessionLocal() as session:
            comparison = session.scalar(
                select(PaperComparison)
                .where(PaperComparison.research_gap.is_(None))
                .order_by(PaperComparison.id.desc())
            )
            paper_ids = (
                list(comparison.paper_ids_json)
                if comparison
                else _uncompared_claimed_paper_ids(session)
            )
            if not 1 <= len(paper_ids) <= 3:
                typer.echo(
                    "Question generation skipped: "
                    f"need at least 1 new claimed paper, currently {len(paper_ids)}."
                )
                return
            papers = list(session.scalars(select(Paper).where(Paper.id.in_(paper_ids))))
            source_claims = list(
                session.scalars(select(Claim).where(Claim.paper_id.in_(paper_ids)))
            )
            pipeline = PipelineRun(query=f"[QUESTIONS] {len(paper_ids)}-paper analysis")
            session.add(pipeline)
            session.commit()
            if comparison is None:
                comparison = await MultiPaperComparisonService(
                    session, provider, settings.reasoning_model
                ).compare(papers, source_claims, pipeline.run_id)
            else:
                typer.echo(f"Resuming comparison: {comparison.comparison_uid}")
            generated = await CandidateQuestionService(
                session, provider, settings.reasoning_model
            ).generate(comparison, source_claims, pipeline.run_id)
            pipeline.ended_at = datetime.now(UTC).replace(tzinfo=None)
            pipeline.status = "COMPLETE"
            pipeline.ai_call_count = 2
            pipeline.question_count = len(generated)
            session.commit()
            typer.echo(f"Comparison: {comparison.comparison_uid}")
            if not generated:
                typer.echo("No new questions: generated candidates matched existing questions.")
            for question in generated:
                typer.echo(f"{question.question_uid} [{question.status.value}] {question.question}")

    asyncio.run(run())


@app.command("translate-questions")
def translate_questions() -> None:
    """Translate untranslated candidate questions into Simplified Chinese."""
    settings = get_settings()
    if not settings.llm_base_url or not settings.llm_api_key:
        typer.echo("LLM is not configured.", err=True)
        raise typer.Exit(code=2)
    provider = OpenAICompatibleProvider(
        settings.llm_base_url,
        settings.llm_api_key.get_secret_value(),
        timeout=max(settings.http_timeout_seconds, 60.0),
    )

    async def run() -> None:
        with SessionLocal() as session:
            rows = list(
                session.scalars(
                    select(ResearchQuestion)
                    .where(
                        ~exists(
                            select(QuestionTranslation.id).where(
                                QuestionTranslation.question_id == ResearchQuestion.id
                            )
                        )
                    )
                    .order_by(ResearchQuestion.research_priority_score.desc())
                )
            )
            translated = await QuestionTranslationService(
                session, provider, settings.primary_model
            ).translate(rows)
            typer.echo(f"Question translations: {len(translated)}/{len(rows)}")

    asyncio.run(run())


@app.command("pipeline")
def pipeline_command(
    query: str,
    top: int = typer.Option(3, min=3, max=3),
    resume: str | None = typer.Option(None, help="Resume an existing run_id"),
) -> None:
    """Run the complete resumable QRI POC pipeline."""
    settings = get_settings()
    if not settings.llm_base_url or not settings.llm_api_key:
        typer.echo(
            "LLM is not configured. Set LLM_BASE_URL and LLM_API_KEY in .env. "
            "The end-to-end pipeline was not started.",
            err=True,
        )
        raise typer.Exit(code=2)
    key = settings.semantic_scholar_api_key
    openalex_key = settings.openalex_api_key
    common = {
        "timeout": settings.http_timeout_seconds,
        "max_retries": settings.http_max_retries,
    }
    paper_providers = [
        SemanticScholarProvider(
            api_key=key.get_secret_value() if key else None,
            timeout=common["timeout"],
            max_retries=int(common["max_retries"]),
        ),
        OpenAlexProvider(
            api_key=openalex_key.get_secret_value() if openalex_key else None,
            timeout=common["timeout"],
            max_retries=int(common["max_retries"]),
        ),
        CrossrefProvider(timeout=common["timeout"], max_retries=int(common["max_retries"])),
        ArxivProvider(timeout=common["timeout"], max_retries=int(common["max_retries"])),
    ]
    llm = OpenAICompatibleProvider(
        settings.llm_base_url,
        settings.llm_api_key.get_secret_value(),
        timeout=max(settings.http_timeout_seconds, 60.0),
    )

    async def run() -> None:
        Base.metadata.create_all(engine)
        with SessionLocal() as session:
            orchestrator = PipelineOrchestrator(
                session=session,
                paper_providers=paper_providers,
                llm_provider=llm,
                downloader=PDFDownloader(timeout=max(settings.http_timeout_seconds, 45.0)),
                parser=PyMuPDFParser(),
                unpaywall=UnpaywallProvider(
                    settings.unpaywall_email,
                    timeout=settings.http_timeout_seconds,
                    max_retries=settings.http_max_retries,
                ),
                storage_dir=Path("data/pdfs"),
                primary_model=settings.primary_model,
                reasoning_model=settings.reasoning_model,
            )
            try:
                outcome = await orchestrator.run(query, top=top, resume_run_id=resume)
            except Exception as exc:
                failed = session.scalar(
                    select(PipelineRun)
                    .where(PipelineRun.query == query)
                    .order_by(PipelineRun.id.desc())
                )
                if failed:
                    typer.echo(
                        f"Pipeline {failed.run_id} failed at {failed.current_stage}: {exc}",
                        err=True,
                    )
                raise typer.Exit(code=1) from exc
            typer.echo(f"Pipeline {outcome.run_id}: {outcome.status}")
            typer.echo(f"Question IDs: {outcome.question_ids}")

    asyncio.run(run())


if __name__ == "__main__":
    app()
