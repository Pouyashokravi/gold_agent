from typing import Any

from fastapi import APIRouter, Query

from app.tools import twelve_data

router = APIRouter(prefix="/api/market", tags=["market"])

ALLOWED_INTERVALS = {"1min", "5min", "15min", "30min", "45min", "1h", "2h", "4h", "1day", "1week", "1month"}


def _num(data: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = data.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


@router.get("/xau/quote")
async def get_xau_quote():
    data = await twelve_data.get_xau_quote()
    if data.get("error") or data.get("status") == "error":
        return {"symbol": "XAU/USD", "error": data.get("error", "Unknown error")}
    return {
        "symbol": data.get("symbol", "XAU/USD"),
        "close": _num(data, "close", "price"),
        "open": _num(data, "open"),
        "high": _num(data, "high"),
        "low": _num(data, "low"),
        "previous_close": _num(data, "previous_close"),
        "change": _num(data, "change"),
        "percent_change": _num(data, "percent_change"),
        "datetime": data.get("datetime"),
    }


@router.get("/xau/ohlc")
async def get_xau_ohlc(
    interval: str = Query("1h", description="Twelve Data interval"),
    outputsize: int = Query(120, ge=10, le=500),
):
    if interval not in ALLOWED_INTERVALS:
        interval = "1h"
    data = await twelve_data.get_xau_time_series(interval, outputsize)
    if data.get("error") or data.get("status") == "error":
        return {"symbol": "XAU/USD", "interval": interval, "values": [], "error": data.get("error", "Unknown error")}
    values = []
    for bar in data.get("values") or []:
        values.append({
            "datetime": bar.get("datetime"),
            "open": float(bar.get("open", 0)),
            "high": float(bar.get("high", 0)),
            "low": float(bar.get("low", 0)),
            "close": float(bar.get("close", 0)),
        })
    return {"symbol": "XAU/USD", "interval": interval, "values": values}
