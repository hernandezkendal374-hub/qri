"""Retired strategy incubation surface, kept read-only.

Extracted from app.main so each surface can be read on its own; the route
bodies are unchanged.
"""

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    QuestionTranslation,
    ResearchQuestion,
    StrategyIncubation,
)


def build_router(
    session_factory: Callable[[], Session],
    templates: Jinja2Templates,
) -> APIRouter:
    router = APIRouter()

    @router.get("/strategies")
    def strategies_redirect() -> RedirectResponse:
        return RedirectResponse("/legacy-strategies", status_code=303)

    @router.get("/legacy-strategies")
    def legacy_strategies(request: Request):
        with session_factory() as session:
            rows = list(
                session.execute(
                    select(StrategyIncubation, ResearchQuestion, QuestionTranslation)
                    .join(
                        ResearchQuestion,
                        ResearchQuestion.id == StrategyIncubation.question_id,
                    )
                    .outerjoin(
                        QuestionTranslation,
                        QuestionTranslation.question_id == ResearchQuestion.id,
                    )
                    .order_by(
                        ResearchQuestion.research_priority_score.desc().nullslast(),
                        StrategyIncubation.id.desc(),
                    )
                ).all()
            )
            return templates.TemplateResponse(
                request=request,
                name="strategies.html",
                context={"rows": rows, "active": "strategies"},
            )

    @router.get("/strategies/{question_id}/backtest")
    def quick_backtest_page(question_id: int) -> RedirectResponse:
        return RedirectResponse("/legacy-strategies", status_code=303)

    @router.post("/strategies/{question_id}/backtest/run")
    def run_quick_backtest_route(question_id: int) -> None:
        raise HTTPException(status_code=410, detail="快速回测已移出 QRI 主流程")

    @router.post("/questions/{question_id}/advance")
    def advance_question_to_backtest(question_id: int) -> None:
        raise HTTPException(status_code=410, detail="请改用研究验证方案")

    @router.post("/strategies/{question_id}/reconstruct")
    def reconstruct_strategy(question_id: int) -> None:
        raise HTTPException(status_code=410, detail="策略重构已移出 QRI")

    return router
