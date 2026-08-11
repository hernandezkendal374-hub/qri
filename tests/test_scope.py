from app.scope.us_equity import (
    MANUAL_REVIEW,
    OUT_OF_SCOPE,
    US_EQUITY_AUXILIARY,
    US_EQUITY_CORE,
    classify_paper_scope,
)


def test_us_equity_factor_paper_enters_core_scope() -> None:
    decision = classify_paper_scope(
        "Momentum and the Cross-Section of US Stock Returns",
        "We test whether momentum predicts expected returns among NYSE and Nasdaq stocks.",
    )
    assert decision.scope == US_EQUITY_CORE


def test_pure_option_pricing_paper_is_out_of_scope() -> None:
    decision = classify_paper_scope(
        "A New Option Pricing Model",
        "We estimate an implied volatility surface for index options.",
    )
    assert decision.scope == OUT_OF_SCOPE


def test_option_signal_for_stock_returns_is_auxiliary() -> None:
    decision = classify_paper_scope(
        "Option Volume and Stock Returns",
        "We test whether option volume predicts the cross-section of stock returns.",
    )
    assert decision.scope == US_EQUITY_AUXILIARY


def test_implied_skewness_signal_for_stock_returns_is_auxiliary() -> None:
    decision = classify_paper_scope(
        "Market Skewness Risk and the Cross Section of Stock Returns",
        "Sensitivity to innovations in implied market skewness predicts stock returns.",
    )
    assert decision.scope == US_EQUITY_AUXILIARY


def test_other_country_equity_paper_is_out_of_scope() -> None:
    decision = classify_paper_scope(
        "Momentum in the China A-Share Market",
        "We study stock returns in the Chinese stock market.",
    )
    assert decision.scope == OUT_OF_SCOPE


def test_ambiguous_finance_paper_requires_manual_review() -> None:
    decision = classify_paper_scope(
        "Financial Intermediation and the Economy",
        "We present a theoretical model of financial intermediaries.",
    )
    assert decision.scope == MANUAL_REVIEW
