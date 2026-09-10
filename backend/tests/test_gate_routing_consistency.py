"""Focused routing consistency: price→FAST, analyse→CLARIFY, FAST fail stays FAST."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db import sqlite as sqlite_mod
from app.db.sqlite import init_db
from app.schemas.common import Horizon, Intent
from app.schemas.conversation_gate import (
    AnalysisScope,
    ContextRelationship,
    ConversationGateLLMOutput,
    ConversationGateOutput,
)
from app.schemas.manager import ComplexityLevel, GateRoute
from app.services.conversation_gate import (
    GateValidationError,
    enforce_gate_consistency,
    postprocess_gate_output,
    run_conversation_gate,
    validate_gate_output,
)


@pytest.fixture
async def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "routing_consistency.db"
    monkeypatch.setattr(sqlite_mod, "DB_PATH", str(db_path))
    await init_db()
    return str(db_path)


def test_coherent_fast_quote_package_validates():
    raw = ConversationGateOutput(
        action=GateRoute.FAST,
        intent=Intent.PRICE_QUERY,
        fast_kind="quote",
        context_relationship=ContextRelationship.INDEPENDENT,
        confidence=0.9,
        reason="current price",
    )
    out = validate_gate_output(postprocess_gate_output(raw, None, "What is the current XAU/USD price?", {}))
    assert out.action == GateRoute.FAST
    assert out.fast_kind == "quote"


def test_stray_fast_kind_does_not_force_fast_action():
    raw = ConversationGateOutput(
        action=GateRoute.STANDARD,
        intent=Intent.MARKET_OUTLOOK,
        analysis_scopes=[
            AnalysisScope.FUNDAMENTAL,
            AnalysisScope.TECHNICAL,
            AnalysisScope.NEWS,
        ],
        horizon=Horizon.SHORT_TERM,
        fast_kind="quote",
        normalized_query="analyse gold Focus on FUNDAMENTAL+TECHNICAL+NEWS. Time horizon: short_term.",
        confidence=0.9,
        reason="inconsistent contamination",
    )
    out = enforce_gate_consistency(raw)
    assert out.action == GateRoute.STANDARD


def test_analyse_gold_standard_without_analysis_signal_is_invalid():
    """Bare STANDARD without established analysis request must not become CLARIFY."""
    raw = ConversationGateOutput(
        action=GateRoute.STANDARD,
        normalized_query="analyse gold",
        confidence=0.9,
        reason="proceeded without fields",
    )
    with pytest.raises(GateValidationError):
        postprocess_gate_output(raw, None, "analyse gold", {})


def test_analyse_gold_with_analysis_intent_becomes_clarify():
    raw = ConversationGateOutput(
        action=GateRoute.STANDARD,
        intent=Intent.MARKET_OUTLOOK,
        normalized_query="analyse gold",
        confidence=0.9,
        reason="need horizon",
        missing_fields=["horizon"],
    )
    out = validate_gate_output(postprocess_gate_output(raw, None, "analyse gold", {}))
    assert out.action == GateRoute.CLARIFY
    assert "horizon" in out.missing_fields


def test_standard_with_missing_fields_list_becomes_clarify():
    """Purpose still pending after scopes+horizon are known → stay on CLARIFY."""
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {"analysis_scopes": ["TECHNICAL"], "horizon": "short_term"},
        "missing_fields": ["purpose"],
    }
    raw = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        intent=Intent.TECHNICAL_ANALYSIS,
        horizon=Horizon.SHORT_TERM,
        analysis_scopes=[AnalysisScope.TECHNICAL],
        context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
        missing_fields=["purpose"],
        clarification_question="What is the purpose of this analysis?",
        resolved_fields={"analysis_scopes": ["TECHNICAL"], "horizon": "short_term"},
        normalized_query="analyse gold technical short-term",
        confidence=0.9,
        reason="still missing purpose",
    )
    out = validate_gate_output(postprocess_gate_output(raw, pending, "analyse gold", {}))
    assert out.action == GateRoute.CLARIFY
    assert out.missing_fields == ["purpose"]


def test_complete_standard_after_pending_still_proceeds():
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {
            "analysis_scopes": ["TECHNICAL"],
            "horizon": "short_term",
            "purpose": "INVESTMENT",
        },
    }
    raw = ConversationGateOutput(
        action=GateRoute.STANDARD,
        intent=Intent.TECHNICAL_ANALYSIS,
        horizon=Horizon.SHORT_TERM,
        context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
        normalized_query=None,
        confidence=0.95,
        reason="complete",
    )
    out = validate_gate_output(postprocess_gate_output(raw, pending, "for investment", {}))
    assert out.action == GateRoute.STANDARD
    assert out.normalized_query


@pytest.mark.asyncio
async def test_mocked_llm_price_request_ends_fast(monkeypatch):
    llm_out = ConversationGateLLMOutput(
        action=GateRoute.FAST,
        intent=Intent.PRICE_QUERY,
        fast_kind="quote",
        confidence=0.95,
        reason="current price",
    )
    monkeypatch.setattr(
        "app.services.conversation_gate.Runner.run",
        AsyncMock(return_value=MagicMock(final_output=llm_out)),
    )
    monkeypatch.setattr(
        "app.services.conversation_gate.settings",
        MagicMock(openai_api_key="test", llm_timeout=30, conversation_gate_max_retries=0),
    )
    result = await run_conversation_gate(
        {"current_user_message": "What is the current XAU/USD price?"},
        query="What is the current XAU/USD price?",
        trade_mode=False,
        pending=None,
    )
    assert result.action == GateRoute.FAST
    assert result.fast_kind == "quote"


@pytest.mark.asyncio
async def test_mocked_llm_analyse_gold_clarify(monkeypatch):
    llm_out = ConversationGateLLMOutput(
        action=GateRoute.CLARIFY,
        missing_fields=["analysis_scopes", "horizon"],
        clarification_question="What type of analysis and time horizon should I use?",
        confidence=0.9,
        reason="need fields",
    )
    monkeypatch.setattr(
        "app.services.conversation_gate.Runner.run",
        AsyncMock(return_value=MagicMock(final_output=llm_out)),
    )
    monkeypatch.setattr(
        "app.services.conversation_gate.settings",
        MagicMock(openai_api_key="test", llm_timeout=30, conversation_gate_max_retries=0),
    )
    result = await run_conversation_gate(
        {"current_user_message": "analyse gold"},
        query="analyse gold",
        trade_mode=False,
        pending=None,
    )
    assert result.action == GateRoute.CLARIFY
    assert "horizon" in result.missing_fields
    assert "analysis_scopes" in result.missing_fields


@pytest.mark.asyncio
async def test_pipeline_price_fast_skips_manager(temp_db, monkeypatch):
    gate_out = ConversationGateOutput(
        action=GateRoute.FAST,
        intent=Intent.PRICE_QUERY,
        fast_kind="quote",
        complexity=ComplexityLevel.FAST,
        confidence=0.95,
        reason="quote",
    )
    monkeypatch.setattr(
        "app.services.manager_runtime.run_conversation_gate",
        AsyncMock(return_value=gate_out),
    )
    monkeypatch.setattr(
        "app.services.manager_runtime.twelve_data.get_xau_quote",
        AsyncMock(return_value={"close": 2650.5, "high": 2660, "low": 2640}),
    )
    manager = AsyncMock(side_effect=AssertionError("manager must not run"))
    monkeypatch.setattr("app.services.manager_runtime._run_agent", manager)

    from app.services.manager_runtime import run_v2_pipeline

    chunks = []
    async for c in run_v2_pipeline("What is the current XAU/USD price?", "route_price"):
        chunks.append(c)
    text = "".join(chunks)
    assert "fast_path" in text
    assert "planning_started" not in text
    assert "2650.5" in text
    manager.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_analyse_gold_clarify_skips_manager(temp_db, monkeypatch):
    gate_out = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        missing_fields=["analysis_scopes", "horizon"],
        clarification_question="What type of analysis and time horizon should I use?",
        complexity=ComplexityLevel.STANDARD,
        confidence=0.9,
        reason="need clarify",
    )
    monkeypatch.setattr(
        "app.services.manager_runtime.run_conversation_gate",
        AsyncMock(return_value=gate_out),
    )
    manager = AsyncMock(side_effect=AssertionError("manager must not run"))
    monkeypatch.setattr("app.services.manager_runtime._run_agent", manager)

    from app.services.manager_runtime import run_v2_pipeline

    chunks = []
    async for c in run_v2_pipeline("analyse gold", "route_analyse"):
        chunks.append(c)
    text = "".join(chunks)
    assert "planning_started" not in text
    assert "analysis" in text.lower() or "horizon" in text.lower()
    manager.assert_not_called()


@pytest.mark.asyncio
async def test_fast_quote_failure_does_not_run_manager(temp_db, monkeypatch):
    gate_out = ConversationGateOutput(
        action=GateRoute.FAST,
        intent=Intent.PRICE_QUERY,
        fast_kind="quote",
        complexity=ComplexityLevel.FAST,
        confidence=0.95,
        reason="quote",
    )
    monkeypatch.setattr(
        "app.services.manager_runtime.run_conversation_gate",
        AsyncMock(return_value=gate_out),
    )
    monkeypatch.setattr(
        "app.services.manager_runtime.twelve_data.get_xau_quote",
        AsyncMock(side_effect=RuntimeError("provider down")),
    )
    manager = AsyncMock(side_effect=AssertionError("manager must not run"))
    monkeypatch.setattr("app.services.manager_runtime._run_agent", manager)

    from app.services.manager_runtime import run_v2_pipeline

    chunks = []
    async for c in run_v2_pipeline("What is the current XAU/USD price?", "route_fail"):
        chunks.append(c)
    text = "".join(chunks)
    assert "fast_path" in text
    assert "planning_started" not in text
    assert "couldn't retrieve" in text.lower() or "could not retrieve" in text.lower()
    manager.assert_not_called()
