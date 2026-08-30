from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import Direction, Freshness, Horizon, Importance, SpecialistOutput


class NewsEvent(BaseModel):
    event_id: str
    event_type: str
    title: str
    summary: str
    event_time: datetime | None = None
    importance: Importance
    gold_relevance: float = Field(ge=0.0, le=1.0)
    impact_score: float = Field(ge=0.0, le=1.0)
    direction: Direction
    mechanism: list[str] = Field(default_factory=list)
    impact_by_horizon: dict[str, float] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    source_ids: list[str] = Field(default_factory=list)
    actual: float | str | None = None
    forecast: float | str | None = None
    previous: float | str | None = None
    unit: str | None = None
    surprise_measurable: bool = False
    surprise_delta: float | None = None
    surprise_magnitude: str | None = None
    surprise_interpretation: str | None = None
    surprise_gold_bias: Direction | None = None


class NewsAgentOutput(SpecialistOutput):
    events: list[NewsEvent] = Field(default_factory=list)
