import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.models import AICall, ResearchQuestion, StrategyIncubation
from app.providers.llm.fixture import FixtureLLMProvider
from app.strategy.quick_backtest import (
    _metrics,
    _month_ends,
    evaluate_quick_result,
    infer_strategy_profile,
)
from app.strategy.service import StrategyIncubationService


def strategy_spec() -> dict:
    return {
        "research_classification": "TESTABLE_STRATEGY_CANDIDATE",
        "readiness_status": "WAITING_FOR_DATA",
        "strategy_thesis": "仅在数据和样本外门槛通过后考虑策略化。",
        "executable_strategy": {
            "strategy_name": "约束分层异常多空",
            "strategy_type": "美股市场中性截面多空",
            "implementation_status": "BACKTEST_SPEC_READY",
            "one_sentence_rule": "做多高约束组高信号股票，做空低信号股票。",
            "universe_query": "美国普通股，价格大于5美元，过去20日成交额中位数大于1000万美元。",
            "signal_formula": "score = z(anomaly_signal)",
            "signal_calculation_steps": ["使用收盘后可得数据计算异常信号", "行业内标准化并排序"],
            "long_entry_rule": "买入信号最高20%的可借券股票",
            "short_entry_rule": "卖空信号最低20%的可借券股票",
            "exit_rule": "下次月度调仓时退出不再入选的股票",
            "formation_window": "月末使用截至当日收盘可得数据",
            "holding_period": "1个月",
            "rebalance_rule": "每月最后一个交易日计算，下一交易日开盘成交",
            "weighting_rule": "多空两侧分别等权",
            "gross_leverage": "100%（多头50%、空头50%）",
            "net_exposure": "0%",
            "position_limit": "单股绝对权重不超过2%",
            "neutralization": ["行业中性", "多空美元中性"],
            "borrow_rule": "无借券或借券费缺失的股票不得进入空头",
            "execution_timing": "信号形成后的下一交易日开盘",
            "cost_assumptions": ["双边10个基点", "空头另计实际借券费"],
            "risk_rules": ["单一行业净敞口不超过5%", "年化波动目标10%"],
            "parameters": [{
                "name": "分位数阈值", "value": "20%", "source": "QRI_RESEARCH_DEFAULT",
                "rationale": "常见截面回测起点，后续只做预注册稳健性检验"
            }],
            "implementation_pseudocode": [
                "筛选股票池",
                "计算信号",
                "构建多空组合",
                "应用成本并记录收益",
            ],
        },
        "null_hypothesis": "扣除成本后收益不显著。",
        "alternative_hypothesis": "扣除成本后样本外收益显著为正。",
        "testable_predictions": ["高约束组的净收益更高。"],
        "universe": {
            "market": "美国股票",
            "security_types": ["普通股"],
            "inclusion_rules": ["使用时点股票池"],
            "exclusion_rules": ["排除数据缺失记录"],
            "point_in_time_requirements": ["包含退市股票"],
        },
        "variables": [
            {
                "name": "signal",
                "role": "SIGNAL",
                "definition": "按月计算并截面排序",
                "timing_lag": "至少滞后一个交易日",
                "source_requirement": "时点数据",
            }
        ],
        "signal": {
            "formula_description": "信号截面标准化后排序",
            "direction": "高分做多、低分做空",
            "formation_window": "月末",
            "ranking_method": "分位数组合",
            "missing_data_rule": "缺失时不持仓",
        },
        "portfolio": {
            "construction": "市场中性多空组合",
            "long_leg": "最高分位",
            "short_leg": "最低分位",
            "weighting": "等权",
            "rebalance_frequency": "每月",
            "constraints": ["限制单股权重"],
        },
        "cost_model": ["价差、冲击、佣金、换手和借券成本"],
        "backtest": {
            "in_sample_period": "预注册后确定",
            "validation_period": "预注册后确定",
            "out_of_sample_period": "最后一段时间外样本",
            "benchmarks": ["市场和因子基准"],
            "statistical_tests": ["Newey-West t 检验"],
            "robustness_tests": ["参数和子样本稳定性"],
        },
        "acceptance_gates": [
            {
                "metric": "样本外净收益",
                "pass_condition": "预设显著性和经济门槛均通过",
                "failure_condition": "任一门槛未通过",
            }
        ],
        "risk_controls": ["回撤和容量限制"],
        "required_datasets": [
            {
                "dataset": "时点行情",
                "fields": ["复权价格", "退市收益"],
                "point_in_time": True,
                "availability": "MISSING",
            }
        ],
        "blockers": ["尚未连接研究数据"],
        "human_review_checkpoints": ["审核变量与门槛"],
        "prohibited_actions": ["禁止实盘下单"],
    }


