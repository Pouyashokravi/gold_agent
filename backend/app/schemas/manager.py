from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import Direction, Freshness, Horizon, Importance
from app.schemas.synthesis import SynthesisOutput


class ComplexityLevel(str, Enum):
    FAST = "FAST"
    STANDARD = "STANDARD"
    RESEARCH = "RESEARCH"


class GateRoute(str, Enum):
    GENERAL_CHAT = "GENERAL_CHAT"
    OFF_TOPIC = "OFF_TOPIC"
    FAST = "FAST"
    CLARIFY = "CLARIFY"
    RESEARCH = "RESEARCH"


TaskKind = Literal[
    "agent_news",
    "agent_fundamental",
    "agent_technical",
    "tool_quote",
    "tool_ohlc",
    "tool_rsi",
    "tool_sma",
    "tool_ema",
    "tool_macd",
    "tool_atr",
    "tool_macro_snapshot",
]


class ManagerTask(BaseModel):
    id: str
    kind: TaskKind
    task: str = ""
    focus: list[str] = Field(default_factory=list)
    depth: Literal["OFF", "LIGHT", "STANDARD", "DEEP"] = "STANDARD"
    depends_on: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class ManagerPlan(BaseModel):
    goal: str
    horizon: Horizon = Horizon.FEW_DAYS
    complexity: ComplexityLevel = ComplexityLevel.STANDARD
    clarification_question: str | None = None
    tasks: list[ManagerTask] = Field(default_factory=list)
    use_prior_thesis: bool = False
    rationale: str = ""


class ManagerReview(BaseModel):
    enough_evidence: bool = True
    missing: list[str] = Field(default_factory=list)
    replan_tasks: list[ManagerTask] = Field(default_factory=list)
    notes: str = ""


class ManagerAnswerOutput(BaseModel):
    answer: str
    synthesis: SynthesisOutput


class EvidenceCategory(str, Enum):
    MARKET_DATA = "market_data"
    NEWS = "news"
    FUNDAMENTAL = "fundamental"
    TECHNICAL = "technical"
    ECONOMIC_SURPRISE = "economic_surprise"
    MEMORY = "memory"
    TOOL = "tool"


class EvidenceItem(BaseModel):
    evidence_id: str
    category: EvidenceCategory
    source: str
    claim: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: str | None = None
    freshness: Freshness = "FRESH"
    horizon: Horizon | None = None
    direction: Direction | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    importance: Importance | None = None
    relevance: float | None = Field(default=None, ge=0.0, le=1.0)


class EvidencePool(BaseModel):
    items: list[EvidenceItem] = Field(default_factory=list)
    specialist_outputs: dict[str, Any] = Field(default_factory=dict)
    tool_outputs: dict[str, Any] = Field(default_factory=dict)
    economic_surprises: list[dict[str, Any]] = Field(default_factory=list)
    memory_hits: list[str] = Field(default_factory=list)

    def add(self, item: EvidenceItem) -> None:
        self.items.append(item)
