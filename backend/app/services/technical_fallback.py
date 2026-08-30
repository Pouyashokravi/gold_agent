from datetime import UTC, datetime
from typing import Any

from app.schemas.common import Horizon
from app.schemas.technical import TechnicalAgentOutput
from app.tools import twelve_data


async def build_technical_fallback(payload: dict) -> TechnicalAgentOutput:
    """Deterministic fallback when LLM structured output fails."""
    quote = await twelve_data.get_xau_quote()
    ts = await twelve_data.get_xau_time_series("1h", 30)

    price = _extract_price(quote)
    values = ts.get("values") or []
    direction = "NEUTRAL"
    drivers: list[str] = []
    risks: list[str] = []

    if price:
        drivers.append(f"Current XAU/USD price: {price}")

    if len(values) >= 2:
        try:
            recent = float(values[0].get("close", 0))
            prior = float(values[1].get("close", 0))
            if recent > prior * 1.002:
                direction = "BULLISH"
                drivers.append("Short-term hourly momentum is positive")
            elif recent < prior * 0.998:
                direction = "BEARISH"
                drivers.append("Short-term hourly momentum is negative")
            else:
                drivers.append("Price consolidating on hourly timeframe")
        except (TypeError, ValueError):
            pass

    if quote.get("error") or ts.get("error"):
        risks.append("Some market data may be incomplete")

    horizon_raw = payload.get("horizon", "intraday")
    try:
        horizon = Horizon(horizon_raw)
    except ValueError:
        horizon = Horizon.INTRADAY

    return TechnicalAgentOutput(
        direction=direction,
        confidence=0.55 if price else 0.35,
        horizon=horizon,
        drivers=drivers or ["Limited live data available"],
        risks=risks or ["Data coverage incomplete"],
        evidence=[],
        sources=[],
        timestamp=datetime.now(UTC),
        freshness="FRESH",
        short_term_view=f"Price near {price}" if price else None,
    )


def _extract_price(quote: dict[str, Any]) -> str | None:
    for key in ("close", "price", "last"):
        if quote.get(key):
            return str(quote[key])
    return None
