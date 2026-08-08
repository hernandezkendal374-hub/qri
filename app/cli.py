import asyncio
from datetime import UTC, datetime
from pathlib import Path

import typer
from sqlalchemy import or_, select

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.discovery.registry import PaperRegistry
from app.discovery.service import DiscoveryService
from app.fulltext.downloader import PDFDownloader
from app.fulltext.service import FullTextService
from app.models import Paper, PipelineRun
from app.models.entities import FullTextStatus
from app.parsing.pymupdf_parser import PyMuPDFParser
from app.providers.papers.arxiv import ArxivProvider
from app.providers.papers.crossref import CrossrefProvider
from app.providers.papers.openalex import OpenAlexProvider
from app.providers.papers.semantic_scholar import SemanticScholarProvider
from app.providers.papers.unpaywall import UnpaywallProvider

app = typer.Typer(help="QRI literature intelligence CLI")


@app.callback()
def main() -> None:
    """Quant Research Intelligence."""


@app.command()
def search(query: str, limit: int = typer.Option(20, min=1, max=100)) -> None:
    """Search public scholarly APIs, deduplicate, persist, and show papers."""
    settings = get_settings()
    key = settings.semantic_scholar_api_key
    providers = [
        SemanticScholarProvider(
            api_key=key.get_secret_value() if key else None,
            timeout=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
        ),
        OpenAlexProvider(
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
            papers = session.scalars(
                select(Paper)
                .where(
                    Paper.fulltext_status != FullTextStatus.FULLTEXT_AVAILABLE,
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
            )
            successes = 0
            attempted = 0
            for paper in papers:
                if successes >= top:
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


if __name__ == "__main__":
    app()
