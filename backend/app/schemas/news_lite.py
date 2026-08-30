from pydantic import BaseModel, Field

from app.schemas.common import Direction, Importance


class NewsEventLite(BaseModel):
    title: str
    summary: str
    direction: Direction = "NEUTRAL"
    importance: Importance = "MEDIUM"
    event_type: str = "other_macro_event"
    actual: float | str | None = None
    forecast: float | str | None = None
    previous: float | str | None = None
    unit: str | None = None


class NewsAgentResponse(BaseModel):
    direction: Direction
    confidence: float = Field(ge=0.0, le=1.0)
    drivers: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    events: list[NewsEventLite] = Field(default_factory=list)
