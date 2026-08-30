from app.schemas.routing import IntentRouterOutput, MessageRoute
from app.services.policy import _contains_gold_keyword


def test_message_route_enum_values():
    assert MessageRoute.RESEARCH.value == "research"
    assert MessageRoute.GENERAL_CHAT.value == "general_chat"
    assert MessageRoute.OFF_TOPIC.value == "off_topic"


def test_intent_router_output_schema():
    output = IntentRouterOutput(
        route=MessageRoute.GENERAL_CHAT,
        confidence=0.92,
        reason="greeting only",
    )
    assert output.route == MessageRoute.GENERAL_CHAT
    assert output.confidence == 0.92
    assert output.reason == "greeting only"


def test_contains_gold_keyword_detects_research_terms():
    assert _contains_gold_keyword("what is the gold price today") is True
    assert _contains_gold_keyword("gold technical analysis") is True
    assert _contains_gold_keyword("how are you") is False
    assert _contains_gold_keyword("best football team") is False


def test_router_fallback_logic():
    """Simulate orchestrator fallback when router fails."""
    query_research = "XAU/USD outlook"
    query_chat = "how are you"

    fallback_research = MessageRoute.RESEARCH if _contains_gold_keyword(query_research) else MessageRoute.GENERAL_CHAT
    fallback_chat = MessageRoute.RESEARCH if _contains_gold_keyword(query_chat) else MessageRoute.GENERAL_CHAT

    assert fallback_research == MessageRoute.RESEARCH
    assert fallback_chat == MessageRoute.GENERAL_CHAT
