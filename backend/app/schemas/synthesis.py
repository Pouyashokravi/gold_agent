from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import Direction, Horizon
from app.schemas.technical import ChartAnnotations, TradeSetup


class Scenario(BaseModel):
    direction: str
    weight: float = Field(ge=0.0, le=1.0)
    drivers: list[str] = Field(default_factory=list)


class AgentPairRelation(BaseModel):
    agent_a: Literal["news", "fundamental", "technical"]
    agent_b: Literal["news", "fundamental", "technical"]
    relation: str
    severity: float = Field(ge=0.0, le=1.0)
    explanation: str


class AgentConflictAnalysis(BaseModel):
    relations: list[AgentPairRelation] = Field(default_factory=list)
    agreement_summary: str = ""
    confidence_adjustment: float = 0.0
    dominant_conflict: str | None = None


class SynthesisOutput(BaseModel):
    overall_direction: Direction
    confidence: float = Field(ge=0.0, le=1.0)
    horizon: Horizon
    base_case: Scenario
    bull_case: Scenario
    bear_case: Scenario
    agreements: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    key_drivers: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    technical_confirmation: str | None = None
    trade_setup: TradeSetup | None = None
    agent_conflicts: AgentConflictAnalysis | None = None
    chart_annotations: ChartAnnotations | None = None
