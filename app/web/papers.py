"""The paper library, scope classification, and full-text acquisition.

Extracted from app.main so each surface can be read on its own; the route
bodies are unchanged.
"""

from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.extraction.abstract_brief import AbstractBriefExtractor
from app.fulltext.downloader import InvalidFullTextError, PDFDownloader
from app.fulltext.service import FullTextResult, FullTextService
from app.models import (
    AbstractBrief,
    Claim,
    Document,
    Evidence,
    Paper,
    ResearchCard,
)
from app.models.entities import FullTextStatus
from app.parsing.pymupdf_parser import PyMuPDFParser
from app.providers.llm.openai_compatible import OpenAICompatibleProvider
from app.providers.papers.openalex import OpenAlexProvider
from app.providers.papers.unpaywall import UnpaywallProvider
from app.scope.us_equity import SCOPE_VERSION
from app.web.support import (
    RESEARCH_SCOPE_LABELS,
    research_card_fields,
)


def build_router(
    session_factory: Callable[[], Session],
    templates: Jinja2Templates,
) -> APIRouter:
    router = APIRouter()

    @router.get("/papers")
    def papers(request: Request, scope: str = ""):
        with session_factory() as session:
            statement = select(Paper).order_by(Paper.id.desc()).limit(100)
            if scope in RESEARCH_SCOPE_LABELS:
                statement = statement.where(Paper.research_scope == scope)
            rows = list(session.scalars(statement))
            scope_counts: dict[str, int] = {
                scope_name: int(count)
                for scope_name, count in session.execute(
                    select(Paper.research_scope, func.count()).group_by(Paper.research_scope)
                ).all()
            }
            return templates.TemplateResponse(
                request=request,
                name="papers.html",
                context={
                    "papers": rows,
                    "scope": scope,
                    "scope_counts": scope_counts,
                    "scope_labels": RESEARCH_SCOPE_LABELS,
                    "active": "papers",
                },
            )

    @router.get("/papers/{paper_id}")
    def paper_detail(request: Request, paper_id: int, evidence: int | None = None):
        with session_factory() as session:
            paper = session.get(Paper, paper_id)
            if not paper:
                raise HTTPException(status_code=404, detail="Paper not found")
            documents = list(
                session.scalars(
                    select(Document)
                    .where(Document.paper_id == paper_id)
                    .order_by(Document.created_at)
                )
            )

            card = session.scalar(
                select(ResearchCard)
                .where(ResearchCard.paper_id == paper_id)
                .order_by(ResearchCard.id.desc())
            )
            brief = session.scalar(select(AbstractBrief).where(AbstractBrief.paper_id == paper_id))
            card_fields = research_card_fields(session, card) if card else []
            claims = list(
                session.scalars(select(Claim).where(Claim.paper_id == paper_id).order_by(Claim.id))
            )
            pointers = list(
                session.scalars(
                    select(Evidence).where(Evidence.paper_id == paper_id).order_by(Evidence.id)
                )
            )
            evidence_by_claim: dict[int, list[Evidence]] = {}
            evidence_by_field: dict[str, list[Evidence]] = {}
            for pointer in pointers:
                if pointer.claim_id:
                    evidence_by_claim.setdefault(pointer.claim_id, []).append(pointer)
                if pointer.research_card_field:
                    evidence_by_field.setdefault(pointer.research_card_field, []).append(pointer)
            return templates.TemplateResponse(
                request=request,
                name="paper_detail.html",
                context={
                    "paper": paper,
                    "documents": documents,
                    "card": card,
                    "brief": brief,
                    "card_fields": card_fields,
                    "claims": claims,
                    "pointers": pointers,
                    "evidence_by_claim": evidence_by_claim,
                    "evidence_by_field": evidence_by_field,
                    "selected_evidence": evidence,
                    "active": "papers",
                },
            )

    @router.post("/papers/{paper_id}/scope/{scope_code}")
    def set_paper_scope(paper_id: int, scope_code: str) -> RedirectResponse:
        allowed = {
            "US_EQUITY_CORE",
            "US_EQUITY_AUXILIARY",
            "OUT_OF_SCOPE",
            "MANUAL_REVIEW",
        }
        if scope_code not in allowed:
            raise HTTPException(status_code=400, detail="无效的研究范围")
        with session_factory() as session:
            paper = session.get(Paper, paper_id)
            if not paper:
                raise HTTPException(status_code=404, detail="论文不存在")
            paper.research_scope = scope_code
            paper.scope_reason = f"人工指定为：{RESEARCH_SCOPE_LABELS[scope_code]}。"
            paper.scope_confidence = 1.0
            paper.scope_version = SCOPE_VERSION
            session.commit()
        return RedirectResponse(f"/papers/{paper_id}", status_code=303)

    @router.post("/papers/{paper_id}/fulltext/retry")
    async def retry_fulltext(paper_id: int) -> RedirectResponse:
        settings = get_settings()
        with session_factory() as session:
            paper = session.get(Paper, paper_id)
            if not paper:
                raise HTTPException(status_code=404, detail="Paper not found")
            service = FullTextService(
                session,
                PDFDownloader(timeout=max(settings.http_timeout_seconds, 45.0)),
                PyMuPDFParser(),
                UnpaywallProvider(
                    settings.unpaywall_email,
                    timeout=settings.http_timeout_seconds,
                    max_retries=settings.http_max_retries,
                ),
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
            result = await service.acquire(paper)
        state = "available" if result.status == FullTextStatus.FULLTEXT_AVAILABLE else "failed"
        return RedirectResponse(
            f"/papers/{paper_id}?fulltext={state}#fulltext-access", status_code=303
        )

    @router.post("/papers/{paper_id}/fulltext/upload")
    async def upload_fulltext(request: Request, paper_id: int) -> JSONResponse:
        max_bytes = 50 * 1024 * 1024
        length = request.headers.get("content-length")
        if length and int(length) > max_bytes:
            raise HTTPException(status_code=413, detail="PDF 不能超过 50 MB")
        # Read in chunks and stop at the cap. Buffering the whole body first
        # would let a request without a content-length header exceed it.
        chunks: list[bytes] = []
        received = 0
        async for chunk in request.stream():
            received += len(chunk)
            if received > max_bytes:
                raise HTTPException(status_code=413, detail="PDF 不能超过 50 MB")
            chunks.append(chunk)
        content = b"".join(chunks)

        def _ingest() -> FullTextResult:
            with session_factory() as session:
                paper = session.get(Paper, paper_id)
                if not paper:
                    raise HTTPException(status_code=404, detail="Paper not found")
                service = FullTextService(
                    session,
                    PDFDownloader(max_bytes=max_bytes),
                    PyMuPDFParser(),
                    UnpaywallProvider(None),
                    storage_dir=Path("data/pdfs"),
                )
                try:
                    return service.ingest_uploaded_pdf(paper, content)
                except (InvalidFullTextError, ValueError) as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc

        # Parsing a 50 MB PDF is synchronous and slow enough to stall every
        # other request if it runs on the event loop.
        result = await run_in_threadpool(_ingest)
        return JSONResponse(
            {"status": "ok", "pages": result.page_count, "characters": result.character_count}
        )

    @router.post("/papers/{paper_id}/abstract-brief")
    async def generate_abstract_brief(paper_id: int):
        settings = get_settings()
        if not settings.llm_base_url or not settings.llm_api_key:
            raise HTTPException(status_code=503, detail="AI 模型尚未配置")
        with session_factory() as session:
            paper = session.get(Paper, paper_id)
            if not paper:
                raise HTTPException(status_code=404, detail="论文不存在")
            existing = session.scalar(
                select(AbstractBrief).where(AbstractBrief.paper_id == paper_id)
            )
            if not existing:
                if not paper.abstract:
                    raise HTTPException(status_code=400, detail="该论文没有可用摘要")
                provider = OpenAICompatibleProvider(
                    settings.llm_base_url,
                    settings.llm_api_key.get_secret_value(),
                    timeout=max(settings.http_timeout_seconds, 60.0),
                )
                try:
                    await AbstractBriefExtractor(session, provider, settings.primary_model).extract(
                        paper
                    )
                except Exception as exc:
                    raise HTTPException(status_code=502, detail="AI 摘要解读生成失败") from exc
        return RedirectResponse(f"/papers/{paper_id}#abstract-brief", status_code=303)

    return router
