from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.evidence.verification import field_verification_status
from app.models import Claim, Document, Evidence, Paper, ResearchCard, ResearchQuestion
from app.schemas.research import PaperResearchCard

APP_DIR = Path(__file__).resolve().parent
CARD_STORAGE_FIELDS = {
    "robustness_tests": "robustness_tests_json",
    "required_data": "required_data_json",
    "limitations": "limitations_json",
}


def create_app(session_factory: Callable[[], Session] = SessionLocal) -> FastAPI:
    web = FastAPI(title="QRI", version="0.1.0")
    templates = Jinja2Templates(directory=APP_DIR / "templates")
    web.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

    @web.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @web.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/papers", status_code=303)

    @web.get("/papers")
    def papers(request: Request):
        with session_factory() as session:
            rows = list(session.scalars(select(Paper).order_by(Paper.id.desc()).limit(100)))
            return templates.TemplateResponse(
                request=request,
                name="papers.html",
                context={"papers": rows, "active": "papers"},
            )

    @web.get("/papers/{paper_id}")
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
            card_fields = _card_fields(session, card) if card else []
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
                    "card_fields": card_fields,
                    "claims": claims,
                    "pointers": pointers,
                    "evidence_by_claim": evidence_by_claim,
                    "evidence_by_field": evidence_by_field,
                    "selected_evidence": evidence,
                    "active": "papers",
                },
            )

    @web.get("/claims")
    def claims(request: Request):
        with session_factory() as session:
            rows = list(
                session.execute(
                    select(Claim, Paper)
                    .join(Paper, Paper.id == Claim.paper_id)
                    .order_by(Claim.id.desc())
                    .limit(200)
                ).all()
            )
            claim_ids = [claim.id for claim, _ in rows]
            pointers = (
                list(session.scalars(select(Evidence).where(Evidence.claim_id.in_(claim_ids))))
                if claim_ids
                else []
            )
            evidence_by_claim: dict[int, list[Evidence]] = {}
            for pointer in pointers:
                if pointer.claim_id:
                    evidence_by_claim.setdefault(pointer.claim_id, []).append(pointer)
            return templates.TemplateResponse(
                request=request,
                name="claims.html",
                context={
                    "rows": rows,
                    "evidence_by_claim": evidence_by_claim,
                    "active": "claims",
                },
            )

    @web.get("/questions")
    def questions(request: Request):
        with session_factory() as session:
            rows = list(
                session.scalars(
                    select(ResearchQuestion).order_by(ResearchQuestion.id.desc()).limit(100)
                )
            )
            return templates.TemplateResponse(
                request=request,
                name="questions.html",
                context={"questions": rows, "active": "questions"},
            )

    return web


def _card_fields(session: Session, card: ResearchCard) -> list[dict[str, Any]]:
    fields = []
    for field_name in PaperResearchCard.model_fields:
        storage_name = CARD_STORAGE_FIELDS.get(field_name, field_name)
        value = getattr(card, storage_name)
        fields.append(
            {
                "name": field_name,
                "value": value,
                "status": field_verification_status(session, card, field_name),
            }
        )
    return fields


app = create_app()
