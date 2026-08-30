import pytest

from app.services.news_impact import classify_importance, compute_impact_score
from app.services.freshness import classify_freshness


def test_impact_score():
    score = compute_impact_score(0.9, 0.8, 0.7, 0.6, 0.5, 0.8)
    assert 0 <= score <= 1


def test_importance_critical():
    assert classify_importance(0.9) == "CRITICAL"


def test_freshness_stale():
    from datetime import UTC, datetime, timedelta
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    assert classify_freshness(old, short_term=True) == "STALE"
