"""Today's radar, the funnel run it came from, and the run controls.

Extracted from app.main so each surface can be read on its own; the route
bodies are unchanged.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.funnel.runner import create_funnel_run
from app.funnel.runner import funnel_stages as build_funnel_stages
from app.models import (
    AICall,
    Claim,
    CommunityObservation,
    KnowledgeDelta,
    Paper,
    PipelineRun,
    PipelineStageRun,
    QuestionTranslation,
    RadarAssessment,
    ResearchCard,
    ResearchQuestion,
    ResearchTheme,
    ResearchValidationSpec,
)
from app.models.entities import FullTextStatus
from app.web.support import (
    LOCAL_ZONE,
    daily_schedule_enabled,
    launch_funnel_process,
    research_merit,
)


def build_router(
    session_factory: Callable[[], Session],
    templates: Jinja2Templates,
) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/papers", status_code=303)

    @router.get("/dashboard")
    def dashboard(request: Request):
        settings = get_settings()
        local_now = datetime.now(LOCAL_ZONE)
        local_today_start = datetime.combine(
            local_now.date(), datetime.min.time(), tzinfo=LOCAL_ZONE
        )
        today_start = local_today_start.astimezone(UTC).replace(tzinfo=None)
        with session_factory() as session:
            stats = {
                "papers": session.scalar(select(func.count()).select_from(Paper)) or 0,
                "papers_today": session.scalar(
                    select(func.count()).select_from(Paper).where(Paper.created_at >= today_start)
                )
                or 0,
                "fulltexts": session.scalar(
                    select(func.count())
                    .select_from(Paper)
                    .where(Paper.fulltext_status == FullTextStatus.FULLTEXT_AVAILABLE)
                )
                or 0,
                "cards": session.scalar(select(func.count()).select_from(ResearchCard)) or 0,
                "claims": session.scalar(select(func.count()).select_from(Claim)) or 0,
                "questions": session.scalar(
                    select(func.count())
                    .select_from(ResearchQuestion)
                    .where(ResearchQuestion.archived_at.is_(None))
                )
                or 0,
            }
            target = settings.daily_scan_target
            recent_runs = list(
                session.scalars(select(PipelineRun).order_by(PipelineRun.id.desc()).limit(10))
            )
            daily_best_rows = list(
                session.execute(
                    select(ResearchQuestion, QuestionTranslation, ResearchValidationSpec)
                    .join(
                        ResearchValidationSpec,
                        ResearchValidationSpec.question_id == ResearchQuestion.id,
                    )
                    .outerjoin(
                        QuestionTranslation,
                        QuestionTranslation.question_id == ResearchQuestion.id,
                    )
                    .where(ResearchQuestion.archived_at.is_(None))
                    .order_by(ResearchQuestion.created_at.desc())
                    .limit(300)
                ).all()
            )
            best_by_day: dict[Any, dict[str, Any]] = {}
            today_research_briefs: list[dict[str, Any]] = []
            for question, translation, validation in daily_best_rows:
                local_date = question.created_at.replace(tzinfo=UTC).astimezone(LOCAL_ZONE).date()
                merit = research_merit(session, question)
                candidate = {
                    "question": question,
                    "translation": translation,
                    "validation": validation,
                    "merit": merit,
                    "score": merit["score"],
                    "date": local_date,
                }
                existing = best_by_day.get(local_date)
                if not existing or candidate["score"] > existing["score"]:
                    best_by_day[local_date] = candidate
                if local_date == local_now.date():
                    today_research_briefs.append(candidate)
            today_research_briefs = sorted(
                today_research_briefs,
                key=lambda item: item["score"],
                reverse=True,
            )[:3]
            daily_best_history = [
                best_by_day[group_date] for group_date in sorted(best_by_day, reverse=True)[:7]
            ]
            daily_best = daily_best_history[0] if daily_best_history else None
            daily_best_is_today = bool(daily_best and daily_best["date"] == local_now.date())
            radar_stats = {
                "scanned": session.scalar(
                    select(func.count())
                    .select_from(RadarAssessment)
                    .where(RadarAssessment.assessed_at >= today_start)
                )
                or 0,
                "evidence": session.scalar(
                    select(func.count())
                    .select_from(RadarAssessment)
                    .where(
                        RadarAssessment.assessed_at >= today_start,
                        RadarAssessment.decision != "ARCHIVED",
                    )
                )
                or 0,
                "new_unique_papers": stats["papers_today"],
                # Count every row that reached Scout, not just the ones still
                # sitting there.  prioritize() rewrites each SCOUT row to DEEP
                # or ARCHIVED_AFTER_SCOUT, so a decision == "SCOUT" filter reads
                # zero for the rest of the day once a funnel run completes.
                "scout": session.scalar(
                    select(func.count())
                    .select_from(RadarAssessment)
                    .where(
                        RadarAssessment.assessed_at >= today_start,
                        RadarAssessment.decision.in_(
                            ("SCOUT", "DEEP", "ARCHIVED_AFTER_SCOUT")
                        ),
                    )
                )
                or 0,
                "changed": session.scalar(
                    select(func.count())
                    .select_from(RadarAssessment)
                    .where(
                        RadarAssessment.assessed_at >= today_start,
                        RadarAssessment.change_type.in_(("CONFLICT", "NEW_GAP")),
                    )
                )
                or 0,
                "conflicts": session.scalar(
                    select(func.count())
                    .select_from(RadarAssessment)
                    .where(
                        RadarAssessment.assessed_at >= today_start,
                        RadarAssessment.change_type == "CONFLICT",
                    )
                )
                or 0,
                "deep": session.scalar(
                    select(func.count())
                    .select_from(RadarAssessment)
                    .where(
                        RadarAssessment.assessed_at >= today_start,
                        RadarAssessment.decision == "DEEP",
                    )
                )
                or 0,
                "themes": session.scalar(select(func.count()).select_from(ResearchTheme)) or 0,
                "knowledge_deltas": session.scalar(
                    select(func.count())
                    .select_from(KnowledgeDelta)
                    .where(
                        KnowledgeDelta.created_at >= today_start,
                        KnowledgeDelta.delta_type != "NO_MATERIAL_CHANGE",
                    )
                )
                or 0,
                "community_observations": session.scalar(
                    select(func.count()).select_from(CommunityObservation)
                )
                or 0,
            }
            knowledge_deltas = list(
                session.execute(
                    select(KnowledgeDelta, ResearchTheme, Paper)
                    .join(ResearchTheme, ResearchTheme.id == KnowledgeDelta.theme_id)
                    .outerjoin(Paper, Paper.id == KnowledgeDelta.paper_id)
                    .where(KnowledgeDelta.delta_type != "NO_MATERIAL_CHANGE")
                    .order_by(KnowledgeDelta.created_at.desc())
                    .limit(12)
                ).all()
            )
            community_attack_count = session.scalar(
                select(func.count()).select_from(CommunityObservation)
            ) or 0
            funnel_run = session.scalar(
                select(PipelineRun)
                .where(PipelineRun.run_type == "DAILY_FUNNEL")
                .order_by(PipelineRun.id.desc())
            )
            stage_rows = {}
            if funnel_run:
                stage_rows = {
                    row.stage: row
                    for row in session.scalars(
                        select(PipelineStageRun)
                        .where(PipelineStageRun.run_id == funnel_run.run_id)
                        .order_by(PipelineStageRun.id)
                    )
                }
            funnel_stages = [
                {"code": code, "label": label, "row": stage_rows.get(code)}
                for code, label, _, _ in build_funnel_stages()
            ]

            def stage_created(stage_code: str) -> int:
                row = stage_rows.get(stage_code)
                return int((row.metrics_json or {}).get("created", 0)) if row else 0

            funnel_live_counts = {
                "papers": max(
                    funnel_run.deduplicated_count if funnel_run else 0,
                    stage_created("DISCOVERY"),
                ),
                "cards": max(
                    funnel_run.research_card_count if funnel_run else 0,
                    stage_created("RESEARCH_CARD"),
                ),
                "questions": max(
                    funnel_run.question_count if funnel_run else 0,
                    stage_created("QUESTIONS"),
                ),
                "ai_calls": (
                    session.scalar(
                        select(func.count())
                        .select_from(AICall)
                        .where(AICall.timestamp >= funnel_run.started_at)
                    )
                    if funnel_run and funnel_run.started_at
                    else 0
                )
                or 0,
            }
            active_stage = (
                stage_rows.get(funnel_run.current_stage or "") if funnel_run else None
            )
            stale_before = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=30)
            funnel_is_stale = bool(
                funnel_run
                and funnel_run.status == "RUNNING"
                and active_stage
                and active_stage.status == "RUNNING"
                and active_stage.started_at
                and active_stage.started_at < stale_before
            )
            funnel_can_resume = bool(
                funnel_run and (funnel_run.status == "FAILED" or funnel_is_stale)
            )
            funnel_started_local_date = (
                funnel_run.started_at.replace(tzinfo=UTC).astimezone(LOCAL_ZONE).date()
                if funnel_run and funnel_run.started_at
                else None
            )
            funnel_is_today = funnel_started_local_date == local_now.date()
            schedule_enabled = daily_schedule_enabled()
            next_schedule_at = datetime.combine(
                local_now.date(), datetime.min.time().replace(hour=8), tzinfo=LOCAL_ZONE
            )
            if next_schedule_at <= local_now:
                next_schedule_at += timedelta(days=1)
            schedule_next_label = (
                "今天 08:00"
                if next_schedule_at.date() == local_now.date()
                else "明天 08:00"
                if next_schedule_at.date() == local_now.date() + timedelta(days=1)
                else f"{next_schedule_at.month}月{next_schedule_at.day}日 08:00"
            )
            if funnel_is_today and funnel_run and funnel_run.status == "RUNNING":
                daily_task_state = "running"
                daily_task_state_label = "今日运行中"
            elif funnel_is_today and funnel_run and funnel_run.status == "COMPLETE":
                daily_task_state = "complete"
                daily_task_state_label = "今日已完成"
            elif local_now.hour >= 8:
                daily_task_state = "missed"
                daily_task_state_label = "今日未运行"
            else:
                daily_task_state = "waiting"
                daily_task_state_label = "等待 08:00"
            return templates.TemplateResponse(
                request=request,
                name="dashboard.html",
                context={
                    "stats": stats,
                    "daily_target": target,
                    "daily_progress": min(100, round(stats["papers_today"] / target * 100)),
                    "schedule_enabled": schedule_enabled,
                    "schedule_next_label": schedule_next_label,
                    "daily_task_state": daily_task_state,
                    "daily_task_state_label": daily_task_state_label,
                    "dashboard_updated_at": local_now,
                    "recent_runs": recent_runs,
                    "daily_best": daily_best,
                    "daily_best_is_today": daily_best_is_today,
                    "daily_best_history": daily_best_history,
                    "today_research_briefs": today_research_briefs,
                    "radar_stats": radar_stats,
                    "knowledge_deltas": knowledge_deltas,
                    "community_attack_count": community_attack_count,
                    "funnel_run": funnel_run,
                    "funnel_stages": funnel_stages,
                    "funnel_live_counts": funnel_live_counts,
                    "funnel_is_stale": funnel_is_stale,
                    "funnel_can_resume": funnel_can_resume,
                    "funnel_is_today": funnel_is_today,
                    "funnel_started_local_date": funnel_started_local_date,
                    "funnel_message": request.query_params.get("funnel"),
                    "daily_model": settings.primary_model,
                    "question_model": settings.reasoning_model,
                    "validation_model": settings.validation_model,
                    "active": "dashboard",
                },
            )

    @router.post("/funnel/run")
    def run_funnel() -> RedirectResponse:
        run, created = create_funnel_run(session_factory)
        if created:
            launch_funnel_process(run.run_id)
            state = "started"
        else:
            state = "running"
        return RedirectResponse(f"/dashboard?funnel={state}#task-center", status_code=303)

    @router.post("/funnel/resume")
    def resume_funnel_route() -> RedirectResponse:
        with session_factory() as session:
            run = session.scalar(
                select(PipelineRun)
                .where(
                    PipelineRun.run_type == "DAILY_FUNNEL",
                    PipelineRun.status.in_(("RUNNING", "FAILED")),
                )
                .order_by(PipelineRun.id.desc())
            )
            if not run:
                raise HTTPException(status_code=404, detail="没有可继续的任务")
            run_id = run.run_id
        launch_funnel_process(run_id)
        return RedirectResponse("/dashboard?funnel=resumed#task-center", status_code=303)

    return router
