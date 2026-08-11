from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.models import AbstractBrief, Paper, RadarAssessment, ResearchTheme
from app.radar import RadarService


def test_radar_archives_bulk_and_promotes_only_top_candidates() -> None:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Paper(
                    title="Momentum Decay after Publication",
                    normalized_title="momentum decay after publication",
                    abstract=(
                        "We provide out-of-sample replication evidence that momentum "
                        "declines after publication in United States equities."
                    ),
                    source="test",
                    research_scope="US_EQUITY_CORE",
                ),
                Paper(
                    title="Machine Learning Asset Pricing",
                    normalized_title="machine learning asset pricing",
                    abstract=(
                        "A machine learning study of United States equity returns with "
                        "out-of-sample tests and point-in-time predictors."
                    ),
                    source="test",
                    research_scope="US_EQUITY_CORE",
                ),
                Paper(
                    title="A General Finance Note",
                    normalized_title="a general finance note",
                    abstract="A short descriptive note without a new empirical test.",
                    source="test",
                    research_scope="US_EQUITY_AUXILIARY",
                ),
            ]
        )
        session.commit()

        rows = RadarService(session).assess(scout_limit=2)

        assert len(rows) == 3
        assert sum(row.decision == "SCOUT" for row in rows) == 2
        assert sum(row.decision == "ARCHIVED" for row in rows) == 1
        assert any(row.change_type == "CONFLICT" for row in rows)
        assert session.scalar(select(func.count()).select_from(ResearchTheme)) >= 2


def test_scout_prioritization_allows_zero_to_three_deep_items() -> None:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        paper = Paper(
            title="Momentum Replication Failure",
            normalized_title="momentum replication failure",
            abstract=(
                "An out-of-sample replication finds momentum decay in United States "
                "equities using point-in-time data."
            ),
            source="test",
            research_scope="US_EQUITY_CORE",
        )
        session.add(paper)
        session.commit()
        RadarService(session).assess(scout_limit=1)
        session.add(
            AbstractBrief(
                paper_id=paper.id,
                summary_zh="这是一项关于动量衰减的样本外复现研究，用于检验已有观点是否仍然成立。",
                core_principle_zh="论文检查公开发表后的动量收益是否因为拥挤或套利而持续衰减。",
                economic_mechanism_zh="策略拥挤可能压缩错误定价，也可能提高交易冲击与实施成本。",
                limitations_json=["仅摘要级判断"],
                reader_takeaway_zh="该论文可能改变动量持续有效的既有判断，值得进入证据级深度研究。",
                confidence=0.9,
                model="fixture",
                prompt_version="fixture",
            )
        )
        session.commit()

        selected = RadarService(session).prioritize(deep_limit=3)

        assert len(selected) == 1
        assert session.scalar(select(RadarAssessment.decision)) == "DEEP"
