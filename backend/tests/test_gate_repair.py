"""Regression tests for Gate normalized_query repair, strict output, and fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.common import Horizon, Intent
from app.schemas.conversation_gate import (
    AnalysisPurpose,
    ContextRelationship,
    ConversationGateLLMOutput,
    ConversationGateOutput,
)
from app.schemas.manager import ComplexityLevel, GateRoute
from app.services.conversation_gate import (
    build_emergency_fallback,
    postprocess_gate_output,
    repair_normalized_query,
    run_conversation_gate,
    validate_gate_output,
)
from app.services.gate import HORIZON_CLARIFY_QUESTION


def test_standard_missing_normalized_query_repaired_locally():
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {
            "analysis_scopes": ["TECHNICAL"],
            "horizon": "short_term",
            "purpose": "INVESTMENT",
        },
        "missing_fields": [],
    }
    decision = ConversationGateOutput(
        action=GateRoute.STANDARD,
        intent=Intent.TECHNICAL_ANALYSIS,
        purpose=AnalysisPurpose.INVESTMENT,
        horizon=Horizon.SHORT_TERM,
        context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
        resolved_fields=dict(pending["resolved_fields"]),
        normalized_query=None,
        confidence=0.9,
        reason="ready",
    )
    repaired = repair_normalized_query(
        decision, pending, "for investment", {}, allow_pending_merge=True
    )
    validated = validate_gate_output(repaired)
    assert validated.normalized_query
    assert "analyse gold" in validated.normalized_query.lower()
    assert "TECHNICAL" in validated.normalized_query


def test_research_missing_normalized_query_repaired_locally():
    pending = {
        "original_query": "gold outlook",
        "resolved_fields": {
            "horizon": "long_term",
            "analysis_scopes": ["FUNDAMENTAL", "TECHNICAL", "NEWS"],
        },
    }
    decision = ConversationGateOutput(
        action=GateRoute.RESEARCH,
        intent=Intent.MARKET_OUTLOOK,
        horizon=Horizon.LONG_TERM,
        resolved_fields={
            "horizon": "long_term",
            "analysis_scopes": ["FUNDAMENTAL", "TECHNICAL", "NEWS"],
        },
        complexity=ComplexityLevel.RESEARCH,
        normalized_query="",
        confidence=0.9,
        reason="research",
    )
    repaired = repair_normalized_query(decision, pending, "for 1 year", {})
    validated = validate_gate_output(repaired)
    assert validated.action == GateRoute.RESEARCH
    assert validated.normalized_query


def test_strict_llm_output_parses():
    raw = ConversationGateLLMOutput(
        action=GateRoute.CLARIFY,
        missing_fields=["horizon"],
        clarification_question="What time horizon should I use?",
        confidence=0.9,
        reason="need horizon",
    )
    out = ConversationGateOutput.model_validate(raw.model_dump())
    assert out.action == GateRoute.CLARIFY
    assert out.missing_fields == ["horizon"]


@pytest.mark.asyncio
async def test_llm_called_once_for_repairable_validation(monkeypatch):
    llm_out = ConversationGateLLMOutput(
        action=GateRoute.STANDARD,
        intent=Intent.TECHNICAL_ANALYSIS,
        horizon=Horizon.SHORT_TERM,
        context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
        normalized_query=None,
        confidence=0.9,
        reason="proceed",
    )
    run_mock = AsyncMock(return_value=MagicMock(final_output=llm_out))
    monkeypatch.setattr("app.services.conversation_gate.Runner.run", run_mock)
    monkeypatch.setattr("app.services.conversation_gate.settings", MagicMock(
        openai_api_key="test",
        llm_timeout=30,
        conversation_gate_max_retries=1,
    ))

    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {
            "analysis_scopes": ["TECHNICAL"],
            "horizon": "short_term",
            "purpose": "INVESTMENT",
        },
    }
    result = await run_conversation_gate(
        {"current_user_message": "for investment", "AUTHORITATIVE_CURRENT_USER_MESSAGE": "for investment"},
        query="for investment",
        trade_mode=False,
        pending=pending,
    )
    assert run_mock.call_count == 1
    assert result.action == GateRoute.STANDARD
    assert result.normalized_query


def test_emergency_fallback_horizon_for_one_year_not_reasked():
    pending = {
        "original_query": "what is gold outlook",
        "resolved_fields": {
            "analysis_scopes": ["FUNDAMENTAL", "TECHNICAL", "NEWS"],
            "intent": "market_outlook",
        },
        "missing_fields": ["horizon"],
        "previous_clarification_question": "What time horizon should I use?",
    }
    result = build_emergency_fallback(
        "for 1 year",
        pending=pending,
        trade_mode=False,
        context={"current_user_message": "for 1 year"},
    )
    assert result.resolved_fields.get("horizon") == "long_term"
    assert "horizon" not in (result.missing_fields or [])
    if result.action == GateRoute.CLARIFY:
        assert HORIZON_CLARIFY_QUESTION not in (result.clarification_question or "")
        assert "horizon" not in (result.clarification_question or "").lower() or "purpose" in (
            result.clarification_question or ""
        ).lower()
    else:
        assert result.action in {GateRoute.STANDARD, GateRoute.RESEARCH}


def test_emergency_fallback_asks_only_remaining_fields():
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {"analysis_scopes": ["TECHNICAL"], "horizon": "short_term"},
        "missing_fields": ["purpose"],
        "previous_clarification_question": "What time horizon and purpose should I use?",
    }
    result = build_emergency_fallback(
        "for investment",
        pending=pending,
        trade_mode=False,
        context={},
    )
    assert result.action in {GateRoute.STANDARD, GateRoute.RESEARCH, GateRoute.CLARIFY}
    if result.action == GateRoute.CLARIFY:
        q = (result.clarification_question or "").lower()
        assert "horizon" not in q
        assert "type of analysis" not in q
    else:
        assert result.resolved_fields.get("purpose") == "INVESTMENT"


def test_static_horizon_question_not_repeated_after_progress():
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {"analysis_scopes": ["TECHNICAL"]},
        "missing_fields": ["horizon", "purpose"],
        "previous_clarification_question": HORIZON_CLARIFY_QUESTION,
    }
    llm = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
        horizon=Horizon.SHORT_TERM,
        resolved_fields={"analysis_scopes": ["TECHNICAL"], "horizon": "short_term"},
        missing_fields=["purpose"],
        clarification_question=HORIZON_CLARIFY_QUESTION,
        confidence=0.9,
        reason="bad repeat",
    )
    result = postprocess_gate_output(llm, pending, "in short time", {})
    assert result.clarification_question != HORIZON_CLARIFY_QUESTION
    assert "horizon" not in result.clarification_question.lower()
    assert "purpose" in result.clarification_question.lower()
