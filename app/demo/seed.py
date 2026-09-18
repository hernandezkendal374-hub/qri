"""Synthetic fixture data so QRI can be evaluated before it is configured.

Running the real funnel needs a Postgres instance, an OpenAI-compatible model
endpoint, and a scan across several public APIs.  That is a lot to ask of
somebody deciding whether the project is worth their attention, so this module
populates every page with a small, self-contained example instead.

Everything here is invented.  The papers, authors, venues, numbers and
community posts do not exist, and every record is tagged ``source="demo"`` so
it can never be mistaken for, or mixed into, a real run.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    AbstractBrief,
    Claim,
    CommunityObservation,
    Document,
    Evidence,
    FalsificationTask,
    KnowledgeDelta,
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
    ScoutAssessment,
)
from app.models.entities import FullTextStatus
from app.radar import RadarService

DEMO_SOURCE = "demo"
DEMO_MODEL = "demo-fixture"
DEMO_VENUE = "Synthetic QRI demo record — not a real publication"
_NOW = datetime.now(UTC).replace(tzinfo=None)


def _hours_ago(hours: float) -> datetime:
    return _NOW - timedelta(hours=hours)


# --------------------------------------------------------------------------
# Full text for the one paper that reaches deep research.  Evidence offsets are
# computed from this string, so the quotes stored below really are verbatim and
# the evidence locator can be checked against them.
# --------------------------------------------------------------------------
DEMO_FULLTEXT = """Momentum After Publication: A Replication on Point-in-Time Data

1. Introduction

We revisit the cross-sectional momentum premium documented in the earlier
literature using a point-in-time universe that retains delisted securities.
Our sample runs from 1972 to 2023 and covers all common shares listed on the
three major US exchanges.

2. Data and Method

We reconstruct the universe monthly from point-in-time listing files, so a
security that was delisted in month t remains investable up to month t. Prior
work that rebuilt the universe from a survivor-only snapshot mechanically
excluded the worst-performing names.

3. Results

The long-short momentum portfolio earns a raw spread of 0.84 percent per month
before costs in the 1972-1993 subsample. In the post-publication subsample the
same portfolio earns 0.21 percent per month, and the difference is significant
at conventional levels.

Once we apply a realistic transaction cost model calibrated to quoted spreads,
the post-publication spread is statistically indistinguishable from zero. The
decay is concentrated in the smallest quintile of the universe.

4. Limitations

