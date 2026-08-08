from app.core.config import Settings
from app.core.logging import redact_headers
from app.db.base import Base
from app.db.session import build_engine
from app.models import Paper  # noqa: F401 - imports all mapped entities
from app.schemas.research import PaperResearchCard


def test_schema_missing_fields_are_null() -> None:
    card = PaperResearchCard()
    assert card.market is None
    assert card.reported_alpha is None


def test_authorization_is_redacted() -> None:
    assert redact_headers({"Authorization": "Bearer secret", "Accept": "json"}) == {
        "Authorization": "[REDACTED]",
        "Accept": "json",
    }


def test_all_tables_create_in_sqlite() -> None:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    assert "papers" in Base.metadata.tables
    assert "research_questions" in Base.metadata.tables
    assert "ai_calls" in Base.metadata.tables


def test_settings_do_not_require_secrets() -> None:
    settings = Settings(_env_file=None)
    assert settings.primary_model == "claude-sonnet-4-6"
    assert settings.llm_api_key is None
