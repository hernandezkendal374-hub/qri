"""Author claims shown alongside the verbatim evidence behind them.

Extracted from app.main so each surface can be read on its own; the route
bodies are unchanged.
"""

from collections.abc import Callable

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Claim,
    Evidence,
    Paper,
)


def build_router(
    session_factory: Callable[[], Session],
    templates: Jinja2Templates,
) -> APIRouter:
    router = APIRouter()

    @router.get("/claims")
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

    return router
