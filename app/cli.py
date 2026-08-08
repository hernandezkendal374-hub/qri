import asyncio
from datetime import datetime

import typer

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.discovery.registry import PaperRegistry
from app.discovery.service import DiscoveryService
from app.models import PipelineRun
from app.providers.papers.arxiv import ArxivProvider
from app.providers.papers.crossref import CrossrefProvider
from app.providers.papers.openalex import OpenAlexProvider
from app.providers.papers.semantic_scholar import SemanticScholarProvider

app = typer.Typer(help="QRI literature intelligence CLI")


@app.callback()
def main() -> None:
    """Quant Research Intelligence."""


@app.command()
def search(query: str, limit: int = typer.Option(20, min=1, max=100)) -> None:
    """Search public scholarly APIs, deduplicate, persist, and show papers."""
    settings = get_settings()
    kwargs = {"timeout": settings.http_timeout_seconds, "max_retries": settings.http_max_retries}
    key = settings.semantic_scholar_api_key
    providers = [
        SemanticScholarProvider(api_key=key.get_secret_value() if key else None, **kwargs),
        OpenAlexProvider(**kwargs),
        CrossrefProvider(**kwargs),
        ArxivProvider(**kwargs),
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
        run.ended_at = datetime.utcnow()
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


if __name__ == "__main__":
    app()
