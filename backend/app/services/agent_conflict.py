"""Programmatic agent agreement and contradiction analysis."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import Horizon
from app.schemas.synthesis import AgentConflictAnalysis, AgentPairRelation

AgentName = Literal["news", "fundamental", "technical"]

HORIZON_ORDER = [
    "intraday",
    "few_days",
    "short_term",
    "medium_term",
    "long_term",
    "ages",
]

AGENT_PAIRS: list[tuple[AgentName, AgentName]] = [
    ("news", "fundamental"),
    ("news", "technical"),
    ("fundamental", "technical"),
]


class ConflictType(str, Enum):
    AGREEMENT = "AGREEMENT"
    PARTIAL_AGREEMENT = "PARTIAL_AGREEMENT"
    DIRECTION_CONFLICT = "DIRECTION_CONFLICT"
    HORIZON_CONFLICT = "HORIZON_CONFLICT"
    DATA_CONFLICT = "DATA_CONFLICT"


def _horizon_index(h: str) -> int:
    try:
        return HORIZON_ORDER.index(h)
    except ValueError:
        return 2


def _horizon_distance(a: str, b: str) -> int:
    return abs(_horizon_index(a) - _horizon_index(b))


def _direction_family(direction: str) -> str:
    d = (direction or "NEUTRAL").upper()
    if d in ("BULLISH", "LONG"):
        return "bullish"
    if d in ("BEARISH", "SHORT"):
        return "bearish"
    return "neutral"


def _extract_agent(out: dict[str, Any] | None) -> dict[str, Any]:
    if not out:
        return {"direction": "NEUTRAL", "confidence": 0.0, "horizon": "few_days", "drivers": [], "available": False}
    return {
        "direction": out.get("direction", "NEUTRAL"),
        "confidence": float(out.get("confidence") or 0.0),
        "horizon": out.get("horizon", "few_days"),
        "drivers": out.get("drivers") or [],
        "available": True,
    }


def _detect_data_conflict(drivers_a: list[str], drivers_b: list[str]) -> bool:
    text_a = " ".join(drivers_a).lower()
    text_b = " ".join(drivers_b).lower()
    bullish_a = any(w in text_a for w in ("bullish", "rise", "rally", "higher", "gain"))
    bearish_a = any(w in text_a for w in ("bearish", "fall", "drop", "lower", "decline"))
    bullish_b = any(w in text_b for w in ("bullish", "rise", "rally", "higher", "gain"))
    bearish_b = any(w in text_b for w in ("bearish", "fall", "drop", "lower", "decline"))
    return (bullish_a and bearish_b) or (bearish_a and bullish_b)


def _classify_pair(
    agent_a: AgentName,
    agent_b: AgentName,
    a: dict[str, Any],
    b: dict[str, Any],
    user_horizon: str,
) -> AgentPairRelation:
    if not a["available"] or not b["available"]:
        return AgentPairRelation(
            agent_a=agent_a,
            agent_b=agent_b,
            relation=ConflictType.PARTIAL_AGREEMENT.value,
            severity=0.1,
            explanation=f"{agent_a.title()} or {agent_b.title()} output unavailable — limited comparison.",
        )

    dir_a = _direction_family(a["direction"])
    dir_b = _direction_family(b["direction"])
    conf_a = a["confidence"]
    conf_b = b["confidence"]
    hz_a = str(a["horizon"])
    hz_b = str(b["horizon"])
    hz_dist = _horizon_distance(hz_a, hz_b)

    label_a = agent_a.title()
    label_b = agent_b.title()

    if _detect_data_conflict(a["drivers"], b["drivers"]) and dir_a != dir_b and dir_a != "neutral" and dir_b != "neutral":
        return AgentPairRelation(
            agent_a=agent_a,
            agent_b=agent_b,
            relation=ConflictType.DATA_CONFLICT.value,
            severity=min(0.9, 0.5 + abs(conf_a - conf_b) * 0.3),
            explanation=(
                f"{label_a} and {label_b} cite conflicting data interpretations "
                f"({a['direction']} vs {b['direction']})."
            ),
        )

    if dir_a == dir_b and dir_a != "neutral":
        conf_gap = abs(conf_a - conf_b)
        if conf_gap <= 0.15:
            return AgentPairRelation(
                agent_a=agent_a,
                agent_b=agent_b,
                relation=ConflictType.AGREEMENT.value,
                severity=0.2 + (conf_a + conf_b) / 4,
                explanation=f"{label_a} and {label_b} both lean {dir_a} with similar confidence.",
            )
        return AgentPairRelation(
            agent_a=agent_a,
            agent_b=agent_b,
            relation=ConflictType.PARTIAL_AGREEMENT.value,
            severity=0.3 + conf_gap * 0.3,
            explanation=(
                f"{label_a} and {label_b} agree on {dir_a} direction but differ in confidence "
                f"({conf_a:.0%} vs {conf_b:.0%})."
            ),
        )

    if dir_a != dir_b and dir_a != "neutral" and dir_b != "neutral":
        if hz_dist >= 2:
            return AgentPairRelation(
                agent_a=agent_a,
                agent_b=agent_b,
                relation=ConflictType.HORIZON_CONFLICT.value,
                severity=0.35 + (conf_a + conf_b) / 6,
                explanation=(
                    f"{label_a} is {a['direction']} ({hz_a.replace('_', ' ')}) while "
                    f"{label_b} is {b['direction']} ({hz_b.replace('_', ' ')}). "
                    f"This may reflect different time horizons rather than a direct contradiction."
                ),
            )
        return AgentPairRelation(
            agent_a=agent_a,
            agent_b=agent_b,
            relation=ConflictType.DIRECTION_CONFLICT.value,
            severity=0.55 + (conf_a + conf_b) / 4,
            explanation=(
                f"{label_a} ({a['direction']}, {hz_a.replace('_', ' ')}) conflicts with "
                f"{label_b} ({b['direction']}, {hz_b.replace('_', ' ')}) on similar horizons."
            ),
        )

    return AgentPairRelation(
        agent_a=agent_a,
        agent_b=agent_b,
        relation=ConflictType.PARTIAL_AGREEMENT.value,
        severity=0.2,
        explanation=(
            f"{label_a} ({a['direction']}) and {label_b} ({b['direction']}) — partial alignment, "
            f"one or both neutral/mixed."
        ),
    )


def compute_confidence_adjustment(relations: list[AgentPairRelation], has_critical_surprise: bool = False) -> float:
    adjustment = 0.0
    for rel in relations:
        if rel.relation == ConflictType.AGREEMENT.value:
            adjustment += 0.05 * rel.severity
        elif rel.relation == ConflictType.PARTIAL_AGREEMENT.value:
            adjustment += 0.01
        elif rel.relation == ConflictType.DIRECTION_CONFLICT.value:
            adjustment -= 0.10 * rel.severity
        elif rel.relation == ConflictType.HORIZON_CONFLICT.value:
            adjustment -= 0.04 * rel.severity
        elif rel.relation == ConflictType.DATA_CONFLICT.value:
            adjustment -= 0.08 * rel.severity

    agreements = sum(1 for r in relations if r.relation == ConflictType.AGREEMENT.value)
    if agreements >= 2:
        adjustment += 0.08

    direction_conflicts = [r for r in relations if r.relation == ConflictType.DIRECTION_CONFLICT.value]
    if direction_conflicts and has_critical_surprise:
        adjustment -= 0.05

    return max(-0.25, min(0.15, round(adjustment, 3)))


def _build_summary(relations: list[AgentPairRelation]) -> str:
    agreements = [r for r in relations if r.relation == ConflictType.AGREEMENT.value]
    direction_conflicts = [r for r in relations if r.relation == ConflictType.DIRECTION_CONFLICT.value]
    horizon_conflicts = [r for r in relations if r.relation == ConflictType.HORIZON_CONFLICT.value]

    parts: list[str] = []
    if len(agreements) >= 2:
        parts.append("Multiple agents agree on direction.")
    elif agreements:
        parts.append(f"{agreements[0].agent_a.title()} and {agreements[0].agent_b.title()} agree.")
    if direction_conflicts:
        r = direction_conflicts[0]
        parts.append(f"Direction conflict: {r.agent_a.title()} vs {r.agent_b.title()}.")
    if horizon_conflicts and not direction_conflicts:
        r = horizon_conflicts[0]
        parts.append(f"Horizon difference: {r.agent_a.title()} vs {r.agent_b.title()}.")
    if not parts:
        return "Agents show mixed or neutral signals."
    return " ".join(parts)


def _dominant_conflict(relations: list[AgentPairRelation]) -> str | None:
    priority = [
        ConflictType.DIRECTION_CONFLICT.value,
        ConflictType.DATA_CONFLICT.value,
        ConflictType.HORIZON_CONFLICT.value,
    ]
    for p in priority:
        matches = [r for r in relations if r.relation == p]
        if matches:
            return max(matches, key=lambda x: x.severity).relation
    return None


def analyze_agent_relations(
    specialist_outputs: dict[str, Any],
    user_horizon: Horizon | str,
    has_critical_surprise: bool = False,
) -> AgentConflictAnalysis:
    horizon = user_horizon.value if isinstance(user_horizon, Horizon) else str(user_horizon)
    agents = {
        "news": _extract_agent(specialist_outputs.get("news")),
        "fundamental": _extract_agent(specialist_outputs.get("fundamental")),
        "technical": _extract_agent(specialist_outputs.get("technical")),
    }

    relations: list[AgentPairRelation] = []
    for a_name, b_name in AGENT_PAIRS:
        relations.append(_classify_pair(a_name, b_name, agents[a_name], agents[b_name], horizon))

    adjustment = compute_confidence_adjustment(relations, has_critical_surprise)
    return AgentConflictAnalysis(
        relations=relations,
        agreement_summary=_build_summary(relations),
        confidence_adjustment=adjustment,
        dominant_conflict=_dominant_conflict(relations),
    )


def max_direction_conflict_severity(analysis: AgentConflictAnalysis) -> float:
    conflicts = [
        r for r in analysis.relations
        if r.relation == ConflictType.DIRECTION_CONFLICT.value
    ]
    if not conflicts:
        return 0.0
    return max(r.severity for r in conflicts)
