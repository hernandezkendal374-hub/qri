"""Shared helpers behind the QRI web routes.

Pulled out of app.main so the individual route modules can import them without
importing each other. The function bodies are unchanged; the names that cross
module boundaries simply lost their leading underscore.
"""

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evidence.verification import field_verification_status
from app.models import (
    Claim,
    Evidence,
    Paper,
    QuestionTranslation,
    ResearchCard,
    ResearchQuestion,
    ResearchValidationSpec,
    StrategyIncubation,
)
from app.schemas.research import PaperResearchCard

# app/, not app/web/: templates and static live one level up from here.
APP_DIR = Path(__file__).resolve().parents[1]
IS_WINDOWS = sys.platform == "win32"

def launch_funnel_process(run_id: str) -> None:
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


def research_merit(session: Session, question: ResearchQuestion) -> dict[str, float]:
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
    numeric_confidences = [value for value in confidences if value is not None]
    evidence_quality = (
        sum(numeric_confidences) / len(numeric_confidences)
        if numeric_confidences
        else 0.35
    )
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


def localized_label(value: Any, labels: dict[str, str]) -> str:
    raw_value = getattr(value, "value", value)
    return labels.get(str(raw_value), str(raw_value).replace("_", " ").title())


LOCAL_ZONE = ZoneInfo("Asia/Shanghai")
DAILY_TASK_NAME = "QRI Daily Research Funnel"


def local_datetime(value: datetime | None, format_string: str = "%Y-%m-%d %H:%M") -> str:
    """Render the naive UTC timestamps stored by QRI in China local time."""
    if value is None:
        return "—"
    aware_value = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware_value.astimezone(LOCAL_ZONE).strftime(format_string)


def local_datetime_zh(value: datetime | None) -> str:
    if value is None:
        return "—"
    aware_value = value if value.tzinfo else value.replace(tzinfo=UTC)
    local_value = aware_value.astimezone(LOCAL_ZONE)
    return f"{local_value.month}月{local_value.day}日 {local_value:%H:%M}"


def _windows_scheduled_task_exists() -> bool:
    """Query the Windows task scheduler.  Only called on win32."""
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


def daily_schedule_enabled() -> bool:
    # The scheduled funnel is a Windows-only convenience; every other platform
    # drives it from cron or a systemd timer, so there is nothing to query.
    # IS_WINDOWS goes through a variable on purpose: comparing sys.platform
    # inline makes the type checker treat the rest of the body as dead code on
    # whichever platform it happens to be analysing.
    if not IS_WINDOWS:
        return False
    return _windows_scheduled_task_exists()


def fulltext_reason_zh(reason: str | None) -> str:
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


def research_card_fields(session: Session, card: ResearchCard) -> list[dict[str, Any]]:
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


def handoff_package(
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


def strategy_export_package(
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


def validation_export_package(
    session: Session,
    question: ResearchQuestion,
    spec: ResearchValidationSpec,
) -> dict[str, Any]:
    evidence_package = handoff_package(session, question, None)
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

