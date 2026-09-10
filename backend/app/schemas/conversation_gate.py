"""LLM Conversation Gate structured output (runs before Gold Manager)."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import Horizon, Intent
from app.schemas.manager import ComplexityLevel, GateRoute


class AnalysisPurpose(str, Enum):
    """Independent of analysis scopes / intent."""

    INVESTMENT = "INVESTMENT"
    TRADING = "TRADING"
    MARKET_VIEW = "MARKET_VIEW"
    OTHER = "OTHER"


class AnalysisScope(str, Enum):
    """Required analysis capabilities (multi-select)."""

    FUNDAMENTAL = "FUNDAMENTAL"
    TECHNICAL = "TECHNICAL"
    NEWS = "NEWS"


class ContextRelationship(str, Enum):
    """How the current user message relates to conversation context."""

    INDEPENDENT = "INDEPENDENT"
    FOLLOW_UP = "FOLLOW_UP"
    CLARIFICATION_ANSWER = "CLARIFICATION_ANSWER"


FAST_KIND_ALLOWLIST: frozenset[str] = frozenset(
    {"quote", "high_low", "rsi", "sma", "ema", "macd", "atr"}
)

CLARIFY_FIELD_ANALYSIS_SCOPES = "analysis_scopes"
CLARIFY_FIELD_ANALYSIS_TYPE = "analysis_type"  # legacy alias → analysis_scopes
CLARIFY_FIELD_PURPOSE = "purpose"
CLARIFY_FIELD_HORIZON = "horizon"
CLARIFY_CANONICAL_FIELDS: tuple[str, ...] = (
    CLARIFY_FIELD_ANALYSIS_SCOPES,
    CLARIFY_FIELD_PURPOSE,
    CLARIFY_FIELD_HORIZON,
)

COMPREHENSIVE_SCOPES: list[AnalysisScope] = [
    AnalysisScope.FUNDAMENTAL,
    AnalysisScope.TECHNICAL,
    AnalysisScope.NEWS,
]

# Legacy singular labels still seen in pending metadata
INTENT_TO_ANALYSIS_TYPE: dict[Intent, str] = {
    Intent.TECHNICAL_ANALYSIS: "TECHNICAL",
    Intent.FUNDAMENTAL_ANALYSIS: "FUNDAMENTAL",
    Intent.NEWS_ANALYSIS: "NEWS",
    Intent.EVENT_IMPACT: "EVENT_IMPACT",
    Intent.MARKET_OUTLOOK: "GENERAL",
    Intent.MARKET_MOVE_EXPLANATION: "GENERAL",
    Intent.TRADE_ANALYSIS: "TECHNICAL",
    Intent.PRICE_QUERY: "PRICE",
    Intent.HISTORICAL_ANALYSIS: "GENERAL",
}

ANALYSIS_TYPE_TO_INTENT: dict[str, Intent] = {
    "TECHNICAL": Intent.TECHNICAL_ANALYSIS,
    "FUNDAMENTAL": Intent.FUNDAMENTAL_ANALYSIS,
    "NEWS": Intent.NEWS_ANALYSIS,
    "EVENT_IMPACT": Intent.EVENT_IMPACT,
    "GENERAL": Intent.MARKET_OUTLOOK,
    "PRICE": Intent.PRICE_QUERY,
}

SCOPE_TO_AGENT_KIND: dict[AnalysisScope, str] = {
    AnalysisScope.FUNDAMENTAL: "agent_fundamental",
    AnalysisScope.TECHNICAL: "agent_technical",
    AnalysisScope.NEWS: "agent_news",
}

ANALYSIS_INTENTS: frozenset[Intent] = frozenset(
    {
        Intent.TECHNICAL_ANALYSIS,
        Intent.FUNDAMENTAL_ANALYSIS,
        Intent.NEWS_ANALYSIS,
        Intent.EVENT_IMPACT,
        Intent.MARKET_OUTLOOK,
        Intent.MARKET_MOVE_EXPLANATION,
        Intent.TRADE_ANALYSIS,
        Intent.HISTORICAL_ANALYSIS,
    }
)

# Intents that normally need a canonical horizon for completeness
HORIZON_REQUIRED_INTENTS: frozenset[Intent] = frozenset(
    {
        Intent.MARKET_OUTLOOK,
        Intent.MARKET_MOVE_EXPLANATION,
        Intent.TRADE_ANALYSIS,
        Intent.TECHNICAL_ANALYSIS,
        Intent.FUNDAMENTAL_ANALYSIS,
    }
)

# Timing may be satisfied without a Horizon enum (news recency, event window, historical period)
TIMING_FLEXIBLE_INTENTS: frozenset[Intent] = frozenset(
    {
        Intent.NEWS_ANALYSIS,
        Intent.EVENT_IMPACT,
        Intent.HISTORICAL_ANALYSIS,
    }
)


def normalize_legacy_analysis_type(value: Any) -> list[AnalysisScope]:
    """Map legacy singular analysis_type / GENERAL → analysis_scopes list."""
    if value is None or value == "":
        return []
    if isinstance(value, AnalysisScope):
        return [value]
    if isinstance(value, list):
        out: list[AnalysisScope] = []
        for item in value:
            out.extend(normalize_legacy_analysis_type(item))
        # de-dupe preserving order
        seen: set[AnalysisScope] = set()
        uniq: list[AnalysisScope] = []
        for s in out:
            if s not in seen:
                seen.add(s)
                uniq.append(s)
        return uniq
    raw = str(value).strip().upper()
    if raw in {s.value for s in AnalysisScope}:
        return [AnalysisScope(raw)]
    if raw in {"GENERAL", "COMPREHENSIVE", "ALL", "OUTLOOK", "EVENT_IMPACT"}:
        return list(COMPREHENSIVE_SCOPES)
    if raw == "PRICE":
        return []
    return []


def scopes_from_intent(intent: Intent | None) -> list[AnalysisScope]:
    """Soft default scopes from a single-discipline / outlook intent (never invent on incomplete clarify)."""
    if intent is None or intent == Intent.PRICE_QUERY:
        return []
    if intent in {Intent.TECHNICAL_ANALYSIS, Intent.TRADE_ANALYSIS}:
        return [AnalysisScope.TECHNICAL]
    if intent == Intent.FUNDAMENTAL_ANALYSIS:
        return [AnalysisScope.FUNDAMENTAL]
    if intent == Intent.NEWS_ANALYSIS:
        return [AnalysisScope.NEWS]
    if intent in {
        Intent.MARKET_OUTLOOK,
        Intent.MARKET_MOVE_EXPLANATION,
        Intent.EVENT_IMPACT,
        Intent.HISTORICAL_ANALYSIS,
    }:
        return list(COMPREHENSIVE_SCOPES)
    return []


def coerce_analysis_scopes(value: Any) -> list[AnalysisScope]:
    """Accept list/enum/legacy singular → list[AnalysisScope]."""
    if value is None or value == "" or value == []:
        return []
    if isinstance(value, list):
        return normalize_legacy_analysis_type(value)
    return normalize_legacy_analysis_type(value)


def normalize_resolved_fields(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize pending/runtime resolved_fields; legacy analysis_type → analysis_scopes."""
    if not raw:
        return {}
    out: dict[str, Any] = {}
    legacy_type = raw.get(CLARIFY_FIELD_ANALYSIS_TYPE)
    scopes_raw = raw.get(CLARIFY_FIELD_ANALYSIS_SCOPES)
    scopes = coerce_analysis_scopes(scopes_raw) if scopes_raw not in (None, "", []) else []
    if not scopes and legacy_type not in (None, ""):
        scopes = normalize_legacy_analysis_type(legacy_type)
    if scopes:
        out[CLARIFY_FIELD_ANALYSIS_SCOPES] = [s.value if isinstance(s, AnalysisScope) else str(s) for s in scopes]
    for key in (CLARIFY_FIELD_PURPOSE, CLARIFY_FIELD_HORIZON, "intent"):
        val = raw.get(key)
        if val is not None and val != "":
            out[key] = val.value if hasattr(val, "value") else val
    # timing_explicit marker (optional, for historical/event/news)
    if raw.get("timing_explicit"):
        out["timing_explicit"] = True
    return out


