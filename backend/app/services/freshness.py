from datetime import UTC, datetime, timedelta

from app.schemas.common import Freshness


def classify_freshness(stored_at: str, short_term: bool = True) -> Freshness:
    ts = datetime.fromisoformat(stored_at.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    age = datetime.now(UTC) - ts
    if short_term:
        if age < timedelta(minutes=15):
            return "FRESH"
        if age < timedelta(minutes=60):
            return "ACCEPTABLE"
        return "STALE"
    if age < timedelta(hours=6):
        return "FRESH"
    if age < timedelta(hours=24):
        return "ACCEPTABLE"
    return "STALE"


FRESHNESS_WEIGHT: dict[Freshness, float] = {"FRESH": 1.0, "ACCEPTABLE": 0.6, "STALE": 0.0}
