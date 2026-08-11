import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.evidence.verification import field_verification_status
from app.extraction.abstract_brief import AbstractBriefExtractor
from app.fulltext.downloader import InvalidFullTextError, PDFDownloader
from app.fulltext.service import FullTextService
from app.funnel.runner import FUNNEL_STAGES, create_funnel_run
from app.models import (
    AbstractBrief,
    AICall,
    Claim,
    Document,
    Evidence,
    Paper,
    PipelineRun,
    PipelineStageRun,
    QuestionStatus,
    QuestionTranslation,
    RadarAssessment,
    ResearchCard,
    ResearchQuestion,
    ResearchTheme,
    ResearchValidationSpec,
    StrategyIncubation,
)
from app.models.entities import FullTextStatus
from app.parsing.pymupdf_parser import PyMuPDFParser
from app.providers.llm.openai_compatible import OpenAICompatibleProvider
from app.providers.papers.openalex import OpenAlexProvider
from app.providers.papers.unpaywall import UnpaywallProvider
from app.research_validation import ResearchValidationService
from app.schemas.research import PaperResearchCard
from app.scope.us_equity import SCOPE_VERSION
from app.strategy.quick_backtest import (
    DEFAULT_UNIVERSE,
    evaluate_quick_result,
    infer_strategy_profile,
    run_quick_backtest,
)
from app.strategy.service import StrategyIncubationService

APP_DIR = Path(__file__).resolve().parent


def _launch_funnel_process(run_id: str) -> None:
    """Run the funnel outside the web-server process so restarts do not kill it."""
    creation_flags = 0
    startup_info = None
    executable = sys.executable
    if sys.platform == "win32":
        # pythonw plus an explicit hidden startup state avoids Windows Terminal
        # appearing when a funnel is launched from the web UI.
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if pythonw.exists():
            executable = str(pythonw)
        creation_flags = subprocess.CREATE_NO_WINDOW
        startup_info = subprocess.STARTUPINFO()
        startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup_info.wShowWindow = subprocess.SW_HIDE
    subprocess.Popen(
        [executable, "-m", "app.cli", "resume-funnel", "--run-id", run_id],
        cwd=APP_DIR.parent,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
        startupinfo=startup_info,
        start_new_session=sys.platform != "win32",
    )


def _strategy_profile(question: ResearchQuestion, incubation: StrategyIncubation) -> str | None:
    specification = incubation.specification_json or {}
    direct = specification.get("executable_strategy") or {}
    profile_text = " ".join(
        str(value)
        for value in (
            question.question,
            direct.get("strategy_name", ""),
            direct.get("strategy_type", ""),
            direct.get("one_sentence_rule", ""),
            direct.get("signal_formula", ""),
        )
    )
    return infer_strategy_profile(profile_text)


def _mark_backtest_unavailable(incubation: StrategyIncubation) -> None:
    specification = dict(incubation.specification_json or {})
    specification.pop("quick_backtest", None)
    specification["quick_backtest_unavailable"] = {
        "status": "UNSUPPORTED_PROFILE",
        "title": "暂无匹配的快速回测模型",
        "reason": (
            "当前快速引擎只支持纯价格动量和纯价格低波动；"
            "本策略依赖额外条件或数据，不能用通用代理结果代替。"
        ),
        "supported_profiles": ["纯价格动量", "纯价格低波动"],
    }
    incubation.specification_json = specification


def _backtest_is_ranking_eligible(backtest: dict[str, Any] | None) -> bool:
    if not backtest:
        return False
    coverage = backtest.get("coverage") or {}
    return bool(coverage.get("eligible_for_ranking", False))


