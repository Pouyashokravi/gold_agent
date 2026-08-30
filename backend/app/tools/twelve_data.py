import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import settings
from app.tools.cache import cache

logger = logging.getLogger(__name__)

BASE_URL = "https://api.twelvedata.com"
SYMBOL = "XAU/USD"


async def _request(endpoint: str, params: dict[str, Any] | None = None, ttl: int = 60) -> dict[str, Any]:
    if settings.mock_external_apis:
        return {"status": "ok", "mock": True, "endpoint": endpoint}

    params = dict(params or {})
    cache_key = f"td:{endpoint}:{json.dumps(params, sort_keys=True)}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    params["symbol"] = SYMBOL
    params["apikey"] = settings.twelve_data_api_key

    last_error: Exception | None = None
    for _ in range(2):
        try:
            async with httpx.AsyncClient(timeout=settings.twelve_data_timeout) as client:
                resp = await client.get(f"{BASE_URL}{endpoint}", params=params)
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") == "error":
                    return {"error": data.get("message", "Twelve Data error"), "status": "error"}
                await cache.set(cache_key, data, ttl)
                return data
        except Exception as exc:
            last_error = exc
    return {"error": str(last_error), "status": "error"}


async def get_xau_quote() -> dict[str, Any]:
    return await _request("/quote", ttl=settings.cache_quote_ttl)


async def get_xau_time_series(interval: str = "1h", outputsize: int = 100) -> dict[str, Any]:
    ttl = settings.cache_ohlc_1m_ttl if interval in {"1min", "5min"} else settings.cache_ohlc_15m_ttl
    if interval in {"1day", "1week", "1month"}:
        ttl = settings.cache_ohlc_daily_ttl
    return await _request("/time_series", {"interval": interval, "outputsize": outputsize}, ttl=ttl)


async def _indicator(name: str, interval: str = "1h", **extra: Any) -> dict[str, Any]:
    params = {"interval": interval, **extra}
    return await _request(f"/{name}", params, ttl=settings.cache_ohlc_15m_ttl)


async def get_xau_rsi(interval: str = "1h", time_period: int = 14) -> dict[str, Any]:
    return await _indicator("rsi", interval, time_period=time_period)


async def get_xau_sma(interval: str = "1h", time_period: int = 20) -> dict[str, Any]:
    return await _indicator("sma", interval, time_period=time_period)


async def get_xau_ema(interval: str = "1h", time_period: int = 20) -> dict[str, Any]:
    return await _indicator("ema", interval, time_period=time_period)


async def get_xau_macd(interval: str = "1h") -> dict[str, Any]:
    return await _indicator("macd", interval)


async def get_xau_atr(interval: str = "1h", time_period: int = 14) -> dict[str, Any]:
    return await _indicator("atr", interval, time_period=time_period)
