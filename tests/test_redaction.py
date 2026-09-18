"""Secrets must not reach the database or the dashboard.

execute_funnel captures each stage's stdout and stderr and stores the tail of
it on PipelineStageRun, which the dashboard renders. httpx puts the full
request URL into HTTPStatusError, and the Stack Exchange API takes its key as
a query parameter, so a single failed request used to be enough to persist the
key and display it on a web page.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.core.redaction import REDACTED, redact_secrets


def _settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_a_configured_key_is_removed_wherever_it_appears() -> None:
    settings = _settings(stackexchange_api_key="rl_LIVEKEYVALUE123456")
    text = "GET https://api.stackexchange.com/2.3/search?site=quant&key=rl_LIVEKEYVALUE123456"
    cleaned = redact_secrets(text, settings)
    assert "rl_LIVEKEYVALUE123456" not in cleaned
    assert REDACTED in cleaned


def test_the_real_httpx_error_text_is_scrubbed() -> None:
    """The exact leak path: httpx renders the whole URL into its error."""
    settings = _settings(stackexchange_api_key="rl_LIVEKEYVALUE123456")
    request = httpx.Request(
        "GET",
        "https://api.stackexchange.com/2.3/search/advanced"
        "?site=quant&key=rl_LIVEKEYVALUE123456",
    )
    try:
        httpx.Response(400, request=request).raise_for_status()
    except httpx.HTTPStatusError as exc:
        message = str(exc)
    assert "rl_LIVEKEYVALUE123456" in message, "precondition: httpx leaks the key"
    assert "rl_LIVEKEYVALUE123456" not in redact_secrets(message, settings)


def test_secret_shaped_values_are_removed_even_when_not_configured() -> None:
    """A subprocess can print a credential this process never held."""
    settings = _settings()
    samples = {
        "url key": "https://api.example.com/v1?api_key=abcdef123456789",
        "db password": "postgresql+psycopg://qri:s3cr3tpassword@db:5432/qri",
        "bearer": "Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz012345",
        "openai": "using sk-abcdefghijklmnopqrstuvwxyz012345 now",
        "github": "token ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "aws": "AKIAIOSFODNN7EXAMPLE was used",
    }
    for label, text in samples.items():
        cleaned = redact_secrets(text, settings)
        assert REDACTED in cleaned, label
    assert "s3cr3tpassword" not in redact_secrets(samples["db password"], settings)
    assert "abcdef123456789" not in redact_secrets(samples["url key"], settings)


def test_ordinary_output_is_left_alone() -> None:
    settings = _settings()
    text = "DISCOVERY created 12 papers in 4.2s; radar archived 8 as LOW_INCREMENTAL_VALUE"
    assert redact_secrets(text, settings) == text


def test_empty_input_is_handled() -> None:
    assert redact_secrets(None, _settings()) == ""
    assert redact_secrets("", _settings()) == ""


def test_short_configured_values_are_not_used_as_patterns() -> None:
    """A tiny key would otherwise rewrite unrelated text."""
    settings = _settings(llm_api_key="abc")
    assert redact_secrets("abcdefg is a normal word here", settings) == (
        "abcdefg is a normal word here"
    )


@pytest.mark.parametrize("status", ["SUCCESS", "FAILED"])
def test_stage_output_is_redacted_before_it_is_stored(tmp_path, monkeypatch, status) -> None:
    from sqlalchemy.orm import Session, sessionmaker

    from app.db.base import Base
    from app.db.session import build_engine
    from app.funnel import runner
    from app.models import PipelineRun, PipelineStageRun

    settings = _settings(stackexchange_api_key="rl_LIVEKEYVALUE123456")
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr("app.core.redaction.get_settings", lambda: settings)

    engine = build_engine(f"sqlite:///{tmp_path / 'funnel.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with factory() as session:
        session.add(PipelineRun(run_id="r1", query="test", run_type="DAILY_FUNNEL"))
        session.add(PipelineStageRun(run_id="r1", stage="DISCOVERY", status="PENDING"))
        session.commit()

    leaky = (
        "Traceback (most recent call last):\n"
        "httpx.HTTPStatusError: Client error '400 Bad Request' for url "
        "'https://api.stackexchange.com/2.3/search?site=quant&key=rl_LIVEKEYVALUE123456'"
    )
    runner._mark_stage_finished(factory, "r1", "DISCOVERY", status, 0, leaky, 1)

    with factory() as session:
        stage = session.query(PipelineStageRun).one()
        stored = repr(stage.checkpoint_json) + repr(stage.error_json)
    assert "rl_LIVEKEYVALUE123456" not in stored
    assert REDACTED in stored
