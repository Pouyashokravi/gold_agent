import json
import logging
from typing import Any

import httpx

from app.config import settings
from app.tools.cache import cache

logger = logging.getLogger(__name__)

BASE_URL = "https://api.stlouisfed.org/fred"

FRED_SERIES = {
    "DFF": "Federal Funds Effective Rate",
    "DGS2": "2-Year Treasury Yield",
    "DGS10": "10-Year Treasury Yield",
    "DFII5": "5-Year Real Yield",
    "DFII10": "10-Year Real Yield",
    "CPIAUCSL": "CPI",
    "CPILFESL": "Core CPI",
    "PCEPI": "PCE Price Index",
    "PCEPILFE": "Core PCE",
    "UNRATE": "Unemployment Rate",
    "PAYEMS": "Nonfarm Payroll Employment",
}


async def get_fred_series(
    series_id: str,
    observation_start: str | None = None,
    observation_end: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    if series_id not in FRED_SERIES:
        return {"error": f"Series {series_id} not in allowlist", "status": "error"}

    if settings.mock_external_apis:
        return {
            "status": "ok",
            "mock": True,
            "series_id": series_id,
            "observations": [{"date": "2025-01-01", "value": "4.5"}],
        }

    params: dict[str, Any] = {
        "series_id": series_id,
        "api_key": settings.fred_api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    if observation_start:
        params["observation_start"] = observation_start
    if observation_end:
        params["observation_end"] = observation_end

    cache_key = f"fred:{json.dumps(params, sort_keys=True)}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    last_error: Exception | None = None
    for _ in range(2):
        try:
            async with httpx.AsyncClient(timeout=settings.fred_timeout) as client:
                resp = await client.get(f"{BASE_URL}/series/observations", params=params)
                resp.raise_for_status()
                data = resp.json()
                await cache.set(cache_key, data, settings.cache_fred_ttl)
                return data
        except Exception as exc:
            last_error = exc
    return {"error": str(last_error), "status": "error"}


async def get_macro_snapshot() -> dict[str, Any]:
    keys = ["DFF", "DGS2", "DGS10", "DFII10", "CPIAUCSL", "CPILFESL"]
    result: dict[str, Any] = {}
    for key in keys:
        data = await get_fred_series(key, limit=5)
        obs = data.get("observations", [])
        latest = obs[0] if obs else {}
        result[key.lower()] = {
            "series_id": key,
            "name": FRED_SERIES[key],
            "latest_date": latest.get("date"),
            "latest_value": latest.get("value"),
            "observations": obs[:5],
        }
    return result
