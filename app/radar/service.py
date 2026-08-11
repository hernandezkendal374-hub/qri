from __future__ import annotations

import math
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.models import AbstractBrief, Claim, Paper, RadarAssessment, ResearchTheme

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


class RadarService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def assess(self, scout_limit: int = 20, lookback_days: int = 3) -> list[RadarAssessment]:
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
        for paper in papers:
            theme_key = self._theme_for(paper)
            theme = self._theme(theme_key)
            relevance = self._relevance(paper, theme_key)
            novelty = self._novelty(paper, theme.id)
            conflict = self._term_score(paper, CONFLICT_TERMS)
            evidence = self._evidence_potential(paper)
            score = 0.35 * relevance + 0.30 * novelty + 0.20 * conflict + 0.15 * evidence
            change_type = (
                "CONFLICT"
                if conflict >= 0.45
                else "NEW_GAP"
                if novelty >= 0.70
                else "EXTENSION"
                if score >= 0.50
                else "NO_CHANGE"
            )
            row = RadarAssessment(
                paper_id=paper.id,
                theme_id=theme.id,
                decision="CANDIDATE",
                change_type=change_type,
                relevance_score=round(relevance, 4),
                novelty_score=round(novelty, 4),
                conflict_score=round(conflict, 4),
                evidence_potential_score=round(evidence, 4),
                radar_score=round(score, 4),
                reason=self._reason(change_type, relevance, novelty, conflict),
            )
            self.session.add(row)
            rows.append(row)
            theme.paper_count += 1
            if change_type in {"CONFLICT", "NEW_GAP"}:
                theme.last_changed_at = datetime.now(UTC).replace(tzinfo=None)
            if change_type == "CONFLICT":
                theme.conflict_count += 1
        self.session.flush()
        ranked = sorted(rows, key=lambda item: item.radar_score, reverse=True)
        selected = {row.id for row in ranked[:scout_limit] if row.radar_score >= 0.40}
        for row in rows:
            row.decision = "SCOUT" if row.id in selected else "ARCHIVED"
        self.session.commit()
        return rows

    def prioritize(self, deep_limit: int = 3, threshold: float = 0.58) -> list[RadarAssessment]:
        rows = list(
            self.session.scalars(
                select(RadarAssessment)
                .where(RadarAssessment.decision == "SCOUT")
                .order_by(RadarAssessment.assessed_at.desc())
            )
        )
        scored: list[tuple[float, RadarAssessment]] = []
        for row in rows:
            brief = self.session.scalar(
                select(AbstractBrief).where(AbstractBrief.paper_id == row.paper_id)
            )
            if not brief:
                scored.append((0.0, row))
                continue
            brief_confidence = brief.confidence if brief.confidence is not None else 0.0
            score = 0.80 * row.radar_score + 0.20 * brief_confidence
            scored.append((score, row))
        chosen = [
            row
            for score, row in sorted(scored, reverse=True, key=lambda x: x[0])
            if score >= threshold
        ][:deep_limit]
        chosen_ids = {row.id for row in chosen}
        for _, row in scored:
            row.decision = "DEEP" if row.id in chosen_ids else "ARCHIVED_AFTER_SCOUT"
        self.session.commit()
        return chosen

    def refresh_theme_counts(self) -> None:
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
                    .select_from(RadarAssessment)
                    .where(
                        RadarAssessment.theme_id == theme.id,
                        RadarAssessment.change_type == "CONFLICT",
                    )
                )
                or 0
            )
        self.session.commit()

    def _theme(self, key: str) -> ResearchTheme:
        theme = self.session.scalar(select(ResearchTheme).where(ResearchTheme.theme_key == key))
        if theme:
            return theme
        name_zh, name_en, _ = THEMES[key]
        theme = ResearchTheme(theme_key=key, name_zh=name_zh, name_en=name_en)
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
            max(matches, key=matches.get)
            if matches and max(matches.values())
            else "other_us_equity"
        )

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
                .limit(50)
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
    def _reason(change: str, relevance: float, novelty: float, conflict: float) -> str:
        labels = {
            "CONFLICT": "可能改变已有观点：摘要出现衰减、失败或复现冲突信号。",
            "NEW_GAP": "可能形成新研究缺口：与该主题既有材料重合度较低。",
            "EXTENSION": "与既有主题相关，适合低成本侦察后再决定。",
            "NO_CHANGE": "暂未发现足以改变现有知识的增量，自动归档。",
        }
        scores = f"相关性 {relevance:.2f}，新颖度 {novelty:.2f}，冲突度 {conflict:.2f}。"
        return f"{labels[change]} {scores}"
