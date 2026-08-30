"""Economic surprise computation from actual vs forecast data."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import Direction, Importance

SurpriseMagnitude = Literal["LOW", "MEDIUM", "LARGE", "EXTREME"]
SurpriseDirection = Literal["ABOVE", "BELOW", "INLINE"]

# Per-event-type thresholds: (medium, large, extreme) in native units
MAGNITUDE_THRESHOLDS: dict[str, tuple[float, float, float]] = {
    "cpi": (0.1, 0.2, 0.3),
    "core_cpi": (0.1, 0.2, 0.3),
    "pce": (0.1, 0.2, 0.3),
    "core_pce": (0.1, 0.2, 0.3),
    "nfp": (30.0, 75.0, 150.0),
    "unemployment": (0.1, 0.2, 0.4),
    "fed_rate": (0.25, 0.5, 0.75),
    "gdp": (0.3, 0.6, 1.0),
    "retail_sales": (0.3, 0.6, 1.0),
    "jobless_claims": (10.0, 25.0, 50.0),
    "other_macro_event": (0.2, 0.5, 1.0),
}

IMPORTANCE_BOOST: dict[str, Importance] = {
    "LOW": "MEDIUM",
    "MEDIUM": "HIGH",
    "LARGE": "HIGH",
    "EXTREME": "CRITICAL",
}

SURPRISE_FACTOR_MAP: dict[str, float] = {
    "LOW": 0.25,
    "MEDIUM": 0.5,
    "LARGE": 0.75,
    "EXTREME": 0.95,
}


class SurpriseAssessment(BaseModel):
    event_type: str
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None
    surprise_measurable: bool = False
    surprise_delta: float | None = None
    surprise_direction: SurpriseDirection | None = None
    surprise_magnitude: SurpriseMagnitude | None = None
    surprise_interpretation: str | None = None
    surprise_gold_bias: Direction | None = None
    mechanism: list[str] = Field(default_factory=list)
    surprise_factor: float = 0.0


def _parse_numeric(value: float | str | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "").replace("K", "000").replace("k", "000")
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_event_type(event_type: str) -> str:
    et = event_type.lower().strip()
    mapping = {
        "cpi": "cpi",
        "core_cpi": "core_cpi",
        "core cpi": "core_cpi",
        "pce": "pce",
        "core_pce": "core_pce",
        "core pce": "core_pce",
        "nfp": "nfp",
        "nonfarm": "nfp",
        "nonfarm payroll": "nfp",
        "unemployment": "unemployment",
        "fed_rate": "fed_rate",
        "fed rate": "fed_rate",
        "fomc": "fed_rate",
        "federal reserve": "fed_rate",
        "gdp": "gdp",
        "retail_sales": "retail_sales",
        "retail sales": "retail_sales",
        "jobless_claims": "jobless_claims",
        "jobless claims": "jobless_claims",
        "initial claims": "jobless_claims",
    }
    for key, normalized in mapping.items():
        if key in et:
            return normalized
    return "other_macro_event"


def classify_surprise_magnitude(delta: float, event_type: str) -> SurpriseMagnitude:
    abs_delta = abs(delta)
    thresholds = MAGNITUDE_THRESHOLDS.get(event_type, MAGNITUDE_THRESHOLDS["other_macro_event"])
    medium, large, extreme = thresholds
    if abs_delta >= extreme:
        return "EXTREME"
    if abs_delta >= large:
        return "LARGE"
    if abs_delta >= medium:
        return "MEDIUM"
    return "LOW"


def compute_surprise_factor(magnitude: str | None) -> float:
    if not magnitude:
        return 0.0
    return SURPRISE_FACTOR_MAP.get(magnitude, 0.0)


def boost_importance(base_importance: Importance, surprise_magnitude: SurpriseMagnitude | None) -> Importance:
    if not surprise_magnitude:
        return base_importance
    boosted = IMPORTANCE_BOOST.get(surprise_magnitude, base_importance)
    rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    if rank.get(boosted, 0) > rank.get(base_importance, 0):
        return boosted
    return base_importance


def interpret_for_gold(
    event_type: str,
    surprise_direction: SurpriseDirection,
    magnitude: SurpriseMagnitude,
) -> tuple[str, Direction, list[str]]:
    """Return interpretation text, tentative gold bias, and mechanism chain."""
    above = surprise_direction == "ABOVE"
    below = surprise_direction == "BELOW"

    if event_type in ("cpi", "core_cpi", "pce", "core_pce"):
        if above:
            return (
                f"Hotter-than-expected inflation ({magnitude.lower()} surprise) may lift real-yield expectations",
                "BEARISH",
                [
                    "Higher inflation surprise",
                    "Potential pressure on real yields",
                    "Higher opportunity cost of holding gold",
                    "Potential USD strength",
                ],
            )
        if below:
            return (
                f"Cooler-than-expected inflation ({magnitude.lower()} surprise) may ease rate pressure",
                "BULLISH",
                [
                    "Lower inflation surprise",
                    "Potential easing of real yields",
                    "Lower opportunity cost of holding gold",
                ],
            )

    if event_type == "nfp":
        if above:
            return (
                f"Stronger-than-expected NFP ({magnitude.lower()} surprise) signals tight labor market",
                "BEARISH",
                [
                    "Strong jobs surprise",
                    "Hawkish Fed risk",
                    "Potential USD strength",
                    "Higher yields pressure on gold",
                ],
            )
        if below:
            return (
                f"Weaker-than-expected NFP ({magnitude.lower()} surprise) may support dovish policy",
                "BULLISH",
                [
                    "Weak jobs surprise",
                    "Dovish Fed risk",
                    "Potential USD weakness",
                    "Lower yields supportive for gold",
                ],
            )

    if event_type == "fed_rate":
        if below:
            return (
                f"Larger-than-expected rate cut ({magnitude.lower()} surprise) is dovish",
                "BULLISH",
                [
                    "Dovish monetary-policy surprise",
                    "Potential pressure on yields",
                    "Potential USD weakness",
                    "Lower opportunity cost of holding gold",
                ],
            )
        if above:
            return (
                f"Smaller cut or hike ({magnitude.lower()} surprise) is hawkish",
                "BEARISH",
                [
                    "Hawkish monetary-policy surprise",
                    "Potential yield support",
                    "Potential USD strength",
                ],
            )

    if event_type == "gdp":
        if below:
            return (
                f"Weaker-than-expected GDP ({magnitude.lower()} surprise) raises growth concerns",
                "BULLISH",
                [
                    "Growth disappointment",
                    "Safe-haven demand for gold",
                    "Potential dovish policy response",
                ],
            )
        if above:
            return (
                f"Stronger-than-expected GDP ({magnitude.lower()} surprise) supports risk appetite",
                "BEARISH",
                [
                    "Growth beat",
                    "Reduced safe-haven demand",
                    "Potential hawkish policy risk",
                ],
            )

    if event_type == "unemployment":
        if above:
            return (
                f"Higher unemployment ({magnitude.lower()} surprise) is growth-negative",
                "BULLISH",
                ["Labor market softening", "Dovish policy risk", "Safe-haven bid for gold"],
            )
        if below:
            return (
                f"Lower unemployment ({magnitude.lower()} surprise) is growth-positive",
                "BEARISH",
                ["Tight labor market", "Hawkish policy risk", "USD/yield pressure on gold"],
            )

    if event_type == "retail_sales":
        if above:
            return (
                f"Stronger retail sales ({magnitude.lower()} surprise)",
                "BEARISH",
                ["Consumer strength", "Growth-positive", "Potential hawkish tilt"],
            )
        if below:
            return (
                f"Weaker retail sales ({magnitude.lower()} surprise)",
                "BULLISH",
                ["Consumer weakness", "Growth concern", "Safe-haven support"],
            )

    if event_type == "jobless_claims":
        if above:
            return (
                f"Higher jobless claims ({magnitude.lower()} surprise)",
                "BULLISH",
                ["Labor market softening", "Dovish policy risk"],
            )
        if below:
            return (
                f"Lower jobless claims ({magnitude.lower()} surprise)",
                "BEARISH",
                ["Labor market strength", "Hawkish policy risk"],
            )

    if above:
        return (
            f"Data above forecast ({magnitude.lower()} surprise)",
            "NEUTRAL",
            ["Macro surprise above expectations", "Context-dependent gold impact"],
        )
    if below:
        return (
            f"Data below forecast ({magnitude.lower()} surprise)",
            "NEUTRAL",
            ["Macro surprise below expectations", "Context-dependent gold impact"],
        )
    return ("Data in line with expectations", "NEUTRAL", ["No significant surprise"])


def assess_release(
    event_type: str,
    actual: float | str | None,
    forecast: float | str | None,
    previous: float | str | None = None,
) -> SurpriseAssessment:
    normalized_type = _normalize_event_type(event_type)
    actual_num = _parse_numeric(actual)
    forecast_num = _parse_numeric(forecast)
    previous_num = _parse_numeric(previous)

    if forecast_num is None or actual_num is None:
        return SurpriseAssessment(
            event_type=normalized_type,
            actual=actual_num,
            forecast=forecast_num,
            previous=previous_num,
            surprise_measurable=False,
        )

    delta = actual_num - forecast_num
    inline_threshold = MAGNITUDE_THRESHOLDS.get(normalized_type, (0.2, 0.5, 1.0))[0] * 0.25

    if abs(delta) <= inline_threshold:
        direction: SurpriseDirection = "INLINE"
        magnitude: SurpriseMagnitude = "LOW"
        interpretation, gold_bias, mechanism = ("In line with market expectations", "NEUTRAL", ["No significant surprise"])
        factor = 0.1
    else:
        direction = "ABOVE" if delta > 0 else "BELOW"
        magnitude = classify_surprise_magnitude(delta, normalized_type)
        interpretation, gold_bias, mechanism = interpret_for_gold(normalized_type, direction, magnitude)
        factor = compute_surprise_factor(magnitude)

    return SurpriseAssessment(
        event_type=normalized_type,
        actual=actual_num,
        forecast=forecast_num,
        previous=previous_num,
        surprise_measurable=True,
        surprise_delta=round(delta, 4),
        surprise_direction=direction,
        surprise_magnitude=magnitude,
        surprise_interpretation=interpretation,
        surprise_gold_bias=gold_bias,
        mechanism=mechanism,
        surprise_factor=factor,
    )


def enrich_news_event(
    event_type: str,
    actual: float | str | None,
    forecast: float | str | None,
    previous: float | str | None,
    base_importance: Importance,
    gold_relevance: float,
    event_importance: float,
    magnitude: float,
    persistence: float,
    source_confidence: float,
) -> dict:
    """Assess surprise and compute impact score for a news event."""
    from app.services.news_impact import classify_importance, compute_impact_score

    assessment = assess_release(event_type, actual, forecast, previous)
    surprise_factor = assessment.surprise_factor if assessment.surprise_measurable else 0.0
    impact = compute_impact_score(
        gold_relevance,
        event_importance,
        surprise_factor,
        magnitude,
        persistence,
        source_confidence,
    )
    importance = boost_importance(base_importance, assessment.surprise_magnitude) if assessment.surprise_measurable else base_importance
    if assessment.surprise_measurable and assessment.surprise_magnitude in ("LARGE", "EXTREME"):
        importance = classify_importance(max(impact, 0.85 if assessment.surprise_magnitude == "EXTREME" else 0.7))

    return {
        "assessment": assessment,
        "impact_score": impact,
        "importance": importance,
        "surprise_factor": surprise_factor,
    }