def _research_merit(session: Session, question: ResearchQuestion) -> dict[str, float]:
    supporting = list(question.supporting_claims_json or [])
    contradicting = list(question.contradicting_claims_json or [])
    claim_ids = list(dict.fromkeys(supporting + contradicting))
    confidences = (
        list(
            session.scalars(
                select(Evidence.confidence).where(
                    Evidence.claim_id.in_(claim_ids),
                    Evidence.confidence.is_not(None),
                )
            )
        )
        if claim_ids
        else []
    )
    evidence_quality = sum(confidences) / len(confidences) if confidences else 0.35
    conflict = min(1.0, len(contradicting) / max(1, len(supporting)))
    falsifiability = min(
        1.0,
        0.35
        + (0.30 if (question.counter_mechanism or "").strip() else 0.0)
        + (0.20 if question.known_risks_json else 0.0)
        + (0.15 if contradicting else 0.0),
    )
    metrics = {
        "novelty": question.novelty_score or 0.0,
        "evidence_quality": evidence_quality,
        "evidence_conflict": conflict,
        "falsifiability": falsifiability,
        "testability": question.testability_score or 0.0,
        "data_availability": question.data_availability_score or 0.0,
    }
    metrics["score"] = (
        0.15 * metrics["novelty"]
        + 0.20 * metrics["evidence_quality"]
        + 0.15 * metrics["evidence_conflict"]
        + 0.20 * metrics["falsifiability"]
        + 0.20 * metrics["testability"]
        + 0.10 * metrics["data_availability"]
    )
    return metrics


CARD_STORAGE_FIELDS = {
    "robustness_tests": "robustness_tests_json",
    "required_data": "required_data_json",
    "limitations": "limitations_json",
}
RESEARCH_FIELD_LABELS = {
    "market": "市场",
    "asset_class": "资产类别",
    "universe": "研究标的范围",
    "sample_start": "样本开始时间",
    "sample_end": "样本结束时间",
    "hypothesis": "研究假设",
    "mechanism": "经济机制",
    "counter_mechanism": "反向机制",
    "signal_definition": "信号定义",
    "formation_period": "形成期",
    "holding_period": "持有期",
    "rebalance_frequency": "调仓频率",
    "portfolio_construction": "投资组合构建",
    "benchmark": "基准",
    "reported_return": "报告收益率",
    "reported_alpha": "报告超额收益（Alpha）",
    "reported_sharpe": "报告夏普比率",
    "reported_max_drawdown": "报告最大回撤",
    "transaction_cost_handling": "交易成本处理",
    "survivorship_handling": "幸存者偏差处理",
    "lookahead_handling": "前视偏差处理",
    "in_sample": "样本内结果",
    "out_of_sample": "样本外结果",
    "robustness_tests": "稳健性检验",
    "required_data": "所需数据",
    "limitations": "研究局限",
}
FULLTEXT_STATUS_LABELS = {
    "UNKNOWN": "尚未检查",
    "ABSTRACT_ONLY": "仅有摘要",
    "FULLTEXT_AVAILABLE": "全文可用",
    "FULLTEXT_UNAVAILABLE": "获取失败",
}
QUESTION_STATUS_LABELS = {
    "DISCOVERED": "新发现",
    "AI_REVIEWED": "AI 已审核",
    "HUMAN_REVIEW_REQUIRED": "等待人工审核",
    "HUMAN_APPROVED": "人工已通过",
    "DEFERRED": "暂缓研究",
    "REJECTED": "已拒绝",
    "EXPORTED": "已导出",
}
VERIFICATION_STATUS_LABELS = {
    "VERIFIED": "已验证",
    "UNVERIFIED": "未验证",
    "PARTIAL": "部分验证",
}
CLAIM_TYPE_LABELS = {
    "AUTHOR_CLAIM": "作者主张",
}
RESEARCH_SCOPE_LABELS = {
    "UNCLASSIFIED": "尚未分类",
    "US_EQUITY_CORE": "美股核心",
    "US_EQUITY_AUXILIARY": "美股辅助信号",
    "OUT_OF_SCOPE": "范围外归档",
    "MANUAL_REVIEW": "等待人工判断",
}


def _localized_label(value: Any, labels: dict[str, str]) -> str:
    raw_value = getattr(value, "value", value)
    return labels.get(str(raw_value), str(raw_value).replace("_", " ").title())


LOCAL_ZONE = ZoneInfo("Asia/Shanghai")
DAILY_TASK_NAME = "QRI Daily Research Funnel"


def _local_datetime(value: datetime | None, format_string: str = "%Y-%m-%d %H:%M") -> str:
    """Render the naive UTC timestamps stored by QRI in China local time."""
    if value is None:
        return "—"
    aware_value = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware_value.astimezone(LOCAL_ZONE).strftime(format_string)


