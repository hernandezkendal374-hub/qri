from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./qri.db"
    llm_base_url: str = ""
    llm_api_key: SecretStr | None = None
    # Any model id your OpenAI-compatible gateway exposes. The defaults are
    # only a starting point; QRI is not tied to a particular vendor.
    primary_model: str = "claude-sonnet-5"
    reasoning_model: str = "claude-sonnet-5"
    validation_model: str = "claude-sonnet-5"
    # Incremental-value funnel controls.  They are thresholds with safety caps,
    # never promises to fill a quota.
    scout_score_threshold: float = 0.48
    scout_max_items: int = 30
    deep_research_threshold: float = 0.62
    deep_research_max_items: int = 5
    daily_scan_target: int = 300
    community_shadow_enabled: bool = True
    stackexchange_api_key: SecretStr | None = None
    # Cost accounting for the AICall audit trail, in currency units per million
    # tokens. Prices differ per vendor, model and contract, so QRI does not ship
    # a built-in price table it would only get wrong -- set these to match your
    # own gateway. Left at zero, calls are still audited with a null cost.
    input_cost_per_million_tokens: float = 0.0
    output_cost_per_million_tokens: float = 0.0
    semantic_scholar_api_key: SecretStr | None = None
    openalex_api_key: SecretStr | None = None
    unpaywall_email: str | None = None
    http_timeout_seconds: float = 20.0
    http_max_retries: int = 3
    qri_log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