def scope_values(scopes: list[AnalysisScope] | list[str] | None) -> list[str]:
    if not scopes:
        return []
    return [s.value if isinstance(s, AnalysisScope) else str(s) for s in scopes]


class NewlyResolvedFields(BaseModel):
    """Typed current-turn semantic delta (null = not established this turn)."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent | None = Field(
        default=None,
        description="Intent newly established by the current message only.",
    )
    analysis_scopes: list[AnalysisScope] | None = Field(
        default=None,
        description="Scopes newly established by the current message; null if none this turn.",
    )
    horizon: Horizon | None = Field(
        default=None,
        description="Horizon newly established by the current message only.",
    )
    purpose: AnalysisPurpose | None = Field(
        default=None,
        description="Purpose newly established by the current message only.",
    )

    def has_any(self) -> bool:
        return (
            self.intent is not None
            or (self.analysis_scopes is not None and len(self.analysis_scopes) > 0)
            or self.horizon is not None
            or self.purpose is not None
        )


class ConversationGateLLMOutput(BaseModel):
    """Strict schema sent to / returned from the Gate LLM (no is_follow_up)."""

    model_config = ConfigDict(extra="forbid")

    action: GateRoute = Field(
        description=(
            "GENERAL_CHAT for greetings; FAST only with valid fast_kind "
            "(quote requires intent=price_query); CLARIFY only for incomplete analysis; "
            "STANDARD/RESEARCH when intent-aware required fields are known — never invent them."
        )
    )
    intent: Intent | None = Field(
        default=None,
        description=(
            "Overall user goal (market_outlook, technical_analysis, price_query, …). "
            "Never inherit from history alone."
        ),
    )
    analysis_scopes: list[AnalysisScope] = Field(
        default_factory=list,
        description=(
            "Multi-select required capabilities: FUNDAMENTAL, TECHNICAL, NEWS. "
            "Infer from meaning (e.g. full outlook → all three). Never invent on incomplete clarify."
        ),
    )
    purpose: AnalysisPurpose | None = Field(
        default=None,
        description="Set only when the user supplied purpose or it is already resolved.",
    )
    horizon: Horizon | None = Field(
        default=None,
        description="Set only when the user supplied a horizon or it is already resolved. Never invent.",
    )
    newly_resolved_fields: NewlyResolvedFields = Field(
        default_factory=NewlyResolvedFields,
        description=(
            "Typed current-turn delta: only fields newly established by THIS message. "
            "On CLARIFICATION_ANSWER this is authoritative over conflicting top-level values."
        ),
    )
    context_relationship: ContextRelationship = Field(
        default=ContextRelationship.INDEPENDENT,
        description=(
            "INDEPENDENT = new self-contained message (greetings, new price/analysis). "
            "FOLLOW_UP = continues prior thread without answering a pending clarify. "
            "CLARIFICATION_ANSWER = answers the pending clarification question."
        ),
    )
    missing_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Unresolved fields only when needed: analysis_scopes, horizon, purpose. "
            "Do not require internal agent labels."
        ),
    )
    clarification_question: str | None = Field(
        default=None,
        description="English user-facing question covering only missing_fields (no agent names).",
    )
    fast_kind: str | None = Field(
        default=None,
        description="Required for FAST: quote | high_low | rsi | sma | ema | macd | atr. Never invent.",
    )
    fast_interval: str | None = None
    normalized_query: str | None = None
    complexity: ComplexityLevel = ComplexityLevel.STANDARD
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = ""


class ConversationGateOutput(ConversationGateLLMOutput):
    """Runtime decision after merge/repair (includes cumulative resolved_fields)."""

    is_follow_up: bool = False
    resolved_fields: dict[str, Any] = Field(default_factory=dict)
    repair_used: bool = False
    emergency_fallback: bool = False
    delta_conflict: bool = False

    @model_validator(mode="after")
    def _derive_is_follow_up(self) -> ConversationGateOutput:
        self.is_follow_up = self.context_relationship in {
            ContextRelationship.FOLLOW_UP,
            ContextRelationship.CLARIFICATION_ANSWER,
        }
        return self

    @property
    def fast_params(self) -> dict[str, str]:
        params: dict[str, str] = {}
        if self.fast_interval:
            params["interval"] = self.fast_interval
        return params
