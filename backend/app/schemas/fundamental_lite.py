from pydantic import BaseModel, Field

from app.schemas.common import Direction, Importance


class FundamentalDriverLite(BaseModel):
    name: str
    current_state: str
    direction_for_gold: Direction
    importance: Importance = "MEDIUM"
    confidence: float = Field(ge=0.0, le=1.0, default=0.6)


class FundamentalAgentResponse(BaseModel):
    direction: Direction
    confidence: float = Field(ge=0.0, le=1.0)
    drivers: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    fundamental_drivers: list[FundamentalDriverLite] = Field(default_factory=list)
