from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./qri.db"
    llm_base_url: str = ""
    llm_api_key: SecretStr | None = None
    primary_model: str = "claude-sonnet-4-6"
    reasoning_model: str = "claude-sonnet-4-6"
    validation_model: str = "claude-sonnet-4-6"
    # Incremental-value funnel controls.  They are thresholds with safety caps,
    # never promises to fill a quota.
    scout_score_threshold: float = 0.48
    scout_max_items: int = 30
    deep_research_threshold: float = 0.62
    deep_research_max_items: int = 5
    daily_scan_target: int = 300
    community_shadow_enabled: bool = True
    stackexchange_api_key: SecretStr | None = None
    # Legacy only: retained so archived strategy records remain readable.
    strategy_model: str = "gpt-5.6-sol"
    semantic_scholar_api_key: SecretStr | None = None
    openalex_api_key: SecretStr | None = None
    unpaywall_email: str | None = None
    http_timeout_seconds: float = 20.0
    http_max_retries: int = 3
    qri_log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
