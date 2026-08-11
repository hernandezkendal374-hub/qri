from dataclasses import dataclass

from app.models import Paper

SCOPE_VERSION = "us-equity-scope-v2"
US_EQUITY_CORE = "US_EQUITY_CORE"
US_EQUITY_AUXILIARY = "US_EQUITY_AUXILIARY"
OUT_OF_SCOPE = "OUT_OF_SCOPE"
MANUAL_REVIEW = "MANUAL_REVIEW"
ELIGIBLE_SCOPES = (US_EQUITY_CORE, US_EQUITY_AUXILIARY)

EQUITY_TERMS = (
    "stock return",
    "stock returns",
    "equity return",
    "equity returns",
    "expected return",
    "expected returns",
    "cross-section of stocks",
    "cross section of stocks",
    "individual stocks",
    "common stocks",
    "equities",
    "stock market",
    "share returns",
)
US_MARKET_TERMS = (
    "u.s.",
    "us stock",
    "united states",
    "crsp",
    "nyse",
    "nasdaq",
    "amex",
    "american stock",
)
STRATEGY_TERMS = (
    "anomaly",
    "factor",
    "predict",
    "forecast",
    "alpha",
    "momentum",
    "reversal",
    "value premium",
    "profitability",
    "investment premium",
    "low volatility",
    "low beta",
    "liquidity",
    "short interest",
    "earnings announcement",
    "return premium",
    "asset pricing",
    "machine learning",
)
OPTION_TERMS = (
    "option pricing",
    "options pricing",
    "implied volatility",
    "volatility surface",
    "option market",
    "option volume",
    "option-implied",
    "implied skewness",
    "implied kurtosis",
    "implied market skewness",
    "implied market kurtosis",
)
NON_EQUITY_TERMS = (
    "foreign exchange",
    "currency market",
    "cryptocurrency",
    "crypto asset",
    "commodity futures",
    "fixed income",
    "sovereign bond",
    "corporate bond",
    "credit default swap",
    "interest rate derivative",
)
OTHER_REGION_TERMS = (
    "chinese stock",
    "china a-share",
    "a-share market",
    "european stock",
    "japanese stock",
    "indian stock",
    "emerging market equities",
)


@dataclass(frozen=True)
class ScopeDecision:
    scope: str
    reason: str
    confidence: float
    version: str = SCOPE_VERSION


def classify_paper_scope(title: str, abstract: str | None) -> ScopeDecision:
    text = f"{title}\n{abstract or ''}".casefold()
    has_equity_target = _contains(text, EQUITY_TERMS)
    has_us_market = _contains(text, US_MARKET_TERMS)
    has_strategy = _contains(text, STRATEGY_TERMS)
    has_options = _contains(text, OPTION_TERMS)
    has_non_equity = _contains(text, NON_EQUITY_TERMS)
    has_other_region = _contains(text, OTHER_REGION_TERMS)

    if has_other_region and not has_us_market:
        return ScopeDecision(
            OUT_OF_SCOPE,
            "研究对象明确是其他国家或地区股票市场，不进入美股核心漏斗。",
            0.94,
        )
    if has_options:
        if has_equity_target and has_strategy:
            return ScopeDecision(
                US_EQUITY_AUXILIARY,
                "期权数据用于解释或预测股票收益，作为美股辅助信号保留。",
                0.88,
            )
        return ScopeDecision(
            OUT_OF_SCOPE,
            "主题以期权定价或波动率曲面为主，未形成美股现货收益信号。",
            0.93,
        )
    if has_non_equity:
        if has_equity_target and has_strategy:
            return ScopeDecision(
                US_EQUITY_AUXILIARY,
                "非股票市场信息用于解释或预测股票收益，作为辅助信号保留。",
                0.82,
            )
        return ScopeDecision(
            OUT_OF_SCOPE,
            "研究对象主要是非股票资产，暂不进入美股策略漏斗。",
            0.91,
        )
    if has_equity_target and has_strategy:
        return ScopeDecision(
            US_EQUITY_CORE,
            "研究直接涉及股票收益、因子、异常或可检验的美股策略信号。",
            0.92 if has_us_market else 0.82,
        )
    if has_equity_target:
        return ScopeDecision(
            MANUAL_REVIEW,
            "涉及股票市场，但摘要未明确给出可检验的收益信号或策略问题。",
            0.66,
        )
    return ScopeDecision(
        MANUAL_REVIEW,
        "仅凭标题和摘要无法确认是否能转化为美股现货策略。",
        0.55,
    )


def apply_scope(paper: Paper) -> ScopeDecision:
    decision = classify_paper_scope(paper.title, paper.abstract)
    paper.research_scope = decision.scope
    paper.scope_reason = decision.reason
    paper.scope_confidence = decision.confidence
    paper.scope_version = decision.version
    return decision


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)
