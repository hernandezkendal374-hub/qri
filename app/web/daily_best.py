"""The archive of completed Research Briefs, by day.

Extracted from app.main so each surface can be read on its own; the route
bodies are unchanged.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    QuestionTranslation,
    ResearchQuestion,
    ResearchValidationSpec,
)
from app.web.support import (
    research_merit,
)


def build_router(
    session_factory: Callable[[], Session],
    templates: Jinja2Templates,
) -> APIRouter:
    router = APIRouter()

    @router.get("/daily-best")
    def daily_best_archive(request: Request, q: str = ""):
        query_text = q.strip()
        with session_factory() as session:
            statement = (
                select(ResearchQuestion, QuestionTranslation, ResearchValidationSpec)
                .join(
                    ResearchValidationSpec,
                    ResearchValidationSpec.question_id == ResearchQuestion.id,
                )
                .outerjoin(
                    QuestionTranslation,
                    QuestionTranslation.question_id == ResearchQuestion.id,
                )
                .order_by(ResearchQuestion.created_at.desc())
            )
            if query_text:
                try:
                    search_date = date.fromisoformat(query_text)
                except ValueError:
                    search_date = None
                if search_date:
                    local_zone = ZoneInfo("Asia/Shanghai")
                    local_start = datetime.combine(search_date, datetime.min.time(), local_zone)
                    utc_start = local_start.astimezone(UTC).replace(tzinfo=None)
                    utc_end = (local_start + timedelta(days=1)).astimezone(UTC).replace(tzinfo=None)
                    statement = statement.where(
                        ResearchQuestion.created_at >= utc_start,
                        ResearchQuestion.created_at < utc_end,
                    )
                else:
                    pattern = f"%{query_text}%"
                    statement = statement.where(
                        or_(
                            ResearchQuestion.question.ilike(pattern),
                            ResearchQuestion.question_uid.ilike(pattern),
                            QuestionTranslation.question_zh.ilike(pattern),
                        )
                    )
            rows = list(session.execute(statement).all())
            local_zone = ZoneInfo("Asia/Shanghai")
            grouped: dict[Any, list[dict[str, Any]]] = {}
            for question, translation, validation in rows:
                local_date = question.created_at.replace(tzinfo=UTC).astimezone(local_zone).date()
                merit = research_merit(session, question)
                grouped.setdefault(local_date, []).append(
                    {
                        "question": question,
                        "translation": translation,
                        "validation": validation,
                        "merit": merit,
                        "score": merit["score"],
                    }
                )
            archive_groups = []
            for group_date in sorted(grouped, reverse=True):
                candidates = sorted(
                    grouped[group_date],
                    key=lambda item: item["score"],
                    reverse=True,
                )
                archive_groups.append(
                    {
                        "date": group_date,
                        "best": candidates[0],
                        "candidates": candidates,
                    }
                )
            return templates.TemplateResponse(
                request=request,
                name="daily_best.html",
                context={
                    "archive_groups": archive_groups,
                    "query": query_text,
                    "result_count": len(rows),
                    "active": "daily_best",
                },
            )

    # Legacy strategy incubation and quick backtesting are a read-only archive.
    # The stored records stay browsable at /legacy-strategies, but nothing may
    # create or mutate them: QRI stops at a falsifiable research question and
    # does not produce or score tradable strategies.

    return router
