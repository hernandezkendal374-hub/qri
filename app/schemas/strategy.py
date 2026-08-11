from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UniverseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    market: str = Field(min_length=1)
    security_types: list[str] = Field(min_length=1)
    inclusion_rules: list[str] = Field(min_length=1)
    exclusion_rules: list[str] = Field(min_length=1)
    point_in_time_requirements: list[str] = Field(min_length=1)


class VariableSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    role: Literal["SIGNAL", "TARGET", "CONTROL", "COST", "RISK", "FILTER"]
    definition: str = Field(min_length=1)
    timing_lag: str = Field(min_length=1)
    source_requirement: str = Field(min_length=1)


class SignalSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    formula_description: str = Field(min_length=1)
    direction: str = Field(min_length=1)
    formation_window: str = Field(min_length=1)
    ranking_method: str = Field(min_length=1)
    missing_data_rule: str = Field(min_length=1)


class PortfolioSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    construction: str = Field(min_length=1)
    long_leg: str = Field(min_length=1)
    short_leg: str = Field(min_length=1)
    weighting: str = Field(min_length=1)
    rebalance_frequency: str = Field(min_length=1)
    constraints: list[str] = Field(min_length=1)


class BacktestSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    in_sample_period: str = Field(min_length=1)
    validation_period: str = Field(min_length=1)
    out_of_sample_period: str = Field(min_length=1)
    benchmarks: list[str] = Field(min_length=1)
    statistical_tests: list[str] = Field(min_length=1)
    robustness_tests: list[str] = Field(min_length=1)


class AcceptanceGate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: str = Field(min_length=1)
    pass_condition: str = Field(min_length=1)
    failure_condition: str = Field(min_length=1)


class DatasetRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset: str = Field(min_length=1)
    fields: list[str] = Field(min_length=1)
    point_in_time: bool
    availability: Literal["MISSING", "PARTIAL", "AVAILABLE"]


class StrategyParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    source: Literal["PAPER_EVIDENCE", "QRI_RESEARCH_DEFAULT"]
    rationale: str = Field(min_length=1)


class ExecutableStrategySpec(BaseModel):
    """A complete, code-ready first-pass strategy, even before data is connected."""

    model_config = ConfigDict(extra="forbid")
    strategy_name: str = Field(min_length=1)
    strategy_type: str = Field(min_length=1)
    implementation_status: Literal["BACKTEST_SPEC_READY", "RESEARCH_ONLY", "REJECTED"]
    one_sentence_rule: str = Field(min_length=1)
    universe_query: str = Field(min_length=1)
    signal_formula: str = Field(min_length=1)
    signal_calculation_steps: list[str] = Field(min_length=1)
    long_entry_rule: str = Field(min_length=1)
    short_entry_rule: str = Field(min_length=1)
    exit_rule: str = Field(min_length=1)
    formation_window: str = Field(min_length=1)
    holding_period: str = Field(min_length=1)
    rebalance_rule: str = Field(min_length=1)
    weighting_rule: str = Field(min_length=1)
    gross_leverage: str = Field(min_length=1)
    net_exposure: str = Field(min_length=1)
    position_limit: str = Field(min_length=1)
    neutralization: list[str] = Field(min_length=1)
    borrow_rule: str = Field(min_length=1)
    execution_timing: str = Field(min_length=1)
    cost_assumptions: list[str] = Field(min_length=1)
    risk_rules: list[str] = Field(min_length=1)
    parameters: list[StrategyParameter] = Field(min_length=1)
    implementation_pseudocode: list[str] = Field(min_length=1)


class StrategyIncubationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    research_classification: Literal[
        "TESTABLE_STRATEGY_CANDIDATE", "EMPIRICAL_ONLY", "NOT_CURRENTLY_TESTABLE"
    ]
    readiness_status: Literal["WAITING_FOR_DATA", "READY_FOR_BACKTEST", "REJECTED"]
    strategy_thesis: str = Field(min_length=1)
    executable_strategy: ExecutableStrategySpec
    null_hypothesis: str = Field(min_length=1)
    alternative_hypothesis: str = Field(min_length=1)
    testable_predictions: list[str] = Field(min_length=1)
    universe: UniverseSpec
    variables: list[VariableSpec] = Field(min_length=1)
    signal: SignalSpec
    portfolio: PortfolioSpec
    cost_model: list[str] = Field(min_length=1)
    backtest: BacktestSpec
    acceptance_gates: list[AcceptanceGate] = Field(min_length=1)
    risk_controls: list[str] = Field(min_length=1)
    required_datasets: list[DatasetRequirement] = Field(min_length=1)
    blockers: list[str]
    human_review_checkpoints: list[str] = Field(min_length=1)
    prohibited_actions: list[str] = Field(min_length=1)
