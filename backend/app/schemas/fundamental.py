from pydantic import BaseModel, Field

from app.schemas.common import Direction, Importance, SpecialistOutput


class FundamentalDriver(BaseModel):
    name: str
    current_state: str
    direction_for_gold: Direction
    importance: Importance
    confidence: float = Field(ge=0.0, le=1.0)
    horizon_relevance: dict[str, float] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)


class FundamentalAgentOutput(SpecialistOutput):
    fundamental_drivers: list[FundamentalDriver] = Field(default_factory=list)
