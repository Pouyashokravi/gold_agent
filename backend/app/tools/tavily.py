import json
import logging
from typing import Any

from app.config import settings
from app.db.repositories import get_tavily_usage, increment_tavily_usage
from app.tools.cache import cache

logger = logging.getLogger(__name__)

TAVILY_BUDGET = {"LIGHT": 1, "STANDARD": 2, "DEEP": 2}


class TavilyBudgetExceeded(Exception):
    pass


async def search_economic_releases(
    query: str,
    depth_level: str = "STANDARD",
) -> dict[str, Any]:
    """Search for economic release headlines with actual vs forecast data."""
    economic_query = f"XAU gold economic data actual vs forecast {query}"[:400]
    return await search_news_with_tavily(economic_query, depth_level)


async def search_news_with_tavily(
    query: str,
    depth_level: str = "STANDARD",
    request_id: str = "",
) -> dict[str, Any]:
    if not settings.tavily_enabled:
        return {"error": "Tavily disabled", "status": "error"}

    if settings.mock_external_apis:
        return {
            "status": "ok",
            "mock": True,
            "results": [
                {
                    "title": "Gold rises on Fed expectations",
                    "url": "https://example.com/gold",
                    "content": "XAU/USD gained on lower rate expectations.",
                }
            ],
        }

    monthly = await get_tavily_usage()
    if monthly >= settings.tavily_monthly_budget:
        return {"error": "Monthly Tavily budget exceeded", "status": "error"}

    cache_key = f"tavily:{query}:{depth_level}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    from tavily import AsyncTavilyClient

    client = AsyncTavilyClient(api_key=settings.tavily_api_key)
    last_error: Exception | None = None
    for _ in range(2):
        try:
            response = await client.search(
                query=query[:400],
                topic="news",
                search_depth=settings.tavily_search_depth,
                max_results=settings.tavily_max_results,
            )
            await increment_tavily_usage()
            await cache.set(cache_key, response, settings.cache_tavily_ttl)
            return response
        except Exception as exc:
            last_error = exc
    return {"error": str(last_error), "status": "error"}


def tavily_budget_for_depth(depth: str) -> int:
    return TAVILY_BUDGET.get(depth, 1)