def _local_datetime_zh(value: datetime | None) -> str:
    if value is None:
        return "—"
    aware_value = value if value.tzinfo else value.replace(tzinfo=UTC)
    local_value = aware_value.astimezone(LOCAL_ZONE)
    return f"{local_value.month}月{local_value.day}日 {local_value:%H:%M}"


def _daily_schedule_enabled() -> bool:
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", DAILY_TASK_NAME],
            capture_output=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _fulltext_reason_zh(reason: str | None) -> str:
    if not reason:
        return "历史获取没有成功，但旧记录未保存具体原因；可以重新查找。"
    lowered = reason.casefold()
    if "no legal open-access pdf location" in lowered:
        return "没有找到合法开放的 PDF 地址。"
    if "403" in lowered or "401" in lowered:
        return "出版商拒绝自动下载，可能需要订阅或登录。"
    if "response is not a pdf" in lowered or "not a pdf" in lowered:
        return "候选地址返回的是网页而不是 PDF，通常是付费墙或验证页面。"
    if "404" in lowered:
        return "候选 PDF 地址已经失效。"
    if "timeout" in lowered:
        return "全文服务器响应超时，可以稍后重试。"
    if "unpaywall lookup" in lowered or "openalex lookup" in lowered:
        return "开放全文来源查询失败，可以稍后重试。"
    return "自动获取没有成功；可以重新查找或上传你合法持有的 PDF。"


