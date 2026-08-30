from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Horizon(str, Enum):
    INTRADAY = "intraday"
    FEW_DAYS = "few_days"
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"
    AGES = "ages"


class Intent(str, Enum):
    MARKET_OUTLOOK = "market_outlook"
    TECHNICAL_ANALYSIS = "technical_analysis"
    FUNDAMENTAL_ANALYSIS = "fundamental_analysis"
    NEWS_ANALYSIS = "news_analysis"
    EVENT_IMPACT = "event_impact"
    MARKET_MOVE_EXPLANATION = "market_move_explanation"
    TRADE_ANALYSIS = "trade_analysis"
    PRICE_QUERY = "price_query"
    HISTORICAL_ANALYSIS = "historical_analysis"


class ResearchDepth(str, Enum):
    LIGHT = "LIGHT"
    STANDARD = "STANDARD"
    DEEP = "DEEP"


Direction = Literal["BULLISH", "BEARISH", "NEUTRAL", "MIXED"]
Freshness = Literal["FRESH", "ACCEPTABLE", "STALE"]
AgentDepth = Literal["OFF", "LIGHT", "STANDARD", "DEEP"]
ExecutionMode = Literal["PARALLEL", "SEQUENTIAL"]
Provider = Literal["TWELVE_DATA", "FRED", "TAVILY"]
EvidenceType = Literal[
    "news_event",
    "macro_data",
    "market_data",
    "technical_signal",
    "technical_level",
    "flow_data",
]
Importance = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
TradeBias = Literal["LONG", "SHORT", "NO_TRADE"]


class Source(BaseModel):
    source_id: str
    provider: Provider
    title: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    quality_score: float = Field(ge=0.0, le=1.0)


class Evidence(BaseModel):
    evidence_id: str
    type: EvidenceType
    claim: str
    direction: Direction
    strength: float = Field(ge=0.0, le=1.0)
    relevance: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: datetime
    freshness: Freshness
    source_ids: list[str] = Field(default_factory=list)


class CoverageReport(BaseModel):
    required: int
    available: int
    coverage_score: float = Field(ge=0.0, le=1.0)


class SpecialistOutput(BaseModel):
    direction: Direction
    confidence: float = Field(ge=0.0, le=1.0)
    horizon: Horizon
    drivers: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    timestamp: datetime
    freshness: Freshness
    coverage: CoverageReport | None = None
