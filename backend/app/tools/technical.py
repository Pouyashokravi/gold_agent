from typing import Any


def _extract_closes(values: list[dict[str, Any]]) -> list[float]:
    closes: list[float] = []
    for row in values:
        try:
            closes.append(float(row.get("close", 0)))
        except (TypeError, ValueError):
            continue
    return closes


def calculate_support_resistance(values: list[dict[str, Any]], lookback: int = 20) -> dict[str, Any]:
    closes = _extract_closes(values[-lookback:])
    if not closes:
        return {"support_levels": [], "resistance_levels": []}
    current = closes[0]
    sorted_closes = sorted(closes)
    support = [round(v, 2) for v in sorted_closes[:3]]
    resistance = [round(v, 2) for v in sorted_closes[-3:] if v > current]
    return {"support_levels": support, "resistance_levels": resistance, "current": round(current, 2)}


def calculate_volatility(values: list[dict[str, Any]], lookback: int = 20) -> dict[str, Any]:
    closes = _extract_closes(values[-lookback:])
    if len(closes) < 2:
        return {"volatility_pct": 0.0, "label": "unknown"}
    returns = [(closes[i] - closes[i + 1]) / closes[i + 1] for i in range(len(closes) - 1) if closes[i + 1]]
    if not returns:
        return {"volatility_pct": 0.0, "label": "unknown"}
    avg = sum(abs(r) for r in returns) / len(returns)
    vol_pct = round(avg * 100, 3)
    label = "low" if vol_pct < 0.3 else "medium" if vol_pct < 0.8 else "high"
    return {"volatility_pct": vol_pct, "label": label}