def create_app(session_factory: Callable[[], Session] = SessionLocal) -> FastAPI:
    web = FastAPI(title="QRI", version="0.1.0")
    templates = Jinja2Templates(directory=APP_DIR / "templates")
    templates.env.filters["fulltext_status_zh"] = lambda value: _localized_label(
        value, FULLTEXT_STATUS_LABELS
    )
    templates.env.filters["fulltext_reason_zh"] = _fulltext_reason_zh
    templates.env.filters["question_status_zh"] = lambda value: _localized_label(
        value, QUESTION_STATUS_LABELS
    )
    templates.env.filters["verification_status_zh"] = lambda value: _localized_label(
        value, VERIFICATION_STATUS_LABELS
    )
    templates.env.filters["claim_type_zh"] = lambda value: _localized_label(
        value, CLAIM_TYPE_LABELS
    )
    templates.env.filters["research_scope_zh"] = lambda value: _localized_label(
        value, RESEARCH_SCOPE_LABELS
    )
    templates.env.filters["local_datetime"] = _local_datetime
    templates.env.filters["local_datetime_zh"] = _local_datetime_zh
    web.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

    @web.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @web.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/papers", status_code=303)

    @web.get("/dashboard")
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
            target = 300
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
                merit = _research_merit(session, question)
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
            }
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
                for code, label, _, _ in FUNNEL_STAGES
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
            active_stage = stage_rows.get(funnel_run.current_stage) if funnel_run else None
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
            schedule_enabled = _daily_schedule_enabled()
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

    @web.post("/funnel/run")
    def run_funnel() -> RedirectResponse:
        run, created = create_funnel_run(session_factory)
        if created:
            _launch_funnel_process(run.run_id)
            state = "started"
        else:
            state = "running"
        return RedirectResponse(f"/dashboard?funnel={state}#task-center", status_code=303)

    @web.post("/funnel/resume")
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
        _launch_funnel_process(run_id)
        return RedirectResponse("/dashboard?funnel=resumed#task-center", status_code=303)

    @web.get("/papers")
    def papers(request: Request, scope: str = ""):
        with session_factory() as session:
            statement = select(Paper).order_by(Paper.id.desc()).limit(100)
            if scope in RESEARCH_SCOPE_LABELS:
                statement = statement.where(Paper.research_scope == scope)
            rows = list(session.scalars(statement))
            scope_counts = dict(
                session.execute(
                    select(Paper.research_scope, func.count()).group_by(Paper.research_scope)
                ).all()
            )
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
            brief = session.scalar(select(AbstractBrief).where(AbstractBrief.paper_id == paper_id))
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

    @web.post("/papers/{paper_id}/scope/{scope_code}")
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

    @web.post("/papers/{paper_id}/fulltext/retry")
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

    @web.post("/papers/{paper_id}/fulltext/upload")
    async def upload_fulltext(request: Request, paper_id: int) -> JSONResponse:
        max_bytes = 50 * 1024 * 1024
        length = request.headers.get("content-length")
        if length and int(length) > max_bytes:
            raise HTTPException(status_code=413, detail="PDF 不能超过 50 MB")
        content = await request.body()
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
                result = service.ingest_uploaded_pdf(paper, content)
            except (InvalidFullTextError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(
            {"status": "ok", "pages": result.page_count, "characters": result.character_count}
        )

    @web.post("/papers/{paper_id}/abstract-brief")
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
                question.id: _handoff_package(session, question, translation)
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

    @web.get("/strategies")
    def strategies_redirect() -> RedirectResponse:
        return RedirectResponse("/legacy-strategies", status_code=303)

    @web.get("/legacy-strategies")
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

    @web.get("/daily-best")
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
                merit = _research_merit(session, question)
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

    @web.get("/strategies/{question_id}/backtest")
    def quick_backtest_page(request: Request, question_id: int, ticker: str = "AAPL"):
        return RedirectResponse("/legacy-strategies", status_code=303)
        ticker = ticker.upper()
        with session_factory() as session:
            question = session.get(ResearchQuestion, question_id)
            incubation = session.scalar(
                select(StrategyIncubation).where(StrategyIncubation.question_id == question_id)
            )
            if not question or not incubation:
                raise HTTPException(status_code=404, detail="策略不存在")
            result = incubation.specification_json.get("quick_backtest")
            universe = result.get("universe", DEFAULT_UNIVERSE) if result else DEFAULT_UNIVERSE
            if ticker not in universe:
                ticker = universe[0]
            return templates.TemplateResponse(
                request=request,
                name="backtest.html",
                context={
                    "question": question,
                    "incubation": incubation,
                    "result": result,
                    "evaluation": evaluate_quick_result(result) if result else None,
                    "ticker": ticker,
                    "universe": universe,
                    "active": "",
                },
            )

    @web.post("/strategies/{question_id}/backtest/run")
    async def run_quick_backtest_route(question_id: int):
        raise HTTPException(status_code=410, detail="快速回测已移出 QRI 主流程")
        with session_factory() as session:
            question = session.get(ResearchQuestion, question_id)
            incubation = session.scalar(
                select(StrategyIncubation).where(StrategyIncubation.question_id == question_id)
            )
            if not question or not incubation:
                raise HTTPException(status_code=404, detail="策略不存在")
            profile = _strategy_profile(question, incubation)
            if profile is None:
                _mark_backtest_unavailable(incubation)
                session.commit()
                return RedirectResponse(f"/questions#question-{question_id}", status_code=303)
        try:
            result = await run_quick_backtest(profile)
        except Exception as exc:
            raise HTTPException(status_code=502, detail="公开行情暂时不可用，请稍后重试") from exc
        with session_factory() as session:
            incubation = session.scalar(
                select(StrategyIncubation).where(StrategyIncubation.question_id == question_id)
            )
            if not incubation:
                raise HTTPException(status_code=404, detail="策略不存在")
            specification = dict(incubation.specification_json)
            specification["quick_backtest"] = result
            specification.pop("quick_backtest_unavailable", None)
            incubation.specification_json = specification
            session.commit()
        return RedirectResponse(f"/strategies/{question_id}/backtest", status_code=303)

    @web.post("/questions/{question_id}/advance")
    async def advance_question_to_backtest(question_id: int):
        raise HTTPException(status_code=410, detail="请改用研究验证方案")
        settings = get_settings()
        with session_factory() as session:
            question = session.get(ResearchQuestion, question_id)
            if not question:
                raise HTTPException(status_code=404, detail="研究问题不存在")
            incubation = session.scalar(
                select(StrategyIncubation).where(StrategyIncubation.question_id == question_id)
            )
            if not incubation:
                if not settings.llm_base_url or not settings.llm_api_key:
                    raise HTTPException(status_code=503, detail="AI 模型尚未配置")
                translation = session.scalar(
                    select(QuestionTranslation).where(
                        QuestionTranslation.question_id == question_id
                    )
                )
                handoff = _handoff_package(session, question, translation)
                provider = OpenAICompatibleProvider(
                    settings.llm_base_url,
                    settings.llm_api_key.get_secret_value(),
                    timeout=max(settings.http_timeout_seconds, 600.0),
                )
                try:
                    incubation = await StrategyIncubationService(
                        session, provider, settings.strategy_model
                    ).generate(question, handoff)
                except Exception as exc:
                    raise HTTPException(status_code=502, detail="直接策略生成失败") from exc
            profile = _strategy_profile(question, incubation)
            if profile is None:
                _mark_backtest_unavailable(incubation)
                session.commit()
                return RedirectResponse(f"/questions#question-{question_id}", status_code=303)
        try:
            result = await run_quick_backtest(profile)
        except Exception as exc:
            raise HTTPException(status_code=502, detail="公开行情暂时不可用，请稍后重试") from exc
        with session_factory() as session:
            incubation = session.scalar(
                select(StrategyIncubation).where(StrategyIncubation.question_id == question_id)
            )
            if not incubation:
                raise HTTPException(status_code=404, detail="策略不存在")
            specification = dict(incubation.specification_json)
            specification["quick_backtest"] = result
            specification.pop("quick_backtest_unavailable", None)
            incubation.specification_json = specification
            session.commit()
        return RedirectResponse(f"/strategies/{question_id}/backtest", status_code=303)

    @web.post("/strategies/{question_id}/reconstruct")
    async def reconstruct_strategy(question_id: int):
        raise HTTPException(status_code=410, detail="策略重构已移出 QRI")
        with session_factory() as session:
            question = session.get(ResearchQuestion, question_id)
            incubation = session.scalar(
                select(StrategyIncubation).where(StrategyIncubation.question_id == question_id)
            )
            if not question or not incubation:
                raise HTTPException(status_code=404, detail="策略不存在")
            previous = incubation.specification_json.get("quick_backtest")
            if not previous:
                raise HTTPException(status_code=409, detail="请先完成首次快速回测")
            base_profile = _strategy_profile(question, incubation)
            if base_profile is None:
                _mark_backtest_unavailable(incubation)
                session.commit()
                return RedirectResponse(f"/questions#question-{question_id}", status_code=303)
            profile = f"{base_profile}_v2"
        try:
            result = await run_quick_backtest(profile)
        except Exception as exc:
            raise HTTPException(status_code=502, detail="重构回测失败，请稍后重试") from exc
        result["reconstruction"] = {
            "version": 2,
            "previous_metrics": previous["metrics"],
            "previous_profile": previous.get("profile", base_profile),
            "changes": [
                "每侧持仓由2只增加至3只，降低单股集中度",
                "总多空敞口由100%降至80%",
                "信号窗口改为更灵敏且更分散的第二版参数",
                "保留原成本和借券假设，保证前后可比",
            ],
        }
        with session_factory() as session:
            incubation = session.scalar(
                select(StrategyIncubation).where(StrategyIncubation.question_id == question_id)
            )
            if not incubation:
                raise HTTPException(status_code=404, detail="策略不存在")
            specification = dict(incubation.specification_json)
            history = list(specification.get("quick_backtest_history", []))
            history.append(previous)
            specification["quick_backtest_history"] = history[-5:]
            specification["quick_backtest"] = result
            incubation.specification_json = specification
            session.commit()
        return RedirectResponse(f"/strategies/{question_id}/backtest", status_code=303)

    @web.post("/questions/{question_id}/archive")
    def archive_question(question_id: int):
        with session_factory() as session:
            question = session.get(ResearchQuestion, question_id)
            if not question:
                raise HTTPException(status_code=404, detail="研究问题不存在")
            question.archived_at = datetime.now(UTC).replace(tzinfo=None)
            session.commit()
        return RedirectResponse("/questions#archived-questions", status_code=303)

    @web.post("/questions/{question_id}/restore")
    def restore_question(question_id: int):
        with session_factory() as session:
            question = session.get(ResearchQuestion, question_id)
            if not question:
                raise HTTPException(status_code=404, detail="研究问题不存在")
            question.archived_at = None
            session.commit()
        return RedirectResponse(f"/questions#question-{question_id}", status_code=303)

    @web.get("/questions/{question_id}/handoff.json")
    def question_handoff(question_id: int):
        with session_factory() as session:
            question = session.get(ResearchQuestion, question_id)
            if not question:
                raise HTTPException(status_code=404, detail="研究问题不存在")
            translation = session.scalar(
                select(QuestionTranslation).where(QuestionTranslation.question_id == question_id)
            )
            package = _handoff_package(session, question, translation)
        return JSONResponse(
            package,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{question.question_uid}-handoff.json"'
                )
            },
        )

    @web.post("/questions/{question_id}/validation-spec")
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
            evidence_package = _handoff_package(session, question, translation)
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

    @web.post("/questions/{question_id}/approve")
    def approve_validation_spec(question_id: int):
        return decide_research_brief(question_id, "approve")

    @web.post("/questions/{question_id}/decision/{decision}")
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

    @web.get("/questions/{question_id}/validation-spec.json")
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
            package = _validation_export_package(session, question, spec)
            session.commit()
        return JSONResponse(
            package,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{question.question_uid}-validation-spec.json"'
                )
            },
        )

    @web.post("/questions/{question_id}/incubate")
    async def incubate_question(question_id: int):
        raise HTTPException(status_code=410, detail="策略孵化已移出 QRI")
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
            handoff = _handoff_package(session, question, translation)
            provider = OpenAICompatibleProvider(
                settings.llm_base_url,
                settings.llm_api_key.get_secret_value(),
                timeout=max(settings.http_timeout_seconds, 600.0),
            )
            try:
                await StrategyIncubationService(
                    session, provider, settings.strategy_model
                ).generate(question, handoff)
            except Exception as exc:
                raise HTTPException(status_code=502, detail="策略孵化方案生成失败") from exc
        return RedirectResponse(f"/questions#strategy-incubation-{question_id}", status_code=303)

    @web.get("/questions/{question_id}/strategy-spec.json")
    def strategy_spec(question_id: int):
        with session_factory() as session:
            question = session.get(ResearchQuestion, question_id)
            incubation = session.scalar(
                select(StrategyIncubation).where(StrategyIncubation.question_id == question_id)
            )
            if not question or not incubation:
                raise HTTPException(status_code=404, detail="策略孵化方案不存在")
            package = _strategy_export_package(question, incubation)
        return JSONResponse(
            package,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{question.question_uid}-strategy-spec.json"'
                )
            },
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
                "label": RESEARCH_FIELD_LABELS.get(field_name, field_name),
                "value": value,
                "status": field_verification_status(session, card, field_name),
            }
        )
    return fields


