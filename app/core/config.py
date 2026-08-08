from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./qri.db"
    llm_base_url: str = ""
    llm_api_key: SecretStr | None = None
    primary_model: str = "claude-sonnet-4-6"
    reasoning_model: str = "gpt-5.4"
    semantic_scholar_api_key: SecretStr | None = None
    unpaywall_email: str | None = None
    http_timeout_seconds: float = 20.0
    http_max_retries: int = 3
    qri_log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
