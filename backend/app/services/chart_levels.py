"""Sync and validate technical chart levels with trade setup."""

from __future__ import annotations

from app.schemas.technical import ChartLevels, TradeSetup
from app.tools import technical, twelve_data


async def build_chart_levels_from_market(interval: str = "1h", lookback: int = 30) -> ChartLevels:
    ts = await twelve_data.get_xau_time_series(interval, lookback + 5)
    values = ts.get("values") or []
    sr = technical.calculate_support_resistance(values, lookback)
    quote = await twelve_data.get_xau_quote()
    try:
        price = float(quote.get("close") or quote.get("price") or (values[0].get("close") if values else 0))
    except (TypeError, ValueError, IndexError):
        price = 0.0

    supports = sr.get("support_levels") or []
    resistances = sr.get("resistance_levels") or []
    trend = "Neutral"
    if len(values) >= 2:
        try:
            recent = float(values[0].get("close", 0))
            prior = float(values[1].get("close", 0))
            if recent > prior * 1.002:
                trend = "Bullish"
            elif recent < prior * 0.998:
                trend = "Bearish"
        except (TypeError, ValueError):
            pass

    if not supports and price:
        supports = [round(price * 0.995, 2)]
    if not resistances and price:
        resistances = [round(price * 1.005, 2)]

    return ChartLevels(
        trend=trend,
        support_levels=supports[:3],
        resistance_levels=resistances[:3],
    )


def _parse_invalidation_level(invalidation: str, stop_loss: float | None) -> float | None:
    if stop_loss is not None:
        return stop_loss
    text = invalidation.lower()
    for token in text.replace(",", " ").split():
        try:
            val = float(token.replace("$", ""))
            if val > 100:
                return val
        except ValueError:
            continue
    return None


def sync_trade_setup_levels(trade_setup: TradeSetup, chart_levels: ChartLevels) -> tuple[TradeSetup, ChartLevels]:
    """Ensure trade_setup and chart_levels use consistent numeric levels."""
    inv_level = trade_setup.invalidation_level
    if inv_level is None:
        inv_level = _parse_invalidation_level(trade_setup.invalidation, trade_setup.stop_loss)

    if inv_level is not None:
        trade_setup = trade_setup.model_copy(update={"invalidation_level": inv_level})
        chart_levels = chart_levels.model_copy(update={"invalidation_level": inv_level})

    if trade_setup.stop_loss is not None and chart_levels.invalidation_level is None:
        chart_levels = chart_levels.model_copy(update={"invalidation_level": trade_setup.stop_loss})

    return trade_setup, chart_levels


def validate_entry_zone(trade_setup: TradeSetup, chart_levels: ChartLevels) -> bool:
    if trade_setup.bias == "NO_TRADE" or len(trade_setup.entry_zone) < 2:
        return True
    lo, hi = min(trade_setup.entry_zone), max(trade_setup.entry_zone)
    supports = chart_levels.support_levels or [lo - 100]
    resistances = chart_levels.resistance_levels or [hi + 100]
    min_support = min(supports)
    max_resistance = max(resistances)
    return min_support <= lo and hi <= max_resistance


async def resolve_technical_chart_output(
    lite_chart_levels: ChartLevels | None,
    trade_setup: TradeSetup | None,
    direction: str,
    interval: str = "1h",
) -> tuple[ChartLevels, TradeSetup | None]:
    chart_levels = lite_chart_levels or await build_chart_levels_from_market(interval)

    if trade_setup:
        trade_setup, chart_levels = sync_trade_setup_levels(trade_setup, chart_levels)
        if not validate_entry_zone(trade_setup, chart_levels):
            return chart_levels, None

    if direction == "BULLISH" and not chart_levels.trend:
        chart_levels = chart_levels.model_copy(update={"trend": "Bullish"})
    elif direction == "BEARISH" and not chart_levels.trend:
        chart_levels = chart_levels.model_copy(update={"trend": "Bearish"})

    return chart_levels, trade_setup