Our cost model is calibrated to quoted spreads rather than realised execution,
and we do not observe securities lending fees for the short leg. Results for
the microcap quintile should be treated as indicative only.
"""


@dataclass(frozen=True, slots=True)
class DemoPaper:
    title: str
    abstract: str
    authors: list[str]
    citation_count: int
    fulltext: bool


def _demo_papers() -> list[DemoPaper]:
    return [
        DemoPaper(
            title="Momentum After Publication: A Replication on Point-in-Time Data",
            abstract=(
                "We replicate the cross-sectional momentum premium on a point-in-time "
                "universe that retains delisted securities. The premium decays sharply "
                "after publication and the post-publication spread is indistinguishable "
                "from zero once quoted-spread transaction costs are applied. The decay "
                "is concentrated in the smallest quintile. Out-of-sample and placebo "
                "tests are reported."
            ),
            authors=["A. Demo", "B. Fixture"],
            citation_count=34,
            fulltext=True,
        ),
        DemoPaper(
            title="Short-Sale Constraints and the Limits of the Value Premium",
            abstract=(
                "We study how securities lending costs and borrow availability bound "
                "the implementable value premium in US equities. Using a point-in-time "
                "sample we show the premium survives on the long leg but the short leg "
                "is largely unimplementable for the highest borrow-fee decile. We run "
                "placebo and out-of-sample robustness checks."
            ),
            authors=["C. Placeholder"],
            citation_count=12,
            fulltext=False,
        ),
        DemoPaper(
            title="Liquidity Provision Under Venue Fragmentation",
            abstract=(
                "We measure price impact and effective spreads across fragmented US "
                "equity venues. Implementation shortfall rises with fragmentation for "
                "large parent orders, with implications for the capacity of published "
                "anomaly portfolios."
            ),
            authors=["D. Sample"],
            citation_count=7,
            fulltext=False,
        ),
        DemoPaper(
            title="Investor Attention and Post-Earnings Announcement Drift",
            abstract=(
                "We revisit announcement drift conditioning on retail attention proxies "
                "in a US equity sample."
            ),
            authors=["E. Example"],
            citation_count=3,
            fulltext=False,
        ),
        DemoPaper(
            title="A Neural Network Factor Zoo for US Equities",
            abstract=(
                "We train deep learning models on a large panel of firm characteristics "
                "to predict the cross section of returns."
            ),
            authors=["F. Synthetic"],
            citation_count=2,
            fulltext=False,
        ),
        DemoPaper(
            title="Intermediary Capital and Limits to Arbitrage Revisited",
            abstract=(
                "We relate intermediary capital ratios to the pricing of arbitrage "
                "spreads in US equities."
            ),
            authors=["G. Mock"],
            citation_count=5,
            fulltext=False,
        ),
        DemoPaper(
            title="Quality Minus Junk in International Samples",
            abstract="We extend the quality factor to non-US developed markets.",
            authors=["H. Stub"],
            citation_count=1,
            fulltext=False,
        ),
        DemoPaper(
            title="Low-Volatility Portfolios and Leverage Constraints",
            abstract="We revisit the low-risk anomaly under explicit leverage limits.",
            authors=["I. Dummy"],
            citation_count=4,
            fulltext=False,
        ),
    ]


_THEMES = [
    ("momentum", "动量与趋势", "Momentum and trend"),
    ("value", "价值与估值", "Value and valuation"),
    ("microstructure", "市场微观结构", "Market microstructure"),
]


def _evidence_span(quote: str) -> tuple[int, int]:
    start = DEMO_FULLTEXT.index(quote)
    return start, start + len(quote)


def clear_demo_data(session: Session) -> int:
    """Remove every record this module created, leaving real data untouched."""
    paper_ids = list(session.scalars(select(Paper.id).where(Paper.source == DEMO_SOURCE)))
    if not paper_ids:
        return 0
    question_ids = list(
        session.scalars(
            select(ResearchQuestion.id).where(ResearchQuestion.family.like("demo-%"))
        )
    )
    session.execute(delete(FalsificationTask))
    session.execute(delete(CommunityObservation))
    if question_ids:
        session.execute(
            delete(ResearchValidationSpec).where(
                ResearchValidationSpec.question_id.in_(question_ids)
            )
        )
        session.execute(
            delete(QuestionTranslation).where(
                QuestionTranslation.question_id.in_(question_ids)
            )
        )
        session.execute(delete(ResearchQuestion).where(ResearchQuestion.id.in_(question_ids)))
    for paper_scoped in (
        Evidence,
        Claim,
        ResearchCard,
        AbstractBrief,
        Document,
        ScoutAssessment,
        KnowledgeDelta,
        RadarAssessment,
    ):
        session.execute(delete(paper_scoped).where(paper_scoped.paper_id.in_(paper_ids)))
    session.execute(delete(Paper).where(Paper.id.in_(paper_ids)))
    session.execute(delete(PipelineStageRun).where(PipelineStageRun.run_id.like("demo-%")))
    session.execute(delete(PipelineRun).where(PipelineRun.run_id.like("demo-%")))
    session.execute(
        delete(ResearchTheme).where(
            ResearchTheme.theme_key.in_([key for key, _, _ in _THEMES])
        )
    )
    session.commit()
    return len(paper_ids)


def seed_demo_database(session: Session) -> dict[str, int]:
    """Populate every QRI page with a small synthetic example. Idempotent."""
    clear_demo_data(session)

    themes: dict[str, ResearchTheme] = {}
    for key, name_zh, name_en in _THEMES:
        theme = ResearchTheme(
            theme_key=key,
            name_zh=name_zh,
            name_en=name_en,
            family=key,
            plain_language_summary=f"持续跟踪{name_zh}的新证据、冲突与研究缺口。",
            academic_summary=f"Long-lived evidence stream for {name_en}.",
            research_maturity="EMERGING",
            last_scanned_at=_hours_ago(2),
        )
        session.add(theme)
        themes[key] = theme
    session.flush()

    papers: list[Paper] = []
    for index, spec in enumerate(_demo_papers()):
        paper = Paper(
            title=spec.title,
            normalized_title=spec.title.lower(),
            abstract=spec.abstract,
            authors_json=[{"name": name} for name in spec.authors],
            source=DEMO_SOURCE,
            venue=DEMO_VENUE,
            citation_count=spec.citation_count,
            research_scope="US_EQUITY_CORE",
            scope_reason="Demo fixture classified as US equity cross-sectional research.",
            scope_confidence=0.9,
            open_access=True,
            license="demo-fixture",
            fulltext_status=(
                FullTextStatus.FULLTEXT_AVAILABLE
                if spec.fulltext
                else FullTextStatus.ABSTRACT_ONLY
            ),
            fulltext_failure_reason=(
                None if spec.fulltext else "NO_OPEN_ACCESS_PDF (demo fixture)"
            ),
            created_at=_hours_ago(6 + index),
            first_seen_at=_hours_ago(6 + index),
        )
        session.add(paper)
        papers.append(paper)
    session.flush()

    # Funnel shape: 8 scanned, 3 promoted to Scout, 2 reaching deep research.
    radar_plan = [
        (0, "momentum", "CONFLICT", 0.91, "DEEP"),
        (1, "value", "CONFLICT", 0.74, "DEEP"),
        # prioritize() rewrites every SCOUT row, so a finished run leaves
        # DEEP or ARCHIVED_AFTER_SCOUT behind -- never a bare SCOUT.
        (2, "microstructure", "NEW_GAP", 0.63, "ARCHIVED_AFTER_SCOUT"),
        (3, "momentum", "EXTENSION", 0.41, "ARCHIVED"),
        (4, "momentum", "EXTENSION", 0.38, "ARCHIVED"),
        (5, "value", "NO_CHANGE", 0.29, "ARCHIVED"),
        (6, "value", "LOW_INCREMENTAL_VALUE", 0.18, "ARCHIVED"),
        (7, "microstructure", "LOW_INCREMENTAL_VALUE", 0.14, "ARCHIVED"),
    ]
    delta_by_change = {
        "CONFLICT": "NEW_CONFLICT",
        "NEW_GAP": "NEW_EVIDENCE",
        "EXTENSION": "NEW_CONDITION",
        "NO_CHANGE": "NO_MATERIAL_CHANGE",
        "LOW_INCREMENTAL_VALUE": "NO_MATERIAL_CHANGE",
    }
    for position, theme_key, change_type, score, decision in radar_plan:
        paper = papers[position]
        theme = themes[theme_key]
        session.add(
            RadarAssessment(
                paper_id=paper.id,
                theme_id=theme.id,
                decision=decision,
                change_type=change_type,
                relevance_score=0.9,
                novelty_score=round(min(1.0, score + 0.05), 4),
                conflict_score=round(score * 0.9, 4),
                evidence_potential_score=round(score * 0.8, 4),
                incremental_value_score=score,
                claim_conflict_score=round(score * 0.9, 4),
                falsification_value_score=round(score * 0.85, 4),
                investment_relevance_hint=round(score * 0.7, 4),
                duplicate_knowledge_penalty=round(max(0.0, 1.0 - score - 0.05), 4),
                radar_score=score,
                reason=(
                    "演示数据：分数由固定 fixture 给出，不是真实筛选结果。"
                    if change_type != "CONFLICT"
                    else "演示数据：标记为可能改变既有结论的冲突证据。"
                ),
                assessed_at=_hours_ago(4),
            )
        )
        session.add(
            KnowledgeDelta(
                theme_id=theme.id,
                paper_id=paper.id,
                source_id=paper.paper_uid,
                source_type="PAPER",
                delta_type=delta_by_change[change_type],
                summary=f"{paper.title} — 演示用增量知识记录。",
                materiality_score=score,
                confidence=0.7,
                created_at=_hours_ago(4),
            )
        )
        if decision in {"DEEP", "ARCHIVED_AFTER_SCOUT"}:
            session.add(
                ScoutAssessment(
                    paper_id=paper.id,
                    theme_id=theme.id,
                    research_value_score=score,
                    investment_relevance_score=round(score * 0.7, 4),
                    novelty=round(min(1.0, score + 0.05), 4),
                    evidence_potential=round(score * 0.8, 4),
                    conflict_potential=round(score * 0.9, 4),
                    falsification_potential=round(score * 0.85, 4),
                    data_availability_hint=0.8,
                    implementation_feasibility_hint=0.6,
                    recommend_deep_research=decision == "DEEP",
                    reason="演示数据：仅表示研究价值，不代表收益预测。",
                    created_at=_hours_ago(3),
                )
            )
            session.add(
                AbstractBrief(
                    paper_id=paper.id,
                    summary_zh=f"{paper.title}（演示数据）的摘要级解读。",
                    core_principle_zh="演示：说明这篇研究改变了我们已知的什么。",
                    economic_mechanism_zh="演示：论文提出的经济机制。",
                    methodology_zh="演示：论文使用的方法。",
                    reported_findings_json=["演示：作者报告的主要结果（未经证据核验）。"],
                    limitations_json=["演示：作者自述的限制。"],
                    reader_takeaway_zh="演示：这是 fixture 数据，不构成任何结论。",
                    confidence=0.6,
                    model=DEMO_MODEL,
                    prompt_version="abstract-brief-v1",
                    created_at=_hours_ago(3),
                )
            )
    session.flush()

    # Deep research artefacts for the momentum replication paper.
    deep_paper = papers[0]
    session.add(
        Document(
            paper_id=deep_paper.id,
            document_type="PDF",
            local_path="demo://momentum-replication.pdf",
            content_hash=hashlib.sha256(DEMO_FULLTEXT.encode()).hexdigest(),
            parser_version="demo-fixture",
            parsed_text=DEMO_FULLTEXT,
            created_at=_hours_ago(3),
        )
    )
    card = ResearchCard(
        paper_id=deep_paper.id,
        market="United States",
        asset_class="Common equity",
        universe="Common shares on the three major US exchanges, point-in-time",
        sample_start="1972",
        sample_end="2023",
        hypothesis="The momentum premium decays after publication.",
        mechanism="Investor underreaction to information, arbitraged away once published.",
        counter_mechanism="Crowding and rising implementation costs.",
        signal_definition="Twelve-month return skipping the most recent month.",
        formation_period="12 months",
        holding_period="1 month",
        rebalance_frequency="Monthly",
        portfolio_construction="Long-short decile spread",
        benchmark="Equal-weighted market",
        reported_return="0.84% per month (1972-1993); 0.21% per month post-publication",
        transaction_cost_handling="Quoted-spread cost model, not realised execution",
        survivorship_handling="Point-in-time universe retaining delisted securities",
        lookahead_handling="Monthly reconstruction from point-in-time listing files",
        in_sample="1972-1993",
        out_of_sample="1994-2023",
        robustness_tests_json=["Placebo test", "Subsample split", "Microcap exclusion"],
        required_data_json=["Point-in-time listing files", "Daily quoted spreads"],
        limitations_json=[
            "Cost model uses quoted spreads rather than realised execution",
            "Securities lending fees for the short leg are not observed",
        ],
        confidence=0.72,
        model=DEMO_MODEL,
        prompt_version="research-card-v1",
        created_at=_hours_ago(2),
    )
    session.add(card)
    session.flush()

    claim_specs = [
        (
            "The post-publication momentum spread is indistinguishable from zero once "
            "quoted-spread transaction costs are applied.",
            "Once we apply a realistic transaction cost model calibrated to quoted spreads,\n"
            "the post-publication spread is statistically indistinguishable from zero.",
            "reported_return",
            "NEGATIVE",
        ),
        (
            "The universe retains delisted securities, so the sample is not survivor-only.",
            "We reconstruct the universe monthly from point-in-time listing files, so a\n"
            "security that was delisted in month t remains investable up to month t.",
            "survivorship_handling",
            "NEUTRAL",
        ),
        (
            "The decay is concentrated in the smallest quintile of the universe.",
            "The\ndecay is concentrated in the smallest quintile of the universe.",
            "limitations_json",
            "NEGATIVE",
        ),
    ]
    claims: list[Claim] = []
    for claim_text, quote, field, direction in claim_specs:
        claim = Claim(
            paper_id=deep_paper.id,
            claim_type="AUTHOR_CLAIM",
            claim_text=claim_text,
            normalized_claim=claim_text.lower(),
            direction=direction,
            support_strength=0.7,
            confidence=0.7,
            created_at=_hours_ago(2),
        )
        session.add(claim)
        session.flush()
        claims.append(claim)
        start, end = _evidence_span(quote)
        session.add(
            Evidence(
                paper_id=deep_paper.id,
                claim_id=claim.id,
                research_card_field=field,
                page_number=1,
                section="Results",
                paragraph_index=DEMO_FULLTEXT[:start].count("\n\n"),
                source_text=quote,
                start_offset=start,
                end_offset=end,
                confidence=0.8,
                created_at=_hours_ago(2),
            )
        )
    session.flush()

    question = ResearchQuestion(
        question_uid="RQ-DEMO-0001",
        family="demo-momentum",
        question=(
            "Does the US cross-sectional momentum premium survive realistic transaction "
            "costs in the post-publication period on a point-in-time universe?"
        ),
        plain_language_question=(
            "After everyone found out about it, does the momentum trade still make money "
            "once you pay the real cost of trading?"
        ),
        academic_question=(
            "Conditional on a point-in-time universe retaining delisted securities, is the "
            "post-publication long-short momentum spread statistically distinguishable from "
            "zero net of quoted-spread transaction costs?"
        ),
        economic_mechanism="Underreaction is arbitraged away once the effect is published.",
        counter_mechanism="Measured decay is an artefact of the cost model, not of crowding.",
        supporting_claims_json=[claims[0].id, claims[2].id],
        contradicting_claims_json=[claims[1].id],
        required_data_json=[
            "Point-in-time US equity listing files including delistings",
            "Daily quoted spreads or an equivalent cost proxy",
            "Securities lending fees for the short leg",
        ],
        known_risks_json=[
            "Quoted spreads understate realised cost for large orders",
            "Microcap results may not be implementable at any size",
        ],
        novelty_score=0.71,
        testability_score=0.84,
        data_availability_score=0.66,
        research_priority_score=0.78,
        priority_type="P1_HIGH",
        status=QuestionStatus.HUMAN_REVIEW_REQUIRED,
        created_at=_hours_ago(1),
    )
    session.add(question)
    session.flush()

    session.add(
        QuestionTranslation(
            question_id=question.id,
            question_zh=(
                "在保留退市股票的 point-in-time 股票池下，动量premium 在公开发表之后，"
                "扣除真实交易成本后是否仍然显著不为零？"
            ),
            economic_mechanism_zh="信息反应不足在被公开后逐渐被套利消除。",
            counter_mechanism_zh="观测到的衰减可能来自成本模型设定，而非真实拥挤。",
            required_data_zh_json=[
                "包含退市记录的 point-in-time 美股股票池",
                "日频报价价差或等效成本代理",
                "空头腿的融券费率",
            ],
            known_risks_zh_json=[
                "报价价差会低估大单的真实成本",
                "微盘股结果可能在任何规模下都不可实现",
            ],
            model=DEMO_MODEL,
            prompt_version="question-translation-v1",
            created_at=_hours_ago(1),
        )
    )

    session.add(
        ResearchValidationSpec(
            question_id=question.id,
            review_status="HUMAN_REVIEW_REQUIRED",
            specification_json={
                "plain_language_question": question.plain_language_question,
                "academic_question": question.academic_question,
                "research_object": "US common equity, point-in-time universe, 1972-2023",
                "economic_mechanism": question.economic_mechanism,
                "counter_mechanism": question.counter_mechanism,
                "dependent_variable": {
                    "name": "Net long-short momentum spread",
                    "role": "DEPENDENT",
                    "academic_definition": "Monthly decile spread net of modelled costs.",
                    "measurement": "Value-weighted decile spread minus round-trip cost.",
                    "timing_rule": "Formed at month end t, held over t+1.",
                    "source_requirement": "Point-in-time returns including delistings.",
                },
                "independent_variables": [
                    {
                        "name": "Post-publication indicator",
                        "role": "INDEPENDENT",
                        "academic_definition": "One after the original publication year.",
                        "measurement": "Binary by calendar month.",
                        "timing_rule": "Known ex ante.",
                        "source_requirement": "Publication date of the original study.",
                    }
                ],
                "interaction_terms": [],
                "control_variables": [
                    {
                        "name": "Market excess return",
                        "role": "CONTROL",
                        "academic_definition": "Market factor return.",
                        "measurement": "Monthly excess return.",
                        "timing_rule": "Contemporaneous.",
                        "source_requirement": "Standard factor file.",
                    }
                ],
                "sample_design": [
                    "Monthly rebalanced deciles, 1972-2023",
                    "Split at the original publication year",
                ],
                "point_in_time_requirements": [
                    "Universe rebuilt monthly from listing files",
                    "Delisted securities retained until the delisting month",
                ],
                "statistical_tests": [
                    "Newey-West adjusted t-test on the net spread",
                    "Subsample difference test across the publication break",
                ],
                "out_of_sample_design": [
                    "Hold out 1994-2023 entirely when calibrating the cost model"
                ],
                "falsification_conditions": [
                    "The net post-publication spread is significantly positive",
                    "The decay disappears when microcaps are excluded",
                ],
                "minimum_data_requirements": [
                    "Point-in-time listing files with delistings",
                    "Daily quoted spreads",
                ],
                "bias_risks": [
                    "Survivorship bias if the universe is rebuilt from a current snapshot",
                    "Look-ahead bias from restated fundamentals",
                ],
                "implementation_sensitivities": [
                    "Cost model calibration dominates the sign of the result"
                ],
                "success_criteria": [
                    "A sign and significance conclusion that is stable across cost models"
                ],
                "human_review_questions": [
                    "Is the quoted-spread cost model acceptable for the smallest quintile?"
                ],
                "prohibited_interpretations": [
                    "This is a research validation plan, not a trading strategy",
                    "A rejected null is not evidence of tradable profit",
                ],
            },
            model=DEMO_MODEL,
            prompt_version="research-validation-v1",
            created_at=_hours_ago(1),
        )
    )

    # Community shadow mode: untrusted, unverified, never part of the ranking.
    observation_text = (
        "In my own replication the published momentum spread mostly disappears once you "
        "use realised execution prices rather than quoted spreads, especially below a "
        "$300m market cap cut-off."
    )
    observation = CommunityObservation(
        source_provider="quant_stackexchange",
        source_tier="COMMUNITY",
        target_theme_id=themes["momentum"].id,
        target_paper_id=deep_paper.id,
        target_claim_id=claims[0].id,
        observation_type="REPLICATION_FAILURE",
        observation_text=observation_text,
        implementation_conditions="Requires realised execution data below $300m market cap.",
        author_name="demo_user",
        author_reputation=4210,
        votes=17,
        accepted_answer=True,
        source_url="https://quant.stackexchange.com/q/000000",
        captured_at=_hours_ago(5),
        content_hash=hashlib.sha256(observation_text.encode()).hexdigest(),
        code_links_json=[],
        data_links_json=[],
        verification_status="UNVERIFIED",
        independence_score=0.6,
        reproducibility_score=0.4,
        attack_dimension="COST",
        created_at=_hours_ago(5),
    )
    session.add(observation)
    session.flush()
    session.add(
        FalsificationTask(
            theme_id=themes["momentum"].id,
            claim_id=claims[0].id,
            observation_id=observation.id,
            question=(
                "Does the post-publication momentum spread remain indistinguishable from "
                "zero when realised execution prices replace quoted spreads?"
            ),
            attack_dimension="COST",
            required_data_json=["Realised execution prices", "Market cap breakpoints"],
            required_code_json=["Cost model swap harness"],
            required_checks_json=["Re-run the subsample split under both cost models"],
            status="PROPOSED",
            created_at=_hours_ago(5),
        )
    )

    run = PipelineRun(
        run_id="demo-run-0001",
        query="[DEMO] 8 scanned → 3 scout → 2 deep",
        run_type="DAILY_FUNNEL",
        status="COMPLETE",
        current_stage="RESEARCH_BRIEF",
        started_at=_hours_ago(6),
        ended_at=_hours_ago(5),
        discovered_count=8,
        deduplicated_count=8,
        fulltext_success_count=1,
        fulltext_failure_count=0,
        research_card_count=1,
        claim_count=3,
        question_count=1,
    )
    session.add(run)
    stage_results = [
        ("DISCOVERY", 8),
        ("RADAR", 8),
        ("SCOUT", 3),
        ("DEEP_SELECTION", 2),
        ("FULLTEXT", 1),
        ("RESEARCH_CARD", 1),
        ("CLAIM_EVIDENCE", 3),
        ("QUESTIONS", 1),
        ("RESEARCH_BRIEF", 1),
    ]
    for stage, created in stage_results:
        session.add(
            PipelineStageRun(
                run_id=run.run_id,
                stage=stage,
                status="SUCCESS",
                attempt_count=1,
                started_at=_hours_ago(6),
                ended_at=_hours_ago(5),
                metrics_json={"created": created},
                checkpoint_json={},
            )
        )

    session.flush()
    # Derive the theme aggregates with the production code path rather than
    # hardcoding them, so the demo cannot drift from how real runs count.
    RadarService(session).refresh_theme_counts(commit=False)

    session.commit()
    return {
        "themes": len(_THEMES),
        "papers": len(papers),
        "scout": 3,
        "deep": 2,
        "claims": len(claims),
        "questions": 1,
        "briefs": 1,
        "community_observations": 1,
    }
