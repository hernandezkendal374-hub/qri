from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AbstractBrief,
    AICall,
    Claim,
    Paper,
    PipelineRun,
    PipelineStageRun,
    RadarAssessment,
    ResearchCard,
    ResearchQuestion,
    ResearchValidationSpec,
)
from app.models.entities import FullTextStatus

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FUNNEL_STAGES = (
    ("DISCOVERY", "雷达采集并去重 300 项", ("daily", "--target", "300"), Paper),
    ("RADAR", "元数据与摘要快速淘汰", ("radar", "--scout", "20"), RadarAssessment),
    ("SCOUT", "侦察解读 Top 20", ("briefs", "--top", "20"), AbstractBrief),
    ("DEEP_SELECTION", "增量判断并选出 Top 1–3", ("prioritize", "--deep", "3"), RadarAssessment),
    ("FULLTEXT", "仅获取深研对象合法全文", ("fetch", "--top", "3"), Paper),
    ("RESEARCH_CARD", "深度研究与证据卡", ("analyze", "--top", "3"), ResearchCard),
    ("CLAIM_EVIDENCE", "提取 Claim 与 Evidence", ("claims", "--top", "3"), Claim),
    ("QUESTIONS", "只生成高价值候选问题", ("questions",), ResearchQuestion),
    (
        "RESEARCH_BRIEF",
        "自动完成 Research Brief",
        ("validation-briefs", "--top", "3"),
        ResearchValidationSpec,
    ),
)


def create_funnel_run(session_factory: Callable[[], Session]) -> tuple[PipelineRun, bool]:
    with session_factory() as session:
        running = session.scalar(
            select(PipelineRun)
            .where(PipelineRun.run_type == "DAILY_FUNNEL", PipelineRun.status == "RUNNING")
            .order_by(PipelineRun.id.desc())
        )
        if running:
            return running, False
        run = PipelineRun(
            query="[THREE_SPEED] 300 → radar → 20 scout → 1-3 deep → brief",
            run_type="DAILY_FUNNEL",
            status="RUNNING",
            current_stage="PENDING",
        )
        session.add(run)
        session.flush()
        session.add_all(
            PipelineStageRun(run_id=run.run_id, stage=code, status="PENDING")
            for code, _, _, _ in FUNNEL_STAGES
        )
        session.commit()
        return run, True


def execute_funnel(
    run_id: str,
    session_factory: Callable[[], Session],
    python_executable: str | None = None,
    project_root: Path = PROJECT_ROOT,
) -> None:
    python_executable = python_executable or sys.executable
    failures = 0
    for code, _, arguments, model in FUNNEL_STAGES:
        if _stage_status(session_factory, run_id, code) == "SUCCESS":
            continue
        stage_start_count = _model_count(session_factory, model, code)
        _mark_stage_started(session_factory, run_id, code)
        try:
            result = subprocess.run(
                [python_executable, "-m", "app.cli", *arguments],
                cwd=project_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=7200,
                check=False,
            )
            output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part)
            created = max(0, _model_count(session_factory, model, code) - stage_start_count)
            if result.returncode == 0:
                _mark_stage_finished(session_factory, run_id, code, "SUCCESS", created, output)
            else:
                failures += 1
                _mark_stage_finished(
                    session_factory, run_id, code, "FAILED", created, output, result.returncode
                )
        except Exception as exc:
            failures += 1
            _mark_stage_finished(
                session_factory, run_id, code, "FAILED", 0, f"{type(exc).__name__}: {exc}"
            )
    with session_factory() as session:
        run = session.scalar(select(PipelineRun).where(PipelineRun.run_id == run_id))
        if not run:
            return
        run.status = "COMPLETE" if failures == 0 else "FAILED"
        run.current_stage = None
        run.ended_at = datetime.now(UTC).replace(tzinfo=None)
        stage_rows = {
            stage.stage: stage
            for stage in session.scalars(
                select(PipelineStageRun).where(PipelineStageRun.run_id == run_id)
            )
        }

        def created(stage: str) -> int:
            row = stage_rows.get(stage)
            return int((row.metrics_json or {}).get("created", 0)) if row else 0

        run.discovered_count = created("DISCOVERY")
        run.deduplicated_count = created("DISCOVERY")
        run.fulltext_success_count = created("FULLTEXT")
        run.research_card_count = created("RESEARCH_CARD")
        run.claim_count = created("CLAIM_EVIDENCE")
        run.question_count = created("QUESTIONS")
        run.ai_call_count = (
            session.scalar(
                select(func.count()).select_from(AICall).where(AICall.timestamp >= run.started_at)
            )
            or 0
        )
        run.error_count = failures
        session.commit()