@pytest.mark.asyncio
async def test_strategy_incubation_persists_waiting_specification() -> None:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        question = ResearchQuestion(
            question_uid="RQ-TEST-0001",
            family="test",
            question="一个可以被严格证伪的量化研究问题是否在成本后成立？",
            economic_mechanism="机制",
            counter_mechanism="反向机制",
            supporting_claims_json=[1],
            required_data_json=["行情"],
            known_risks_json=["前视偏差"],
        )
        session.add(question)
        session.commit()
        incubation = await StrategyIncubationService(
            session,
            FixtureLLMProvider([json.dumps(strategy_spec(), ensure_ascii=False)]),
            "gpt-5.4",
        ).generate(question, {"question": {"id": question.id}})
        assert incubation.readiness_status == "WAITING_FOR_DATA"
        assert incubation.specification_json["acceptance_gates"]
        assert session.scalar(select(func.count()).select_from(StrategyIncubation)) == 1
        assert session.scalar(select(func.count()).select_from(AICall)) == 1


def test_quick_backtest_helpers_produce_month_ends_and_metrics() -> None:
    assert _month_ends(["2026-01-02", "2026-01-30", "2026-02-02"]) == [
        "2026-01-30",
        "2026-02-02",
    ]
    curve = [
        {"date": "2026-01-02", "strategy": 1.0},
        {"date": "2026-01-05", "strategy": -1.0},
    ]
    metrics = _metrics([0.01, -0.01980198], curve, 0.001)
    assert metrics["total_return"] == -1.0
    assert metrics["max_drawdown"] < 0


def test_quick_backtest_evaluation_flags_weak_risk_adjusted_result() -> None:
    result = {
        "metrics": {
            "total_return": 20.96,
            "annual_return": 4.98,
            "sharpe": 0.38,
            "max_drawdown": -37.17,
            "estimated_cost": 2.15,
        },
        "equity_curve": [{"benchmark": 71.2}],
    }
    evaluation = evaluate_quick_result(result)
    assert evaluation["verdict"] == "暂不通过，建议重构"
    assert evaluation["tone"] == "warning"


def test_proxy_backtest_never_becomes_a_ranking_verdict() -> None:
    result = {
        "metrics": {
            "total_return": 30.0,
            "annual_return": 12.0,
            "sharpe": 1.2,
            "max_drawdown": -10.0,
            "estimated_cost": 2.0,
        },
        "equity_curve": [{"benchmark": 20.0}],
        "coverage": {"eligible_for_ranking": False},
    }
    evaluation = evaluate_quick_result(result)
    assert evaluation["verdict"] == "代理回测，仅供方向检查"
    assert evaluation["tone"] == "proxy"


def test_backtest_profile_is_inferred_from_research_question() -> None:
    assert infer_strategy_profile("Does the low-volatility anomaly persist?") == "low_volatility"
    assert infer_strategy_profile("Does the low-beta anomaly persist?") == "low_volatility"
    assert infer_strategy_profile("Do momentum returns persist?") == "momentum"
    assert infer_strategy_profile("Does momentum survive after borrowing fees?") is None
    assert infer_strategy_profile("Low volatility under institutional constraints") is None
    assert infer_strategy_profile("Cross-asset residual reversal") == "cross_asset_etf"
    assert infer_strategy_profile("Does intermediary capital affect expected returns?") is None
