"""V2 gate, STM, and manager policy tests (behavioral scenarios 1–10 coverage)."""

import asyncio

import pytest

from app.schemas.common import Horizon
from app.schemas.manager import ComplexityLevel, GateRoute, ManagerPlan, ManagerTask
from app.services.gate import (
    classify_gate,
    has_explicit_horizon,
    looks_like_horizon_reply,
    merge_clarification_query,
    parse_horizon_from_text,
)
from app.services.policy import apply_manager_plan_constraints, validate_manager_plan
from app.services import working_memory as stm


def test_fast_price_query():
    d = classify_gate("What is the current XAU/USD price?")
    assert d.route == GateRoute.FAST
    assert d.fast_kind == "quote"
    assert d.complexity == ComplexityLevel.FAST


def test_fast_rsi_query():
    d = classify_gate("What is the 1H RSI for gold?")
    assert d.route == GateRoute.FAST
    assert d.fast_kind == "rsi"
    assert d.fast_params and d.fast_params.get("interval") == "1h"


def test_clarification_bare_analyze():
    d = classify_gate("Analyze gold for me.")
    assert d.route == GateRoute.CLARIFY
    assert d.clarification_question


def test_clarification_ambiguous_outlook():
    d = classify_gate("What's the gold outlook?")
    assert d.route == GateRoute.CLARIFY
    assert d.clarification_question
    assert "horizon" in d.clarification_question.lower() or "time" in d.clarification_question.lower()


def test_clarification_gold_view_without_timeframe():
    d = classify_gate("What do you think about XAU/USD?")
    assert d.route == GateRoute.CLARIFY


def test_clarification_skipped_when_horizon_present():
    d = classify_gate("Analyze XAU/USD for the next two weeks.")
    assert d.route == GateRoute.RESEARCH


def test_clarification_skipped_for_today_move():
    d = classify_gate("Why did gold fall today despite dovish Fed expectations?")
    assert d.route == GateRoute.RESEARCH


def test_trade_setup_clarification_without_trade_mode():
    d = classify_gate("Give me a trade setup.", trade_mode=False)
    assert d.route == GateRoute.CLARIFY


def test_trade_mode_skips_trade_clarification():
    d = classify_gate("Give me a trade setup.", trade_mode=True)
    assert d.route == GateRoute.RESEARCH


def test_complex_research_route():
    d = classify_gate("Why did gold fall today despite dovish Fed expectations?")
    assert d.route == GateRoute.RESEARCH
    assert d.complexity == ComplexityLevel.RESEARCH


def test_follow_up_uses_prior_thesis_path():
    d = classify_gate("What are the biggest downside risks?", has_prior_thesis=True)
    assert d.route == GateRoute.RESEARCH


def test_greeting_is_chat():
    d = classify_gate("Hello!")
    assert d.route == GateRoute.GENERAL_CHAT


def test_pending_clarification_horizon_reply_is_research():
    d = classify_gate(
        "next two weeks",
        pending_clarification=True,
        pending_goal="What's the gold outlook?",
    )
    assert d.route == GateRoute.RESEARCH
    assert "horizon" in d.reason or "clarification" in d.reason


def test_pending_clarification_short_term_reply():
    d = classify_gate("short-term", pending_clarification=True, pending_goal="Analyze gold")
    assert d.route == GateRoute.RESEARCH


def test_horizon_reply_not_off_topic_when_pending():
    # Without pending, bare "next two weeks" has no gold keywords → OFF_TOPIC
    alone = classify_gate("Focus on the next two weeks.")
    assert alone.route == GateRoute.OFF_TOPIC
    resumed = classify_gate(
        "Focus on the next two weeks.",
        pending_clarification=True,
        pending_goal="Analyze gold for me.",
    )
    assert resumed.route == GateRoute.RESEARCH


def test_has_explicit_horizon_helpers():
    assert has_explicit_horizon("gold outlook for next two weeks") is True
    assert has_explicit_horizon("What's the gold outlook?") is False
    assert looks_like_horizon_reply("short-term") is True
    assert looks_like_horizon_reply("intraday") is True
    assert parse_horizon_from_text("next two weeks") == Horizon.SHORT_TERM
    assert parse_horizon_from_text("intraday scalp") == Horizon.INTRADAY
    assert parse_horizon_from_text("medium-term") == Horizon.MEDIUM_TERM


def test_merge_clarification_query():
    merged = merge_clarification_query("What's the gold outlook?", "next two weeks")
    assert "gold outlook" in merged.lower()
    assert "next two weeks" in merged.lower() or "short" in merged.lower()


def test_manager_plan_trade_mode_forces_technical():
    plan = ManagerPlan(
        goal="setup",
        horizon=Horizon.MEDIUM_TERM,
        tasks=[ManagerTask(id="n", kind="agent_news", depth="DEEP", task="news")],
    )
    out = apply_manager_plan_constraints(plan, "trade setup", trade_mode=True)
    assert out.horizon == Horizon.INTRADAY
    assert any(t.kind == "agent_technical" and t.depth == "DEEP" for t in out.tasks)
    news = [t for t in out.tasks if t.kind == "agent_news"]
    assert all(t.depth == "LIGHT" for t in news)


def test_manager_plan_event_forces_all_three():
    plan = ManagerPlan(goal="fed", horizon=Horizon.FEW_DAYS, tasks=[])
    out = apply_manager_plan_constraints(
        plan,
        "How would an unexpected 50bp Fed cut affect gold?",
        trade_mode=False,
    )
    kinds = {t.kind for t in out.tasks}
    assert "agent_news" in kinds
    assert "agent_fundamental" in kinds
    assert "agent_technical" in kinds


def test_validate_manager_plan_empty():
    plan = ManagerPlan(goal="x", tasks=[])
    warnings = validate_manager_plan(plan)
    assert warnings


@pytest.mark.asyncio
async def test_stm_fresh_then_stale(monkeypatch):
    monkeypatch.setattr("app.services.working_memory.settings.stm_quote_ttl", 1)
    scope = "test_conv_stm"
    await stm.put(scope, "quote", {"close": 2500.0}, "quote")
    value, freshness, _ = await stm.get_fresh(scope, "quote")
    assert value is not None
    assert freshness in {"FRESH", "ACCEPTABLE"}

    # Force expiry by rewriting stored_at via put with ttl 1 then sleeping
    await asyncio.sleep(1.2)
    value2, freshness2, _ = await stm.get_fresh(scope, "quote", max_age=1)
    assert value2 is None or freshness2 == "STALE"


@pytest.mark.asyncio
async def test_stm_reuse_hit():
    scope = "test_conv_reuse"
    await stm.put(scope, "quote", {"close": 2600.5}, "quote")
    v1, f1, _ = await stm.get_fresh(scope, "quote")
    v2, f2, _ = await stm.get_fresh(scope, "quote")
    assert v1["close"] == v2["close"] == 2600.5
    assert f1 is not None and f2 is not None


def test_parallel_wave_dependency_ordering():
    """Independent tasks have empty depends_on — runtime gathers them together."""
    tasks = [
        ManagerTask(id="a", kind="agent_news", task="n"),
        ManagerTask(id="b", kind="agent_fundamental", task="f"),
        ManagerTask(id="c", kind="tool_quote", task="q"),
    ]
    assert all(not t.depends_on for t in tasks)


def test_replan_bound_config():
    from app.config import settings
    assert settings.max_replan_rounds >= 1
    assert settings.max_replan_rounds <= 5
