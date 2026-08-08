from pydantic import BaseModel, ConfigDict


class PaperResearchCard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    market: str | None = None
    asset_class: str | None = None
    universe: str | None = None
    sample_start: str | None = None
    sample_end: str | None = None
    hypothesis: str | None = None
    mechanism: str | None = None
    counter_mechanism: str | None = None
    signal_definition: str | None = None
    formation_period: str | None = None
    holding_period: str | None = None
    rebalance_frequency: str | None = None
    portfolio_construction: str | None = None
    benchmark: str | None = None
    reported_return: str | None = None
    reported_alpha: str | None = None
    reported_sharpe: str | None = None
    reported_max_drawdown: str | None = None
    transaction_cost_handling: str | None = None
    survivorship_handling: str | None = None
    lookahead_handling: str | None = None
    in_sample: str | None = None
    out_of_sample: str | None = None
    robustness_tests: list[str] = []
    required_data: list[str] = []
    limitations: list[str] = []
