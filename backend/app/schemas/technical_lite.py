from pydantic import BaseModel, Field

from app.schemas.common import Direction, TradeBias
from app.schemas.technical import ChartLevels, TradeSetup


class TradeSetupLite(BaseModel):
    bias: TradeBias
    entry_zone: list[float] = Field(default_factory=list)
    stop_loss: float | None = None
    take_profit: list[float] = Field(default_factory=list)
    risk_reward: float | None = None
    invalidation: str = ""
    invalidation_level: float | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.6)


class TechnicalAgentResponse(BaseModel):
    direction: Direction
    confidence: float = Field(ge=0.0, le=1.0)
    drivers: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    short_term_view: str | None = None
    long_term_view: str | None = None
    trade_setup: TradeSetupLite | None = None
    chart_levels: ChartLevels | None = None