def _handoff_package(
    session: Session,
    question: ResearchQuestion,
    translation: QuestionTranslation | None,
) -> dict[str, Any]:
    supporting_ids = list(question.supporting_claims_json or [])
    contradicting_ids = list(question.contradicting_claims_json or [])
    claim_ids = list(dict.fromkeys(supporting_ids + contradicting_ids))
    claim_rows = (
        list(
            session.execute(
                select(Claim, Paper)
                .join(Paper, Paper.id == Claim.paper_id)
                .where(Claim.id.in_(claim_ids))
                .order_by(Claim.id)
            ).all()
        )
        if claim_ids
        else []
    )
    evidence_rows = (
        list(
            session.scalars(
                select(Evidence)
                .where(Evidence.claim_id.in_(claim_ids))
                .order_by(Evidence.claim_id, Evidence.id)
            )
        )
        if claim_ids
        else []
    )
    evidence_by_claim: dict[int, list[Evidence]] = {}
    for pointer in evidence_rows:
        if pointer.claim_id:
            evidence_by_claim.setdefault(pointer.claim_id, []).append(pointer)
    literature = []
    for claim, paper in claim_rows:
        literature.append(
            {
                "claim_id": claim.id,
                "role": "supporting" if claim.id in supporting_ids else "contradicting",
                "paper": {
                    "paper_id": paper.id,
                    "title": paper.title,
                    "doi": paper.doi,
                    "arxiv_id": paper.arxiv_id,
                    "source_url": paper.source_url,
                },
                "author_claim": claim.claim_text,
                "direction": claim.direction,
                "evidence": [
                    {
                        "evidence_id": pointer.id,
                        "page": pointer.page_number,
                        "section": pointer.section,
                        "source_text": pointer.source_text,
                        "confidence": pointer.confidence,
                    }
                    for pointer in evidence_by_claim.get(claim.id, [])
                ],
            }
        )
    return {
        "package_type": "QRI_CANDIDATE_QUESTION_EVIDENCE",
        "version": "2.0",
        "evidence_policy": (
            "AUTHOR_CLAIM is not a system fact. Evidence pointers verify only that "
            "the quote exists in the locally parsed paper."
        ),
        "question": {
            "id": question.id,
            "uid": question.question_uid,
            "family": question.family,
            "plain_language_question": (question.plain_language_question or question.question),
            "academic_question": question.academic_question or question.question,
            "question_zh": translation.question_zh if translation else question.question,
            "question_original": question.question,
            "economic_mechanism_zh": (
                translation.economic_mechanism_zh if translation else question.economic_mechanism
            ),
            "counter_mechanism_zh": (
                translation.counter_mechanism_zh if translation else question.counter_mechanism
            ),
            "required_data_zh": (
                translation.required_data_zh_json if translation else question.required_data_json
            ),
            "known_risks_zh": (
                translation.known_risks_zh_json if translation else question.known_risks_json
            ),
            "scores": {
                "novelty": question.novelty_score,
                "testability": question.testability_score,
                "data_availability": question.data_availability_score,
                "research_priority": question.research_priority_score,
            },
        },
        "literature_evidence": literature,
        "required_output": [
            "Plain-language and academic versions of the same research question",
            "Falsification conditions",
            "Point-in-time data specification",
            "Statistical design and robustness tests",
            "Failure criteria and human-review checkpoints",
        ],
        "prohibited_actions": [
            "Do not treat author claims as established facts",
            "Do not generate portfolio weights, positions, exposure, or execution rules",
            "Do not present statistical tests as a tradable strategy",
            "Do not run or report a strategy backtest inside QRI",
        ],
    }


