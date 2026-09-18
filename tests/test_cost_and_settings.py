"""Cost accounting and settings that are read when they are used.

AICall.estimated_cost was hardcoded to None, so a system designed to process
300 papers a day had no way to see what it spent. FUNNEL_STAGES was built at
import time, so a threshold change in .env needed a process restart.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings, get_settings
from app.funnel.runner import funnel_stages
from app.providers.llm.audit import estimate_cost


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _configure(monkeypatch: pytest.MonkeyPatch, **values: object) -> None:
    settings = Settings(_env_file=None, **values)  # type: ignore[arg-type]
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)


def test_cost_is_unknown_rather_than_zero_when_no_price_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    monkeypatch.setattr("app.providers.llm.audit.get_settings", lambda: Settings(_env_file=None))
    assert estimate_cost(1000, 500) is None


def test_cost_is_priced_from_the_configured_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        _env_file=None,
        input_cost_per_million_tokens=3.0,
        output_cost_per_million_tokens=15.0,
    )
    monkeypatch.setattr("app.providers.llm.audit.get_settings", lambda: settings)
    # 1,000,000 in at 3.0 plus 200,000 out at 15.0 = 3.0 + 3.0
    assert estimate_cost(1_000_000, 200_000) == pytest.approx(6.0)


def test_missing_usage_is_unknown_not_free(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, input_cost_per_million_tokens=3.0)
    monkeypatch.setattr("app.providers.llm.audit.get_settings", lambda: settings)
    assert estimate_cost(None, None) is None
    # A gateway that reports only one side still prices what it did report.
    assert estimate_cost(1_000_000, None) == pytest.approx(3.0)


def test_funnel_stages_follow_the_current_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, daily_scan_target=42, deep_research_max_items=7)
    monkeypatch.setattr("app.funnel.runner.get_settings", lambda: settings)
    stages = dict((code, arguments) for code, _, arguments, _ in funnel_stages())
    assert stages["DISCOVERY"] == ("daily", "--target", "42")
    assert stages["FULLTEXT"] == ("fetch", "--top", "7")


def test_funnel_stages_reflect_a_later_change_without_a_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = Settings(_env_file=None, daily_scan_target=10)
    monkeypatch.setattr("app.funnel.runner.get_settings", lambda: first)
    assert funnel_stages()[0][2] == ("daily", "--target", "10")

    second = Settings(_env_file=None, daily_scan_target=300)
    monkeypatch.setattr("app.funnel.runner.get_settings", lambda: second)
    assert funnel_stages()[0][2] == ("daily", "--target", "300")
