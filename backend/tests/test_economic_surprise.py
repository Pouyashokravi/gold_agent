import pytest

from app.services.economic_surprise import (
    assess_release,
    classify_surprise_magnitude,
    compute_surprise_factor,
    interpret_for_gold,
)
from app.services.news_impact import compute_surprise_factor as impact_surprise_factor


def test_no_surprise_without_forecast():
    result = assess_release("cpi", actual=3.4, forecast=None, previous=3.2)
    assert result.surprise_measurable is False
    assert result.surprise_delta is None


def test_no_surprise_without_actual():
    result = assess_release("cpi", actual=None, forecast=3.0, previous=3.2)
    assert result.surprise_measurable is False


def test_cpi_above_forecast_bearish_gold():
    result = assess_release("cpi", actual=3.4, forecast=3.0, previous=3.2)
    assert result.surprise_measurable is True
    assert result.surprise_direction == "ABOVE"
    assert result.surprise_gold_bias == "BEARISH"
    assert result.surprise_magnitude in ("MEDIUM", "LARGE", "EXTREME")


def test_fed_larger_cut_bullish_gold():
    result = assess_release("fed_rate", actual=4.5, forecast=4.75, previous=5.0)
    assert result.surprise_measurable is True
    assert result.surprise_direction == "BELOW"
    assert result.surprise_gold_bias == "BULLISH"


def test_surprise_magnitude_classification():
    assert classify_surprise_magnitude(0.05, "cpi") == "LOW"
    assert classify_surprise_magnitude(0.15, "cpi") == "MEDIUM"
    assert classify_surprise_magnitude(0.35, "cpi") == "EXTREME"


def test_surprise_factor_mapping():
    assert compute_surprise_factor("EXTREME") == 0.95
    assert compute_surprise_factor(None) == 0.0
    assert impact_surprise_factor("LARGE") == 0.75


def test_nfp_interpretation():
    _, bias, mechanism = interpret_for_gold("nfp", "ABOVE", "LARGE")
    assert bias == "BEARISH"
    assert len(mechanism) >= 2
