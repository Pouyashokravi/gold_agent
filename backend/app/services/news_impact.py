def compute_surprise_factor(magnitude: str | None) -> float:
    """Map surprise magnitude label to 0-1 factor for impact scoring."""
    factors = {
        "LOW": 0.25,
        "MEDIUM": 0.5,
        "LARGE": 0.75,
        "EXTREME": 0.95,
    }
    if not magnitude:
        return 0.0
    return factors.get(magnitude.upper(), 0.0)


def classify_importance(score: float) -> str:
    if score >= 0.85:
        return "CRITICAL"
    if score >= 0.65:
        return "HIGH"
    if score >= 0.35:
        return "MEDIUM"
    return "LOW"


def compute_impact_score(
    gold_relevance: float,
    event_importance: float,
    surprise_factor: float,
    magnitude: float,
    persistence: float,
    source_confidence: float,
) -> float:
    return round(
        0.25 * gold_relevance
        + 0.20 * event_importance
        + 0.20 * surprise_factor
        + 0.15 * magnitude
        + 0.10 * persistence
        + 0.10 * source_confidence,
        3,
    )


DEFAULT_HORIZON_IMPACT = {
    "intraday": 0.9,
    "few_days": 0.75,
    "short_term": 0.6,
    "medium_term": 0.4,
    "long_term": 0.25,
    "ages": 0.1,
}
