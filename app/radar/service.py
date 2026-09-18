from __future__ import annotations

import math
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AbstractBrief,
    Claim,
    InvestmentRelevance,
    KnowledgeDelta,
    Paper,
    RadarAssessment,
    ResearchQuestion,
    ResearchTheme,
    ScoutAssessment,
)

# The taxonomy is deliberately small.  A theme is a long-lived stream of
# knowledge, not a new bucket for every paper.
THEMES = {
    "momentum": ("动量与趋势", "Momentum and trend", ("momentum", "trend", "continuation")),
    "value": ("价值与估值", "Value and valuation", ("value", "valuation", "book-to-market")),
    "quality": (
        "质量与盈利能力",
        "Quality and profitability",
        ("quality", "profitability", "investment factor"),
    ),
    "low_risk": (
        "低风险异象",
        "Low-risk anomalies",
        ("low volatility", "low beta", "minimum variance"),
    ),
    "microstructure": (
        "市场微观结构",
        "Market microstructure",
        ("liquidity", "microstructure", "transaction cost", "price impact"),
    ),
    "shorting": (
        "做空约束",
        "Short-sale constraints",
        ("short interest", "securities lending", "borrow fee", "short-sale"),
    ),
    "institutional": (
        "机构与中介资本",
        "Institutional and intermediary capital",
        ("institutional", "intermediary capital", "limits to arbitrage", "fund flow"),
    ),
    "machine_learning": (
        "机器学习资产定价",
        "Machine-learning asset pricing",
        ("machine learning", "neural network", "random forest", "deep learning"),
    ),
    "events": (
        "事件与信息扩散",
        "Events and information diffusion",
        ("earnings", "announcement drift", "information diffusion", "attention"),
    ),
    "other_us_equity": ("其他美股横截面研究", "Other US-equity research", ()),
}

CONFLICT_TERMS = (
    "decline",
    "decay",
    "disappear",
    "failure",
    "fails",
    "replication",
    "not robust",
    "insignificant",
    "reversal",
    "crowding",
    "post-publication",
    "no evidence",
    "weakens",
)
FALSIFICATION_TERMS = (
    "point-in-time",
    "delisting",
    "survivorship",
    "look-ahead",
    "lookahead",
    "transaction cost",
    "implementation",
    "placebo",
    "out-of-sample",
    "out of sample",
    "robustness",
    "bias",
)
EVIDENCE_TERMS = (
    "out-of-sample",
    "point-in-time",
    "replication",
    "experiment",
    "identification",
    "instrumental variable",
    "difference-in-differences",
    "fama-macbeth",
    "placebo",
)
INVESTMENT_TERMS = (
    "portfolio",
    "holding period",
    "implementation",
    "transaction cost",
    "liquidity",
    "capacity",
    "out-of-sample",
    "forward",
)