def _stage_status(session_factory: Callable[[], Session], run_id: str, code: str) -> str | None:
    with session_factory() as session:
        return session.scalar(
            select(PipelineStageRun.status).where(
                PipelineStageRun.run_id == run_id,
                PipelineStageRun.stage == code,
            )
        )


def _snapshot(session_factory: Callable[[], Session]) -> dict[str, int]:
    with session_factory() as session:
        return {
            "papers": session.scalar(select(func.count()).select_from(Paper)) or 0,
            "fulltexts": session.scalar(
                select(func.count())
                .select_from(Paper)
                .where(Paper.fulltext_status == FullTextStatus.FULLTEXT_AVAILABLE)
            )
            or 0,
            "cards": session.scalar(select(func.count()).select_from(ResearchCard)) or 0,
            "claims": session.scalar(select(func.count()).select_from(Claim)) or 0,
            "questions": session.scalar(select(func.count()).select_from(ResearchQuestion)) or 0,
            "ai_calls": session.scalar(select(func.count()).select_from(AICall)) or 0,
        }


def _model_count(session_factory: Callable[[], Session], model, stage: str) -> int:
    with session_factory() as session:
        statement = select(func.count()).select_from(model)
        if stage == "FULLTEXT":
            statement = statement.where(Paper.fulltext_status == FullTextStatus.FULLTEXT_AVAILABLE)
        return session.scalar(statement) or 0


def _mark_stage_started(session_factory: Callable[[], Session], run_id: str, code: str) -> None:
    with session_factory() as session:
        run = session.scalar(select(PipelineRun).where(PipelineRun.run_id == run_id))
        stage = session.scalar(
            select(PipelineStageRun).where(
                PipelineStageRun.run_id == run_id, PipelineStageRun.stage == code
            )
        )
        if run:
            run.current_stage = code
        if stage:
            stage.status = "RUNNING"
            stage.attempt_count += 1
            stage.started_at = datetime.now(UTC).replace(tzinfo=None)
            stage.ended_at = None
            stage.error_json = None
        session.commit()


def _mark_stage_finished(
    session_factory: Callable[[], Session],
    run_id: str,
    code: str,
    status: str,
    created: int,
    output: str,
    return_code: int | None = None,
) -> None:
    with session_factory() as session:
        run = session.scalar(select(PipelineRun).where(PipelineRun.run_id == run_id))
        stage = session.scalar(
            select(PipelineStageRun).where(
                PipelineStageRun.run_id == run_id, PipelineStageRun.stage == code
            )
        )
        if not stage:
            return
        stage.status = status
        stage.ended_at = datetime.now(UTC).replace(tzinfo=None)
        stage.metrics_json = {"created": created}
        stage.checkpoint_json = {"output": output[-2000:]}
        if status == "FAILED":
            stage.error_json = {"return_code": return_code, "message": output[-1000:]}
        else:
            stage.error_json = None
        if run:
            count_fields = {
                "DISCOVERY": ("discovered_count", "deduplicated_count"),
                "FULLTEXT": ("fulltext_success_count",),
                "RESEARCH_CARD": ("research_card_count",),
                "CLAIM_EVIDENCE": ("claim_count",),
                "QUESTIONS": ("question_count",),
            }
            for field_name in count_fields.get(code, ()):
                setattr(run, field_name, created)
            run.ai_call_count = (
                session.scalar(
                    select(func.count())
                    .select_from(AICall)
                    .where(AICall.timestamp >= run.started_at)
                )
                or 0
            )
        session.commit()
