from datetime import UTC, datetime

from app.schemas.common import Horizon
from app.schemas.fundamental import FundamentalAgentOutput, FundamentalDriver
from app.tools import fred


def _parse_values(observations: list) -> list[float]:
    vals = []
    for o in observations:
        try:
            v = float(o.get("value", 0))
            if v == v:
                vals.append(v)
        except (TypeError, ValueError):
            continue
    return vals


def _trend(vals: list[float]) -> str:
    if len(vals) < 2:
        return "stable"
    if vals[0] > vals[-1] * 1.01:
        return "rising"
    if vals[0] < vals[-1] * 0.99:
        return "falling"
    return "stable"


async def build_fundamental_fallback(payload: dict) -> FundamentalAgentOutput:
    snap = await fred.get_macro_snapshot()
    drivers: list[FundamentalDriver] = []
    macro_drivers: list[str] = []
    risks: list[str] = []
    bullish = 0
    bearish = 0

    mapping = {
        "dff": ("Fed Funds Rate", "HIGH"),
        "dgs10": ("10Y Treasury Yield", "HIGH"),
        "dfii10": ("10Y Real Yield", "CRITICAL"),
        "cpiaucsl": ("CPI", "MEDIUM"),
    }

    for key, (name, importance) in mapping.items():
        block = snap.get(key, {})
        obs = block.get("observations") or []
        vals = _parse_values(obs)
        latest = block.get("latest_value", "N/A")
        trend = _trend(vals)
        state = f"{latest} ({trend})"

        direction = "NEUTRAL"
        if key in {"dgs10", "dfii10", "dff"}:
            if trend == "rising":
                direction = "BEARISH"
                bearish += 1
            elif trend == "falling":
                direction = "BULLISH"
                bullish += 1
        elif key == "cpiaucsl" and trend == "rising":
            direction = "BULLISH"
            bullish += 1

        drivers.append(FundamentalDriver(
            name=name,
            current_state=state,
            direction_for_gold=direction,
            importance=importance,
            confidence=0.6,
            horizon_relevance={},
            evidence_ids=[],
        ))
        macro_drivers.append(f"{name}: {state}")

    if bullish > bearish:
        overall = "BULLISH"
    elif bearish > bullish:
        overall = "BEARISH"
    else:
        overall = "NEUTRAL"

    if snap.get("dff", {}).get("latest_value") is None:
        risks.append("Some macro series unavailable")

    horizon_raw = payload.get("horizon", "medium_term")
    try:
        horizon = Horizon(horizon_raw)
    except ValueError:
        horizon = Horizon.MEDIUM_TERM

    return FundamentalAgentOutput(
        direction=overall,
        confidence=0.6,
        horizon=horizon,
        drivers=macro_drivers or ["Macro snapshot from FRED"],
        risks=risks or ["Limited macro coverage"],
        evidence=[],
        sources=[],
        timestamp=datetime.now(UTC),
        freshness="FRESH",
        fundamental_drivers=drivers,
    )
