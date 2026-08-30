import uuid
from datetime import UTC, datetime

from app.schemas.common import Horizon
from app.schemas.news import NewsAgentOutput, NewsEvent
from app.services.economic_surprise import enrich_news_event
from app.services.news_impact import DEFAULT_HORIZON_IMPACT, classify_importance, compute_impact_score
from app.tools import tavily


async def build_news_fallback(payload: dict) -> NewsAgentOutput:
    query = f"XAU/USD gold market news today {payload.get('query', '')}"[:400]
    depth = payload.get("depth", "STANDARD")
    data = await tavily.search_news_with_tavily(query, depth)

    events: list[NewsEvent] = []
    results = data.get("results") or []

    for item in results[:6]:
        title = item.get("title") or "Market headline"
        summary = (item.get("content") or "")[:600]
        gold_rel = 0.75 if any(w in title.lower() + summary.lower() for w in ("gold", "xau", "fed", "rate", "inflation")) else 0.5
        enriched = enrich_news_event(
            event_type="other_macro_event",
            actual=None,
            forecast=None,
            previous=None,
            base_importance=classify_importance(0.5),
            gold_relevance=gold_rel,
            event_importance=0.6,
            magnitude=0.5,
            persistence=0.5,
            source_confidence=0.6,
        )
        impact = enriched["impact_score"]
        events.append(NewsEvent(
            event_id=str(uuid.uuid4())[:8],
            event_type="other_macro_event",
            title=title,
            summary=summary or title,
            importance=enriched["importance"],
            gold_relevance=gold_rel,
            impact_score=impact,
            direction="NEUTRAL",
            mechanism=["market sentiment"],
            impact_by_horizon=DEFAULT_HORIZON_IMPACT,
            confidence=0.55,
            source_ids=[],
        ))

    horizon_raw = payload.get("horizon", "few_days")
    try:
        horizon = Horizon(horizon_raw)
    except ValueError:
        horizon = Horizon.FEW_DAYS

    if data.get("error"):
        return NewsAgentOutput(
            direction="NEUTRAL",
            confidence=0.3,
            horizon=horizon,
            drivers=["News retrieval limited"],
            risks=[str(data.get("error"))],
            events=[],
            evidence=[],
            sources=[],
            timestamp=datetime.now(UTC),
            freshness="FRESH",
        )

    drivers = [e.title for e in events[:3]] or ["Recent gold-related headlines"]
    return NewsAgentOutput(
        direction="NEUTRAL",
        confidence=0.65 if events else 0.35,
        horizon=horizon,
        drivers=drivers,
        risks=["Headline risk can shift quickly"],
        events=events,
        evidence=[],
        sources=[],
        timestamp=datetime.now(UTC),
        freshness="FRESH",
    )
