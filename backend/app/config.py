from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
_env_candidates = [ROOT_DIR / ".env", Path(".env"), Path("../.env")]
_existing = [str(p) for p in _env_candidates if p.exists()]

# Defaults — overridable via env; never hardcode model IDs in agent modules.
DEFAULT_FAST_MODEL = "gpt-5.4-nano"
DEFAULT_MANAGER_MODEL = "gpt-5.4"
DEFAULT_SPECIALIST_MODEL = "gpt-5.4-mini"


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

    # Primary model settings
    fast_model: str = DEFAULT_FAST_MODEL
    manager_model: str = DEFAULT_MANAGER_MODEL
    news_model: str = ""
    fundamental_model: str = ""
    technical_model: str = ""
    # Shared specialist fallback (NEWS/FUNDAMENTAL/TECHNICAL inherit when unset)
    specialist_model: str = DEFAULT_SPECIALIST_MODEL

    # Legacy env compatibility
    query_model: str = Field(default="")
    planner_model: str = Field(default="")
    synthesis_model: str = Field(default="")
    answer_model: str = Field(default="")

    cors_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:3001,http://127.0.0.1:3001"
    )

    tavily_enabled: bool = True
    tavily_monthly_budget: int = 900
    tavily_search_depth: str = "basic"
    tavily_max_results: int = 8
    mock_external_apis: bool = False

    twelve_data_timeout: float = 8.0
    fred_timeout: float = 8.0
    tavily_timeout: float = 15.0
    llm_timeout: float = 90.0

    cache_quote_ttl: int = 15
    cache_ohlc_1m_ttl: int = 60
    cache_ohlc_15m_ttl: int = 300
    cache_ohlc_daily_ttl: int = 1800
    cache_fred_ttl: int = 3600
    cache_tavily_ttl: int = 1200

    # Conversation Gate / Summarizer (optional overrides → fast_model)
    conversation_gate_model: str = ""
    conversation_summary_model: str = ""
    recent_messages_limit: int = 20
    conversation_summary_batch_size: int = 20
    max_clarification_turns: int = 3
    conversation_gate_max_retries: int = 1

    max_replan_rounds: int = 2
    session_history_limit: int = 20

    @field_validator(
        "openai_api_key",
        "twelve_data_api_key",
        "fred_api_key",
        "tavily_api_key",
    )
    @classmethod
    def strip_secrets(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def resolve_model_aliases(self) -> "Settings":
        # Per-domain specialists fall back to SPECIALIST_MODEL when unset.
        news = self.news_model or self.specialist_model
        fund = self.fundamental_model or self.specialist_model
        tech = self.technical_model or self.specialist_model
        object.__setattr__(self, "news_model", news)
        object.__setattr__(self, "fundamental_model", fund)
        object.__setattr__(self, "technical_model", tech)

        # Legacy aliases → primary roles when primary still at defaults and legacy is set.
        if self.query_model and self.fast_model == DEFAULT_FAST_MODEL and self.query_model != self.fast_model:
            object.__setattr__(self, "fast_model", self.query_model)
        if self.planner_model and self.manager_model == DEFAULT_MANAGER_MODEL and self.planner_model != self.manager_model:
            object.__setattr__(self, "manager_model", self.planner_model)

        # Populate legacy fields for any remaining consumers.
        object.__setattr__(self, "query_model", self.query_model or self.fast_model)
        object.__setattr__(self, "planner_model", self.planner_model or self.manager_model)
        object.__setattr__(self, "synthesis_model", self.synthesis_model or self.manager_model)
        object.__setattr__(self, "answer_model", self.answer_model or self.fast_model)

        gate_model = self.conversation_gate_model or self.fast_model
        summary_model = self.conversation_summary_model or self.fast_model
        object.__setattr__(self, "conversation_gate_model", gate_model)
        object.__setattr__(self, "conversation_summary_model", summary_model)
        return self


settings = Settings()
