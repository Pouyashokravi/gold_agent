from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.schemas.common import Direction, Evidence, Freshness, SpecialistOutput, TradeBias


class TradeSetup(BaseModel):
    bias: TradeBias
    entry_zone: list[float] = Field(default_factory=list)
    stop_loss: float | None = None
    take_profit: list[float] = Field(default_factory=list)
    risk_reward: float | None = None
    invalidation: str = ""
    invalidation_level: float | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class ChartLevels(BaseModel):
    trend: str = ""
    support_levels: list[float] = Field(default_factory=list)
    resistance_levels: list[float] = Field(default_factory=list)
    invalidation_level: float | None = None


class ChartAnnotations(BaseModel):
    levels: ChartLevels | None = None
    trade_setup: TradeSetup | None = None
    default_interval: str = "1h"


class ShortTermTechnicalOutput(BaseModel):
    direction: Direction
    confidence: float = Field(ge=0.0, le=1.0)
    trend: str = ""
    momentum: str = ""
    volatility: str = ""
    support_levels: list[float] = Field(default_factory=list)
    resistance_levels: list[float] = Field(default_factory=list)
    drivers: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    freshness: Freshness = "FRESH"
    trade_setup: TradeSetup | None = None


class LongTermTechnicalOutput(BaseModel):
    direction: Direction
    confidence: float = Field(ge=0.0, le=1.0)
    primary_trend: str = ""
    market_structure: str = ""
    major_support: list[float] = Field(default_factory=list)
    major_resistance: list[float] = Field(default_factory=list)
    drivers: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    freshness: Freshness = "FRESH"


class TechnicalAgentOutput(SpecialistOutput):
    short_term_view: str | None = None
    long_term_view: str | None = None
    trade_setup: TradeSetup | None = None
    chart_levels: ChartLevels | None = None