class RadarService:
    """Low-cost, theme-aware incremental knowledge triage.

    Scores are research triage signals only.  None of the fields represent
    expected return, Sharpe, alpha, or a trading recommendation.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def assess(
        self,
        scout_limit: int | None = None,
        lookback_days: int = 3,
        threshold: float | None = None,
    ) -> list[RadarAssessment]:
        """Assess unseen papers and promote only material changes to Scout.

        ``scout_limit`` and the threshold are caps, not quotas.  Explicit
        arguments remain supported for the old CLI and tests; normal runs use
        the settings values.
        """
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=lookback_days)
        papers = list(
            self.session.scalars(
                select(Paper)
                .where(
                    Paper.created_at >= cutoff,
                    Paper.abstract.is_not(None),
                    ~exists(select(RadarAssessment.id).where(RadarAssessment.paper_id == Paper.id)),
                )
                .order_by(Paper.created_at.desc(), Paper.id.desc())
            )
        )
        rows: list[RadarAssessment] = []
        now = datetime.now(UTC).replace(tzinfo=None)
        for paper in papers:
            theme_key = self._theme_for(paper)
            theme = self._theme(theme_key)
            metrics = self._incremental_metrics(paper, theme.id)
            change_type = self._change_type(metrics)
            row = RadarAssessment(
                paper_id=paper.id,
                theme_id=theme.id,
                decision="CANDIDATE",
                change_type=change_type,
                relevance_score=round(metrics["relevance"], 4),
                novelty_score=round(metrics["novelty"], 4),
                conflict_score=round(metrics["conflict"], 4),
                evidence_potential_score=round(metrics["evidence"], 4),
                incremental_value_score=round(metrics["incremental"], 4),
                claim_conflict_score=round(metrics["conflict"], 4),
                falsification_value_score=round(metrics["falsification"], 4),
                investment_relevance_hint=round(metrics["investment"], 4),
                duplicate_knowledge_penalty=round(metrics["duplicate"], 4),
                radar_score=round(metrics["incremental"], 4),
                reason=self._reason(change_type, metrics),
            )
            self.session.add(row)
            rows.append(row)
            theme.paper_count += 1
            theme.last_scanned_at = now
            if change_type in {"CONFLICT", "NEW_GAP"}:
                theme.last_changed_at = now
                theme.last_material_change_at = now
            if change_type == "CONFLICT":
                theme.conflict_count += 1

            delta_type = self._delta_type(change_type, metrics)
            self.session.add(
                KnowledgeDelta(
                    theme_id=theme.id,
                    paper_id=paper.id,
                    source_id=paper.paper_uid,
                    source_type="PAPER",
                    delta_type=delta_type,
                    summary=self._delta_summary(paper, change_type, metrics),
                    materiality_score=round(metrics["incremental"], 4),
                    confidence=round(min(1.0, 0.55 + metrics["evidence"] * 0.45), 4),
                )
            )
        self.session.flush()

        max_items = scout_limit if scout_limit is not None else self.settings.scout_max_items
        score_threshold = (
            threshold if threshold is not None else self.settings.scout_score_threshold
        )
        ranked = sorted(
            rows,
            key=lambda item: (item.incremental_value_score, item.id),
            reverse=True,
        )
        # The cap has to be applied to the ranked sequence.  Collecting ids into
        # a set first would discard the ordering and silently promote whichever
        # rows the set happened to yield, which in practice meant the oldest
        # papers rather than the highest-scoring ones.
        eligible = [
            row
            for row in ranked
            if row.incremental_value_score >= score_threshold
            and row.change_type != "LOW_INCREMENTAL_VALUE"
        ]
        selected = {row.id for row in eligible[: max(0, max_items)]}
        for row in rows:
            row.decision = "SCOUT" if row.id in selected else "ARCHIVED"
        self.refresh_theme_counts(commit=False)
        self.session.commit()
        return rows

    def backfill_existing(self) -> int:
        """Add incremental metadata for pre-0012 radar rows without rewriting them."""
        rows = list(self.session.scalars(select(RadarAssessment)))
        created = 0
        for row in rows:
            if not row.incremental_value_score:
                row.incremental_value_score = row.radar_score
            if not row.claim_conflict_score:
                row.claim_conflict_score = row.conflict_score
            if not row.falsification_value_score:
                row.falsification_value_score = row.evidence_potential_score
            if not row.investment_relevance_hint:
                row.investment_relevance_hint = row.relevance_score
            if not row.duplicate_knowledge_penalty:
                row.duplicate_knowledge_penalty = max(0.0, 1.0 - row.novelty_score)
            has_delta = self.session.scalar(
                select(KnowledgeDelta.id).where(KnowledgeDelta.paper_id == row.paper_id)
            )
            if has_delta:
                continue
            delta_type = {
                "CONFLICT": "NEW_CONFLICT",
                "NEW_GAP": "NEW_EVIDENCE",
                "EXTENSION": "NEW_CONDITION",
            }.get(row.change_type, "NO_MATERIAL_CHANGE")
            self.session.add(
                KnowledgeDelta(
                    theme_id=row.theme_id,
                    paper_id=row.paper_id,
                    source_type="PAPER",
                    delta_type=delta_type,
                    summary=(
                        "迁移前 Radar 记录已保留，并补充为增量知识记录；原论文证据链未改写。"
                    ),
                    materiality_score=row.incremental_value_score,
                    confidence=min(1.0, 0.55 + row.evidence_potential_score * 0.45),
                )
            )
            created += 1
        self.session.commit()
        return created

    def build_scout_assessments(self, *, commit: bool = True) -> list[ScoutAssessment]:
        """Create a structured, non-trading Scout assessment for each Scout row."""
        rows = list(
            self.session.scalars(
                select(RadarAssessment).where(RadarAssessment.decision == "SCOUT")
            )
        )
        result: list[ScoutAssessment] = []
        for radar in rows:
            existing = self.session.scalar(
                select(ScoutAssessment).where(ScoutAssessment.paper_id == radar.paper_id)
            )
            brief = self.session.scalar(
                select(AbstractBrief).where(AbstractBrief.paper_id == radar.paper_id)
            )
            confidence = brief.confidence if brief and brief.confidence is not None else 0.0
            research_value = min(
                1.0,
                0.60 * radar.incremental_value_score
                + 0.20 * radar.falsification_value_score
                + 0.20 * confidence,
            )
            investment = min(
                1.0,
                0.65 * radar.investment_relevance_hint
                + 0.20 * radar.relevance_score
                + 0.15 * radar.falsification_value_score,
            )
            values = {
                "theme_id": radar.theme_id,
                "research_value_score": round(research_value, 4),
                "investment_relevance_score": round(investment, 4),
                "novelty": radar.novelty_score,
                "evidence_potential": radar.evidence_potential_score,
                "conflict_potential": radar.claim_conflict_score,
                "falsification_potential": radar.falsification_value_score,
                "data_availability_hint": min(1.0, radar.evidence_potential_score + 0.2),
                "implementation_feasibility_hint": min(
                    1.0, 0.55 + radar.investment_relevance_hint * 0.35
                ),
                "recommend_deep_research": research_value >= self.settings.deep_research_threshold,
                "reason": (
                    "增量研究价值与证伪价值达到侦察门槛；投资相关性仅表示后续假设的"
                    "可转化性，不代表收益预测。"
                ),
            }
            if existing:
                for key, value in values.items():
                    setattr(existing, key, value)
                scout = existing
            else:
                scout = ScoutAssessment(paper_id=radar.paper_id, **values)
                self.session.add(scout)
            self._upsert_investment_relevance(radar, investment)
            result.append(scout)
        self.session.flush()
        if commit:
            self.session.commit()
        return result

    def prioritize(
        self,
        deep_limit: int | None = None,
        threshold: float | None = None,
    ) -> list[RadarAssessment]:
        """Promote only threshold-passing Scout rows to Deep Research."""
        self.build_scout_assessments(commit=False)
        rows = list(
            self.session.scalars(
                select(RadarAssessment).where(RadarAssessment.decision == "SCOUT")
            )
        )
        score_threshold = (
            threshold
            if threshold is not None
            else self.settings.deep_research_threshold
        )
        max_items = deep_limit if deep_limit is not None else self.settings.deep_research_max_items
        scored: list[tuple[float, RadarAssessment]] = []
        for row in rows:
            scout = self.session.scalar(
                select(ScoutAssessment).where(ScoutAssessment.paper_id == row.paper_id)
            )
            score = scout.research_value_score if scout else 0.0
            if scout:
                score = 0.85 * scout.research_value_score + 0.15 * scout.investment_relevance_score
            scored.append((score, row))
        chosen = [
            row
            for score, row in sorted(scored, key=lambda item: item[0], reverse=True)
            if score >= score_threshold
        ][: max(0, max_items)]
        chosen_ids = {row.id for row in chosen}
        for _score, row in scored:
            row.decision = "DEEP" if row.id in chosen_ids else "ARCHIVED_AFTER_SCOUT"
            scout = self.session.scalar(
                select(ScoutAssessment).where(ScoutAssessment.paper_id == row.paper_id)
            )
            if scout:
                scout.recommend_deep_research = row.id in chosen_ids
        self.refresh_theme_counts(commit=False)
        self.session.commit()
        return chosen

    def refresh_theme_counts(self, *, commit: bool = True) -> None:
        for theme in self.session.scalars(select(ResearchTheme)):
            theme.paper_count = (
                self.session.scalar(
                    select(func.count())
                    .select_from(RadarAssessment)
                    .where(RadarAssessment.theme_id == theme.id)
                )
                or 0
            )
            theme.claim_count = (
                self.session.scalar(
                    select(func.count())
                    .select_from(Claim)
                    .join(RadarAssessment, RadarAssessment.paper_id == Claim.paper_id)
                    .where(RadarAssessment.theme_id == theme.id)
                )
                or 0
            )
            theme.conflict_count = (
                self.session.scalar(
                    select(func.count())
                    .select_from(KnowledgeDelta)
                    .where(
                        KnowledgeDelta.theme_id == theme.id,
                        KnowledgeDelta.delta_type.in_(("NEW_CONFLICT", "NEW_COUNTER_MECHANISM")),
                    )
                )
                or 0
            )
            theme.evidence_density = round(theme.claim_count / max(1, theme.paper_count), 4)
            theme.known_claims_json = [
                claim_id
                for claim_id in self.session.scalars(
                    select(Claim.id)
                    .join(RadarAssessment, RadarAssessment.paper_id == Claim.paper_id)
                    .where(RadarAssessment.theme_id == theme.id)
                    .order_by(Claim.id)
                    .limit(200)
                )
            ]
            theme.known_conflicts_json = [
                delta_id
                for delta_id in self.session.scalars(
                    select(KnowledgeDelta.id)
                    .where(
                        KnowledgeDelta.theme_id == theme.id,
                        KnowledgeDelta.delta_type.in_(
                            ("NEW_CONFLICT", "NEW_COUNTER_MECHANISM")
                        ),
                    )
                    .order_by(KnowledgeDelta.created_at.desc())
                    .limit(100)
                )
            ]
            active_question_ids = []
            for question in self.session.scalars(
                select(ResearchQuestion)
                .where(ResearchQuestion.archived_at.is_(None))
                .order_by(ResearchQuestion.id.desc())
                .limit(200)
            ):
                claim_ids = set(question.supporting_claims_json or []) | set(
                    question.contradicting_claims_json or []
                )
                if claim_ids and set(theme.known_claims_json or []) & claim_ids:
                    active_question_ids.append(question.id)
            theme.active_research_questions_json = active_question_ids[:50]
            theme.research_maturity = (
                "DENSE"
                if theme.paper_count >= 20
                else "EMERGING"
                if theme.paper_count >= 3
                else "SEED"
            )
        if commit:
            self.session.commit()

    def _upsert_investment_relevance(self, radar: RadarAssessment, investment: float) -> None:
        row = self.session.scalar(
            select(InvestmentRelevance).where(
                InvestmentRelevance.paper_id == radar.paper_id,
                InvestmentRelevance.question_id.is_(None),
            )
        )
        values = {
            "theme_id": radar.theme_id,
            "hypothesis_convertibility": round(investment, 4),
            "data_availability": min(1.0, radar.evidence_potential_score + 0.2),
            "holding_period_fit": 0.5,
            "implementation_complexity": round(1.0 - radar.falsification_value_score * 0.25, 4),
            "forward_validation_feasibility": min(1.0, radar.relevance_score),
            "capital_fit": 0.5,
            "summary": "仅评估后续研究假设的可转化性，不预测收益、风险调整收益或利润。",
        }
        if row:
            for key, value in values.items():
                setattr(row, key, value)
        else:
            self.session.add(InvestmentRelevance(paper_id=radar.paper_id, **values))

    def _theme(self, key: str) -> ResearchTheme:
        theme = self.session.scalar(select(ResearchTheme).where(ResearchTheme.theme_key == key))
        if theme:
            return theme
        name_zh, name_en, _ = THEMES[key]
        theme = ResearchTheme(
            theme_key=key,
            name_zh=name_zh,
            name_en=name_en,
            family=key,
            plain_language_summary=f"持续跟踪{ name_zh }的新证据、冲突与研究缺口。",
            academic_summary=f"Long-lived evidence stream for {name_en}.",
            research_maturity="SEED",
        )
        self.session.add(theme)
        self.session.flush()
        return theme

    @staticmethod
    def _theme_for(paper: Paper) -> str:
        text = f"{paper.title} {paper.abstract or ''}".lower()
        matches = {
            key: sum(1 for term in terms if term in text)
            for key, (_, _, terms) in THEMES.items()
            if terms
        }
        return (
            max(matches, key=lambda item: matches[item])
            if matches and max(matches.values())
            else "other_us_equity"
        )

    def _incremental_metrics(self, paper: Paper, theme_id: int) -> dict[str, float]:
        theme_key = self._theme_for(paper)
        relevance = self._relevance(paper, theme_key)
        novelty = self._novelty(paper, theme_id)
        duplicate = max(0.0, 1.0 - novelty)
        conflict = self._term_score(paper, CONFLICT_TERMS)
        falsification = self._term_score(paper, FALSIFICATION_TERMS)
        evidence = self._evidence_potential(paper)
        investment = self._term_score(paper, INVESTMENT_TERMS)
        incremental = min(
            1.0,
            0.30 * novelty
            + 0.25 * conflict
            + 0.20 * falsification
            + 0.15 * evidence
            + 0.10 * relevance,
        )
        return {
            "relevance": relevance,
            "novelty": novelty,
            "duplicate": duplicate,
            "conflict": conflict,
            "falsification": falsification,
            "evidence": evidence,
            "investment": investment,
            "incremental": incremental,
        }

    @staticmethod
    def _change_type(metrics: dict[str, float]) -> str:
        if (
            metrics["duplicate"] >= 0.80
            and metrics["conflict"] < 0.35
            and metrics["incremental"] < 0.48
        ):
            return "LOW_INCREMENTAL_VALUE"
        if metrics["conflict"] >= 0.45:
            return "CONFLICT"
        if metrics["novelty"] >= 0.70 and metrics["incremental"] >= 0.48:
            return "NEW_GAP"
        if metrics["incremental"] >= 0.48:
            return "EXTENSION"
        return "NO_CHANGE"

    @staticmethod
    def _delta_type(change_type: str, metrics: dict[str, float]) -> str:
        if change_type == "CONFLICT":
            return "NEW_CONFLICT"
        if metrics["falsification"] >= 0.55:
            return "NEW_COUNTER_MECHANISM"
        if change_type == "NEW_GAP":
            return "NEW_EVIDENCE"
        if change_type == "EXTENSION":
            return "NEW_CONDITION"
        if metrics["evidence"] >= 0.45:
            return "CLAIM_STRENGTHENED"
        return "NO_MATERIAL_CHANGE"

    @staticmethod
    def _relevance(paper: Paper, theme_key: str) -> float:
        scope = 0.75 if paper.research_scope == "US_EQUITY_CORE" else 0.55
        theme_bonus = 0.15 if theme_key != "other_us_equity" else 0.0
        return min(1.0, scope + theme_bonus + (0.10 if paper.abstract else 0.0))

    def _novelty(self, paper: Paper, theme_id: int) -> float:
        current = self._tokens(f"{paper.title} {paper.abstract or ''}")
        prior_titles = list(
            self.session.scalars(
                select(Paper.title)
                .join(RadarAssessment, RadarAssessment.paper_id == Paper.id)
                .where(RadarAssessment.theme_id == theme_id, Paper.id != paper.id)
                .order_by(Paper.id.desc())
                .limit(80)
            )
        )
        similarity = max(
            (self._jaccard(current, self._tokens(title)) for title in prior_titles), default=0.0
        )
        return max(0.15, 1.0 - similarity)

    @staticmethod
    def _term_score(paper: Paper, terms: tuple[str, ...]) -> float:
        text = f"{paper.title} {paper.abstract or ''}".lower()
        hits = sum(1 for term in terms if term in text)
        return min(1.0, hits / 2)

    def _evidence_potential(self, paper: Paper) -> float:
        abstract = paper.abstract or ""
        length_score = min(0.55, len(abstract) / 2000)
        method_score = 0.30 * self._term_score(paper, EVIDENCE_TERMS)
        citation_score = min(0.15, math.log1p(paper.citation_count or 0) / 50)
        return min(1.0, length_score + method_score + citation_score)

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z]{3,}", text.lower())
            if token not in {"the", "and", "for", "with", "from"}
        }

    @staticmethod
    def _jaccard(left: set[str], right: set[str]) -> float:
        return len(left & right) / len(left | right) if left and right else 0.0

    @staticmethod
    def _reason(change: str, metrics: dict[str, float]) -> str:
        labels = {
            "CONFLICT": "可能改变已有观点：出现衰减、失败、反转或复现冲突信号。",
            "NEW_GAP": "可能形成新研究缺口：与主题已有知识重合度较低。",
            "EXTENSION": "为已有主题增加了条件、样本或实现约束。",
            "LOW_INCREMENTAL_VALUE": "与已有主题高度重复，暂不进入深研。",
            "NO_CHANGE": "暂未发现足以改变现有知识的增量，自动归档。",
        }
        scores = (
            f"增量 {metrics['incremental']:.2f}，冲突 {metrics['conflict']:.2f}，"
            f"证伪价值 {metrics['falsification']:.2f}，重复惩罚 {metrics['duplicate']:.2f}。"
        )
        return f"{labels[change]} {scores}"

    @staticmethod
    def _delta_summary(paper: Paper, change: str, metrics: dict[str, float]) -> str:
        title = (paper.title or "未命名研究").strip()
        if change == "LOW_INCREMENTAL_VALUE":
            return f"{title} 与主题已有材料高度重复，未形成可用的新研究增量。"
        if change == "CONFLICT":
            return f"{title} 提供了可能削弱或限定既有结论的冲突线索，需要定向证伪。"
        if change == "NEW_GAP":
            return f"{title} 可能把主题推进到新的样本、时期、机制或实现条件。"
        return f"{title} 为主题增加了待侦察的条件性证据。"
