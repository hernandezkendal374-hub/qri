from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Claim, CommunityObservation, FalsificationTask, Paper, ResearchTheme
from app.providers.community.quant_stackexchange import sanitize_external_text, unix_datetime
from app.providers.sources import CommunityRecord

OBSERVATION_TYPES = {
    "replication": "REPLICATION_FAILURE",
    "reproduc": "REPLICATION_FAILURE",
    "implement": "IMPLEMENTATION_TRAP",
    "cost": "IMPLEMENTATION_TRAP",
    "counterexample": "COUNTEREXAMPLE",
    "counter example": "COUNTEREXAMPLE",
    "assumption": "HIDDEN_ASSUMPTION",
    "bias": "METHODOLOGY_CRITIQUE",
    "method": "METHODOLOGY_CRITIQUE",
}
ATTACK_DIMENSIONS = {
    "delisting": "UNIVERSE",
    "survivorship": "BIAS",
    "point-in-time": "DATA",
    "transaction cost": "COST",
    "cost": "COST",
    "borrow": "COST",
    "execution": "EXECUTION",
    "vwap": "EXECUTION",
    "statistics": "STATISTICS",
    "p-value": "STATISTICS",
    "regime": "REGIME",
    "implementation": "IMPLEMENTATION",
}


def claim_driven_queries(claim_text: str, *, theme_name: str = "") -> list[str]:
    """Turn a Claim into narrow, inert community attack queries."""
    clean = re.sub(r"[^\w\s-]", " ", claim_text, flags=re.UNICODE)
    words = [word for word in clean.split() if len(word) > 2][:8]
    anchor = " ".join(words)
    theme = re.sub(r"[^\w\s-]", " ", theme_name, flags=re.UNICODE).strip()
    base = " ".join(item for item in (theme, anchor) if item).strip() or "quantitative finance"
    return [
        f"{base} transaction cost replication",
        f"{base} implementation",
        f"{base} delisting point in time",
        f"{base} execution",
        f"{base} microcap liquidity",
    ]


class ShadowCommunityService:
    """Persist community observations without touching formal evidence."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def ingest(
        self,
        records: Iterable[CommunityRecord],
        *,
        theme: ResearchTheme | None = None,
        paper: Paper | None = None,
        claim: Claim | None = None,
    ) -> list[CommunityObservation]:
        observations: list[CommunityObservation] = []
        for record in records:
            text = self._observation_text(record)
            content_hash = hashlib.sha256(
                f"{record.provider}:{record.provider_id}:{text}".encode()
            ).hexdigest()
            existing = self.session.scalar(
                select(CommunityObservation).where(
                    CommunityObservation.content_hash == content_hash
                )
            )
            if existing:
                continue
            observation = CommunityObservation(
                source_provider=record.provider,
                source_tier="COMMUNITY",
                target_theme_id=theme.id if theme else None,
                target_paper_id=paper.id if paper else None,
                target_claim_id=claim.id if claim else None,
                observation_type=self._observation_type(text),
                observation_text=text,
                implementation_conditions=self._conditions(record),
                author_name=record.author_name,
                author_reputation=record.author_reputation,
                votes=record.score,
                accepted_answer=bool(record.accepted_answer),
                source_url=record.source_url,
                captured_at=unix_datetime(record.last_activity_date)
                or datetime.now(UTC).replace(tzinfo=None),
                edited_at=unix_datetime(record.last_edit_date),
                content_hash=content_hash,
                code_links_json=[url for url in record.links if self._is_code_link(url)],
                data_links_json=[url for url in record.links if not self._is_code_link(url)],
                verification_status="UNVERIFIED",
                independence_score=self._independence(record),
                reproducibility_score=self._reproducibility(record),
                attack_dimension=self._attack_dimension(text),
            )
            self.session.add(observation)
            self.session.flush()
            task = FalsificationTask(
                theme_id=theme.id if theme else None,
                claim_id=claim.id if claim else None,
                observation_id=observation.id,
                question=self._task_question(observation, claim),
                attack_dimension=observation.attack_dimension,
                required_data_json=self._required_data(observation),
                required_code_json=list(observation.code_links_json or []),
                required_checks_json=[
                    "保留未见过未来信息的时间切分",
                    "报告样本范围、退市处理和交易成本敏感性",
                    "仅由独立验证环境执行，QRI 不自动回测",
                ],
                status="PROPOSED",
            )
            self.session.add(task)
            self.session.flush()
            observation.generated_test_task_id = task.id
            observations.append(observation)
        self.session.commit()
        return observations

    @staticmethod
    def _observation_text(record: CommunityRecord) -> str:
        answers = "\n\n".join(
            f"回答（得分 {answer.score}）：{answer.body}" for answer in record.answers[:3]
        )
        return sanitize_external_text(f"{record.title}\n{record.body}\n{answers}")

    @staticmethod
    def _conditions(record: CommunityRecord) -> str:
        if record.tags:
            return "标签：" + ", ".join(record.tags)
        return "社区文本未提供结构化实现条件；需要人工补充。"

    @staticmethod
    def _observation_type(text: str) -> str:
        lowered = text.casefold()
        for marker, value in OBSERVATION_TYPES.items():
            if marker in lowered:
                return value
        return "RESEARCH_IDEA"

    @staticmethod
    def _attack_dimension(text: str) -> str:
        lowered = text.casefold()
        for marker, value in ATTACK_DIMENSIONS.items():
            if marker in lowered:
                return value
        return "OTHER"

    @staticmethod
    def _independence(record: CommunityRecord) -> float:
        accepted_bonus = 0.20 if record.accepted_answer else 0.0
        return round(min(1.0, 0.35 + max(0, record.score) / 25 + accepted_bonus), 4)

    @staticmethod
    def _reproducibility(record: CommunityRecord) -> float:
        code_or_data = len(record.links) + sum(len(answer.links) for answer in record.answers)
        conditions = bool(record.tags) or len(record.body) > 300
        return round(min(1.0, 0.20 + code_or_data * 0.12 + (0.25 if conditions else 0)), 4)

    @staticmethod
    def _is_code_link(url: str) -> bool:
        lowered = url.casefold()
        return any(host in lowered for host in ("github.com", "gitlab.com", "gist.github.com"))

    @staticmethod
    def _task_question(observation: CommunityObservation, claim: Claim | None) -> str:
        target = claim.claim_text if claim else "相关研究结论"
        return (
            f"在攻击维度 {observation.attack_dimension} 下，社区观察是否能在独立数据与代码"
            f"条件下证伪或限定该结论：{target}？"
        )

    @staticmethod
    def _required_data(observation: CommunityObservation) -> list[str]:
        data = {
            "DATA": ["Point-in-time 数据与版本记录"],
            "UNIVERSE": ["含退市证券的完整历史股票池"],
            "COST": ["交易成本、借券或流动性数据"],
            "EXECUTION": ["可审计的成交时点和价格数据"],
            "BIAS": ["样本构建与未来数据审计"],
            "STATISTICS": ["独立样本与多重检验校正"],
            "REGIME": ["跨时期、跨市场状态数据"],
            "IMPLEMENTATION": ["论文/代码的参数与实现记录"],
        }
        return data.get(observation.attack_dimension, ["与原 Claim 一致的原始数据和实现记录"])
