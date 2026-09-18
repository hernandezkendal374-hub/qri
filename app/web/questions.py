"""Research questions, their briefs, and the single human decision gate.

Extracted from app.main so each surface can be read on its own; the route
bodies are unchanged.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    QuestionStatus,
    QuestionTranslation,
    ResearchQuestion,
    ResearchValidationSpec,
    StrategyIncubation,
)
from app.providers.llm.openai_compatible import OpenAICompatibleProvider
from app.research_validation import ResearchValidationService
from app.web.support import (
    handoff_package,
    strategy_export_package,
    validation_export_package,
)


def build_router(
    session_factory: Callable[[], Session],
    templates: Jinja2Templates,
) -> APIRouter:
    router = APIRouter()

    @router.get("/questions")
    def questions(request: Request):
        with session_factory() as session:
            active_rows = list(
                session.execute(
                    select(ResearchQuestion, QuestionTranslation)
                    .outerjoin(
                        QuestionTranslation,
                        QuestionTranslation.question_id == ResearchQuestion.id,
                    )
                    .where(ResearchQuestion.archived_at.is_(None))
                    .order_by(
                        ResearchQuestion.research_priority_score.desc().nullslast(),
                        ResearchQuestion.id,
                    )
                    .limit(100)
                ).all()
            )

            archived_rows = list(
                session.execute(
                    select(ResearchQuestion, QuestionTranslation)
                    .outerjoin(
                        QuestionTranslation,
                        QuestionTranslation.question_id == ResearchQuestion.id,
                    )
                    .where(ResearchQuestion.archived_at.is_not(None))
                    .order_by(ResearchQuestion.archived_at.desc())
                ).all()
            )
            handoff_by_question = {
                question.id: handoff_package(session, question, translation)
                for question, translation in active_rows + archived_rows
            }
            question_ids = [question.id for question, _ in active_rows + archived_rows]
            validation_specs = (
                list(
                    session.scalars(
                        select(ResearchValidationSpec).where(
                            ResearchValidationSpec.question_id.in_(question_ids)
                        )
                    )
                )
                if question_ids
                else []
            )
            validation_by_question = {item.question_id: item for item in validation_specs}
            legacy_rows = (
                list(
                    session.scalars(
                        select(StrategyIncubation).where(
                            StrategyIncubation.question_id.in_(question_ids)
                        )
                    )
                )
                if question_ids
                else []
            )
            legacy_by_question = {item.question_id: item for item in legacy_rows}
            local_zone = ZoneInfo("Asia/Shanghai")
            today = datetime.now(local_zone).date()
            grouped_rows: dict[Any, list[Any]] = {}
            for row in active_rows:
                created_at = row[0].created_at.replace(tzinfo=UTC)
                local_date = created_at.astimezone(local_zone).date()
                grouped_rows.setdefault(local_date, []).append(row)
            daily_groups = []
            for group_date in sorted(grouped_rows, reverse=True):
                if group_date == today:
                    label = f"今天 · {group_date.isoformat()}"
                elif group_date == today - timedelta(days=1):
                    label = f"昨天 · {group_date.isoformat()}"
                else:
                    label = group_date.isoformat()
                daily_groups.append(
                    {
                        "date": group_date.isoformat(),
                        "label": label,
                        "rows": grouped_rows[group_date],
                        "is_today": group_date == today,
                    }
                )
            return templates.TemplateResponse(
                request=request,
                name="questions.html",
                context={
                    "active_rows": active_rows,
                    "daily_groups": daily_groups,
                    "archived_rows": archived_rows,
                    "handoff_by_question": handoff_by_question,
                    "validation_by_question": validation_by_question,
                    "legacy_by_question": legacy_by_question,
                    "active": "questions",
                },
            )

    @router.post("/questions/{question_id}/archive")
    def archive_question(question_id: int):
        with session_factory() as session:
            question = session.get(ResearchQuestion, question_id)
            if not question:
                raise HTTPException(status_code=404, detail="研究问题不存在")
            question.archived_at = datetime.now(UTC).replace(tzinfo=None)
            session.commit()
        return RedirectResponse("/questions#archived-questions", status_code=303)

    @router.post("/questions/{question_id}/restore")
    def restore_question(question_id: int):
        with session_factory() as session:
            question = session.get(ResearchQuestion, question_id)
            if not question:
                raise HTTPException(status_code=404, detail="研究问题不存在")
            question.archived_at = None
            session.commit()
        return RedirectResponse(f"/questions#question-{question_id}", status_code=303)

    @router.get("/questions/{question_id}/handoff.json")
    def question_handoff(question_id: int):
        with session_factory() as session:
            question = session.get(ResearchQuestion, question_id)
            if not question:
                raise HTTPException(status_code=404, detail="研究问题不存在")
            translation = session.scalar(
                select(QuestionTranslation).where(QuestionTranslation.question_id == question_id)
            )
            package = handoff_package(session, question, translation)
        return JSONResponse(
            package,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{question.question_uid}-handoff.json"'
                )
            },
        )

    @router.post("/questions/{question_id}/validation-spec")
    async def generate_validation_spec(question_id: int):
        settings = get_settings()
        if not settings.llm_base_url or not settings.llm_api_key:
            raise HTTPException(status_code=503, detail="AI 模型尚未配置")
        with session_factory() as session:
            question = session.get(ResearchQuestion, question_id)
            if not question:
                raise HTTPException(status_code=404, detail="研究问题不存在")
            translation = session.scalar(
                select(QuestionTranslation).where(QuestionTranslation.question_id == question_id)
            )
            evidence_package = handoff_package(session, question, translation)
            provider = OpenAICompatibleProvider(
                settings.llm_base_url,
                settings.llm_api_key.get_secret_value(),
                timeout=max(settings.http_timeout_seconds, 600.0),
            )
            try:
                await ResearchValidationService(
                    session, provider, settings.validation_model
                ).generate(question, evidence_package)
            except Exception as exc:
                raise HTTPException(status_code=502, detail="研究验证方案生成失败") from exc
        return RedirectResponse(f"/questions#question-{question_id}", status_code=303)

    @router.post("/questions/{question_id}/approve")
    def approve_validation_spec(question_id: int):
        return decide_research_brief(question_id, "approve")

    @router.post("/questions/{question_id}/decision/{decision}")
    def decide_research_brief(question_id: int, decision: str):
        if decision not in {"approve", "defer", "reject"}:
            raise HTTPException(status_code=400, detail="未知人工决策")
        with session_factory() as session:
            question = session.get(ResearchQuestion, question_id)
            spec = session.scalar(
                select(ResearchValidationSpec).where(
                    ResearchValidationSpec.question_id == question_id
                )
            )
            if not question or not spec:
                raise HTTPException(status_code=404, detail="研究验证方案不存在")
            if decision == "approve":
                question.status = QuestionStatus.HUMAN_APPROVED
                spec.review_status = "APPROVED"
                spec.approved_at = datetime.now(UTC).replace(tzinfo=None)
            elif decision == "defer":
                question.status = QuestionStatus.DEFERRED
                spec.review_status = "DEFERRED"
                spec.approved_at = None
            else:
                question.status = QuestionStatus.REJECTED
                spec.review_status = "REJECTED"
                spec.approved_at = None
            session.commit()
        return RedirectResponse(f"/questions#question-{question_id}", status_code=303)

    @router.get("/questions/{question_id}/validation-spec.json")
    def export_validation_spec(question_id: int):
        with session_factory() as session:
            question = session.get(ResearchQuestion, question_id)
            spec = session.scalar(
                select(ResearchValidationSpec).where(
                    ResearchValidationSpec.question_id == question_id
                )
            )
            if not question or not spec:
                raise HTTPException(status_code=404, detail="研究验证方案不存在")
            if spec.review_status not in {"APPROVED", "EXPORTED"}:
                raise HTTPException(status_code=409, detail="必须先通过人工审核")
            spec.review_status = "EXPORTED"
            spec.exported_at = datetime.now(UTC).replace(tzinfo=None)
            question.status = QuestionStatus.EXPORTED
            package = validation_export_package(session, question, spec)
            session.commit()
        return JSONResponse(
            package,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{question.question_uid}-validation-spec.json"'
                )
            },
        )

    @router.post("/questions/{question_id}/incubate")
    def incubate_question(question_id: int) -> None:
        raise HTTPException(status_code=410, detail="策略孵化已移出 QRI")

    @router.get("/questions/{question_id}/strategy-spec.json")
    def strategy_spec(question_id: int):
        with session_factory() as session:
            question = session.get(ResearchQuestion, question_id)
            incubation = session.scalar(
                select(StrategyIncubation).where(StrategyIncubation.question_id == question_id)
            )
            if not question or not incubation:
                raise HTTPException(status_code=404, detail="策略孵化方案不存在")
            package = strategy_export_package(question, incubation)
        return JSONResponse(
            package,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{question.question_uid}-strategy-spec.json"'
                )
            },
        )

    return router
