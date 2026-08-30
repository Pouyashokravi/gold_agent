from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
_env_candidates = [ROOT_DIR / ".env", Path(".env"), Path("../.env")]
_existing = [str(p) for p in _env_candidates if p.exists()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_existing or [".env"],
        extra="ignore",
    )

    openai_api_key: str = ""
    twelve_data_api_key: str = ""
    fred_api_key: str = ""
    tavily_api_key: str = ""
    database_url: str = "sqlite:///./gold_agent.db"

    query_model: str = "gpt-4.1-nano"
    planner_model: str = "gpt-4.1-mini"
    specialist_model: str = "gpt-4.1-mini"
    synthesis_model: str = "gpt-4.1-mini"
    answer_model: str = "gpt-4.1-nano"

    cors_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:3001,http://127.0.0.1:3001"
    )

    tavily_enabled: bool = True
    tavily_monthly_budget: int = 900
    tavily_search_depth: str = "basic"
    tavily_max_results: int = 8
    mock_external_apis: bool = False

    # Timeouts (seconds)
    twelve_data_timeout: float = 8.0
    fred_timeout: float = 8.0
    tavily_timeout: float = 15.0
    llm_timeout: float = 60.0

    # Cache TTLs (seconds)
    cache_quote_ttl: int = 15
    cache_ohlc_1m_ttl: int = 60
    cache_ohlc_15m_ttl: int = 300
    cache_ohlc_daily_ttl: int = 1800
    cache_fred_ttl: int = 3600
    cache_tavily_ttl: int = 1200

    @field_validator(
        "openai_api_key",
        "twelve_data_api_key",
        "fred_api_key",
        "tavily_api_key",
    )
    @classmethod
    def strip_secrets(cls, value: str) -> str:
        return value.strip()


settings = Settings()
