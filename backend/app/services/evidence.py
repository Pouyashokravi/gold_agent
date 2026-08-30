HORIZON_AGENT_WEIGHTS: dict[str, dict[str, float]] = {
    "intraday": {"technical": 0.9, "news": 0.85, "fundamental": 0.2},
    "few_days": {"technical": 0.8, "news": 0.75, "fundamental": 0.4},
    "short_term": {"technical": 0.75, "news": 0.6, "fundamental": 0.5},
    "medium_term": {"technical": 0.7, "news": 0.45, "fundamental": 0.8},
    "long_term": {"technical": 0.55, "news": 0.3, "fundamental": 0.9},
    "ages": {"technical": 0.45, "news": 0.15, "fundamental": 0.95},
}


def effective_evidence_weight(
    agent_weight: float,
    freshness_weight: float,
    relevance: float,
    confidence: float,
) -> float:
    return agent_weight * freshness_weight * relevance * confidence


def clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, value))


def agent_weight_for_horizon(horizon: str, agent: str) -> float:
    return HORIZON_AGENT_WEIGHTS.get(horizon, HORIZON_AGENT_WEIGHTS["few_days"]).get(agent, 0.5)
