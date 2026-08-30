from app.schemas.common import Horizon, Intent, ResearchDepth
from app.schemas.planner import AgentTask, GoldPlannerOutput
from app.schemas.query import QueryUnderstandingOutput
from app.services.policy import (
    _is_trade_query,
    apply_horizon_overrides,
    apply_intent_overrides,
    apply_routing_overrides,
)


def _base_profile(**kwargs) -> QueryUnderstandingOutput:
    defaults = {
        "intents": [Intent.TECHNICAL_ANALYSIS],
        "horizon": Horizon.MEDIUM_TERM,
        "requested_depth": ResearchDepth.STANDARD,
    }
    defaults.update(kwargs)
    return QueryUnderstandingOutput(**defaults)


def _base_plan() -> GoldPlannerOutput:
    off = AgentTask(enabled=False, depth="OFF", task="", focus=[])
    return GoldPlannerOutput(
        news_agent=off.model_copy(),
        fundamental_agent=off.model_copy(),
        technical_agent=AgentTask(enabled=True, depth="STANDARD", task="", focus=[]),
        execution_mode="PARALLEL",
    )


FED_QUERY = (
    "How would an unexpected 50 basis point Federal Reserve rate cut affect "
    "XAU/USD in the intraday, short-term, and medium-term horizons?"
)


def test_short_term_does_not_trigger_trade_routing():
    intents = {Intent.MARKET_OUTLOOK}
    assert _is_trade_query(FED_QUERY, intents) is False


def test_fed_event_query_enables_news_and_fundamental():
    profile = _base_profile(intents=[Intent.TECHNICAL_ANALYSIS])
    profile = apply_intent_overrides(profile, FED_QUERY)
    plan = _base_plan()
    plan = apply_routing_overrides(plan, profile, FED_QUERY)

    assert plan.news_agent.enabled is True
    assert plan.fundamental_agent.enabled is True
    assert plan.technical_agent.enabled is True
    assert plan.news_agent.depth != "OFF"
    assert plan.fundamental_agent.depth != "OFF"


def test_fed_query_does_not_force_intraday_horizon():
    profile = _base_profile(intents=[Intent.EVENT_IMPACT], horizon=Horizon.MEDIUM_TERM)
    updated = apply_horizon_overrides(profile, FED_QUERY)
    assert updated.horizon == Horizon.MEDIUM_TERM


def test_fed_query_bumps_intraday_to_medium_when_multi_horizon():
    profile = _base_profile(intents=[Intent.EVENT_IMPACT], horizon=Horizon.INTRADAY)
    updated = apply_horizon_overrides(profile, FED_QUERY)
    assert updated.horizon == Horizon.MEDIUM_TERM


def test_price_only_routes_technical_only():
    price_query = "XAU/USD price?"
    profile = _base_profile(intents=[Intent.PRICE_QUERY, Intent.TECHNICAL_ANALYSIS])
    plan = _base_plan()
    plan = apply_routing_overrides(plan, profile, price_query)

    assert plan.technical_agent.enabled is True
    assert plan.news_agent.enabled is False
    assert plan.fundamental_agent.enabled is False


def test_real_trade_query_still_routes_technical_only():
    trade_query = "give me a gold buy setup with entry and stop loss"
    profile = _base_profile(intents=[Intent.TRADE_ANALYSIS])
    plan = _base_plan()
    plan = apply_routing_overrides(plan, profile, trade_query)

    assert plan.technical_agent.enabled is True
    assert plan.news_agent.enabled is False
    assert plan.fundamental_agent.enabled is False