def _strategy_export_package(
    question: ResearchQuestion, incubation: StrategyIncubation
) -> dict[str, Any]:
    return {
        "package_type": "QRI_EXECUTABLE_BACKTEST_STRATEGY",
        "version": "1.2",
        "question_uid": question.question_uid,
        "readiness_status": incubation.readiness_status,
        "execution_policy": {
            "allowed": ["offline research", "backtest", "human review", "paper trading later"],
            "prohibited": [
                "live order submission",
                "broker credential access",
                "changing acceptance gates after seeing results",
            ],
        },
        "specification": incubation.specification_json,
        "model": incubation.model,
        "prompt_version": incubation.prompt_version,
    }


def _validation_export_package(
    session: Session,
    question: ResearchQuestion,
    spec: ResearchValidationSpec,
) -> dict[str, Any]:
    evidence_package = _handoff_package(session, question, None)
    return {
        "package_type": "QRI_CANDIDATE_RESEARCH_QUESTION",
        "version": "2.0",
        "product_boundary": (
            "Research design only. The receiving system decides whether to create a "
            "hypothesis, freeze parameters, run historical validation, or construct a strategy."
        ),
        "question_uid": question.question_uid,
        "review_status": spec.review_status,
        "plain_language_question": question.plain_language_question or question.question,
        "academic_question": question.academic_question or question.question,
        "validation_specification": spec.specification_json,
        "literature_evidence": evidence_package["literature_evidence"],
        "prohibited_downstream_assumptions": [
            "Do not interpret this package as a trading strategy",
            "Do not infer position sizes, portfolio weights, or execution rules",
            "Do not treat author claims as verified facts",
            "Freeze any later hypothesis and parameters before historical validation",
        ],
        "model": spec.model,
        "prompt_version": spec.prompt_version,
    }


app = create_app()
