import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.session import build_engine
from app.main import create_app
from app.models import AICall, ResearchQuestion, ResearchValidationSpec
from app.providers.llm.fixture import FixtureLLMProvider
from app.research_validation import ResearchValidationService


def validation_spec() -> dict:
    variable = {
        "name": "未来一个月股票收益",
        "role": "DEPENDENT",
        "academic_definition": "股票在 t+1 月的含退市收益",
        "measurement": "月度总收益率",
        "timing_rule": "所有解释变量在 t 月末可得",
        "source_requirement": "PIT 行情与退市数据",
    }
    independent = dict(variable, name="中介资本冲击", role="INDEPENDENT")
    control = dict(variable, name="市值", role="CONTROL")
    return {
        "plain_language_question": "机构资金紧张时，冷门股票是否更容易受到价格冲击？",
        "academic_question": (
            "在美股横截面中，中介资本冲击与投资者知晓度的交互项能否显著解释未来股票收益？"
        ),
        "research_object": "美股横截面中的中介资本约束与投资者知晓度",
        "economic_mechanism": "资本受限的中介机构优先出售难以被其他投资者承接的股票。",
        "counter_mechanism": "结果可能只是流动性或微盘股暴露的代理。",
        "dependent_variable": variable,
        "independent_variables": [independent],
        "interaction_terms": [],
        "control_variables": [control],
        "sample_design": ["美国普通股月度横截面"],
        "point_in_time_requirements": ["使用当时可得的股票池和变量"],
        "statistical_tests": ["Fama-MacBeth 回归与双向聚类标准误"],
        "out_of_sample_design": ["按时间切分训练期和验证期"],
        "falsification_conditions": ["控制流动性后交互项消失"],
        "minimum_data_requirements": ["含退市收益的 PIT 行情"],
        "bias_risks": ["幸存者偏差", "未来数据污染"],
        "implementation_sensitivities": ["微盘股与做空可得性"],
        "success_criteria": ["方向、显著性、经济意义和样本外稳定性一致"],
        "human_review_questions": ["知晓度代理是否有前视信息？"],
        "prohibited_interpretations": ["统计显著不等于可交易策略"],
    }


@pytest.mark.asyncio
async def test_validation_spec_persists_dual_wording_and_audit() -> None:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        question = ResearchQuestion(
            question_uid="RQ-VALIDATION-0001",
            family="intermediary-capital",
            question="旧问题文本",
            economic_mechanism="机制",
            counter_mechanism="反机制",
            supporting_claims_json=[],
            required_data_json=["PIT 行情"],
            known_risks_json=["幸存者偏差"],
        )
        session.add(question)
        session.commit()

        row = await ResearchValidationService(
            session,
            FixtureLLMProvider([json.dumps(validation_spec(), ensure_ascii=False)]),
            "claude-sonnet-4-6",
        ).generate(question, {"question": {"id": question.id}})

        assert row.review_status == "DRAFT"
        assert question.plain_language_question.startswith("机构资金紧张")
        assert question.academic_question.startswith("在美股横截面")
        assert question.question == question.academic_question
        assert session.scalar(select(func.count()).select_from(ResearchValidationSpec)) == 1
        assert session.scalar(select(func.count()).select_from(AICall)) == 1


def test_validation_schema_contains_no_portfolio_or_backtest_fields() -> None:
    keys = set(validation_spec())
    assert not keys.intersection(
        {"portfolio", "positions", "weights", "backtest", "sharpe", "max_drawdown"}
    )


@pytest.mark.asyncio
async def test_research_brief_has_one_exit_decision_gate(tmp_path: Path) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'gate.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        question = ResearchQuestion(
            question_uid="RQ-GATE-0001",
            family="gate",
            question="一个达到深研出口的问题",
            plain_language_question="机构压力会放大冷门股票的价格冲击吗？",
            academic_question="中介资本压力与知晓度交互项能否解释未来收益？",
            economic_mechanism="机制",
            counter_mechanism="反机制",
            supporting_claims_json=[],
            required_data_json=[],
            known_risks_json=[],
        )
        session.add(question)
        session.flush()
        session.add(
            ResearchValidationSpec(
                question_id=question.id,
                review_status="DRAFT",
                specification_json=validation_spec(),
                model="fixture",
                prompt_version="fixture",
            )
        )
        session.commit()
        question_id = question.id

    app = create_app(factory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/questions/{question_id}/decision/defer", follow_redirects=False
        )
        assert response.status_code == 303

    with factory() as session:
        question = session.get(ResearchQuestion, question_id)
        spec = session.scalar(
            select(ResearchValidationSpec).where(ResearchValidationSpec.question_id == question_id)
        )
        assert question.status.value == "DEFERRED"
        assert spec.review_status == "DEFERRED"
