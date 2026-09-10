"""Focused Gate independent-message, pending relationship, and emergency fallback tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db import repositories
from app.db import sqlite as sqlite_mod
from app.db.sqlite import init_db
from app.schemas.common import Horizon, Intent
from app.schemas.conversation_gate import (
    AnalysisScope,
    ContextRelationship,
    ConversationGateLLMOutput,
    ConversationGateOutput,
    NewlyResolvedFields,
)
from app.schemas.manager import ComplexityLevel, GateRoute, ManagerPlan, ManagerTask
from app.services.conversation_gate import (
    CLARIFICATION_LIMIT_MESSAGE,
    apply_clarification_limit,
    build_emergency_fallback,
    enforce_gate_consistency,
    gate_diagnostics,
    postprocess_gate_output,
    run_conversation_gate,
    validate_gate_output,
    GateValidationError,
)


@pytest.fixture
async def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "independent_gate.db"
    monkeypatch.setattr(sqlite_mod, "DB_PATH", str(db_path))
    await init_db()
    return str(db_path)


def test_invalid_fast_does_not_default_to_quote():
    raw = ConversationGateOutput(
        action=GateRoute.FAST,
        intent=None,
        fast_kind=None,
        context_relationship=ContextRelationship.INDEPENDENT,
        confidence=0.8,
        reason="incomplete fast",
    )
    with pytest.raises(GateValidationError):
        validate_gate_output(raw)


def test_stray_price_query_does_not_force_fast():
    raw = ConversationGateOutput(
        action=GateRoute.GENERAL_CHAT,
        intent=Intent.PRICE_QUERY,
        fast_kind="quote",
        context_relationship=ContextRelationship.INDEPENDENT,
        confidence=0.9,
        reason="greeting contaminated",
    )
    out = enforce_gate_consistency(raw)
    assert out.action == GateRoute.GENERAL_CHAT


def test_zero_conf_blank_reason_standard_not_clarify():
    raw = ConversationGateOutput(
        action=GateRoute.STANDARD,
        context_relationship=ContextRelationship.INDEPENDENT,
        confidence=0.0,
        reason="",
        normalized_query="hi",
    )
    with pytest.raises(GateValidationError):
        postprocess_gate_output(raw, None, "hi", {})


def test_greeting_during_pending_is_independent_chat():
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {},
        "missing_fields": ["analysis_scopes", "horizon"],
        "previous_clarification_question": "What type of analysis and time horizon should I use?",
    }
    raw = ConversationGateOutput(
        action=GateRoute.GENERAL_CHAT,
        context_relationship=ContextRelationship.INDEPENDENT,
        confidence=0.9,
        reason="greeting",
    )
    out = validate_gate_output(postprocess_gate_output(raw, pending, "hi", {}))
    assert out.action == GateRoute.GENERAL_CHAT
    assert out.resolved_fields == {}
    assert out.is_follow_up is False


def test_clarification_answer_fundamental_asks_horizon_only():
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {},
        "missing_fields": ["analysis_scopes", "horizon"],
        "previous_clarification_question": "What type of analysis and time horizon should I use?",
    }
    # LLM marks clarification answer; scopes come via newly_resolved_fields (no fragment extraction)
    raw = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
        newly_resolved_fields=NewlyResolvedFields(
            intent=Intent.FUNDAMENTAL_ANALYSIS,
            analysis_scopes=[AnalysisScope.FUNDAMENTAL],
        ),
        missing_fields=["analysis_scopes", "horizon"],
        clarification_question="What type of analysis and time horizon should I use?",
        confidence=0.9,
        reason="partial",
    )
    out = validate_gate_output(postprocess_gate_output(raw, pending, "fundamental", {}))
    assert out.action == GateRoute.CLARIFY
    assert out.resolved_fields.get("analysis_scopes") == ["FUNDAMENTAL"]
    assert out.missing_fields == ["horizon"]
    assert "type of analysis" not in (out.clarification_question or "").lower()


def test_independent_price_during_pending_does_not_merge_analysis():
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {"analysis_scopes": ["TECHNICAL"]},
        "missing_fields": ["horizon"],
    }
    raw = ConversationGateOutput(
        action=GateRoute.FAST,
        intent=Intent.PRICE_QUERY,
        fast_kind="quote",
        context_relationship=ContextRelationship.INDEPENDENT,
        confidence=0.95,
        reason="new price request",
    )
    out = validate_gate_output(postprocess_gate_output(raw, pending, "What is the current XAU/USD price?", {}))
    assert out.action == GateRoute.FAST
    assert out.fast_kind == "quote"
    assert out.resolved_fields.get("analysis_scopes") is None


def test_clarification_limit_cancels_without_invented_fields():
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {},
        "missing_fields": ["analysis_scopes", "horizon"],
    }
    raw = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        missing_fields=["analysis_scopes", "horizon"],
        clarification_question="What type of analysis and time horizon should I use?",
        confidence=0.5,
        reason="still clarifying",
    )
    out = apply_clarification_limit(raw, pending, "hello")
    assert out.action == GateRoute.GENERAL_CHAT
    assert out.reason == "clarification_limit_cancelled"
    assert out.horizon is None
    assert "few_days" not in (out.normalized_query or "")


def test_emergency_pending_greeting_is_chat():
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {},
        "missing_fields": ["analysis_scopes", "horizon"],
    }
    out = build_emergency_fallback("hi", pending=pending, trade_mode=False, context={})
    assert out.action == GateRoute.GENERAL_CHAT
    assert out.emergency_fallback is True


def test_emergency_pending_price_is_fast_quote():
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {"analysis_scopes": ["FUNDAMENTAL"]},
        "missing_fields": ["horizon"],
    }
    out = build_emergency_fallback(
        "What is the current XAU/USD price?",
        pending=pending,
        trade_mode=False,
        context={},
    )
    assert out.action == GateRoute.FAST
    assert out.fast_kind == "quote"
    assert out.intent == Intent.PRICE_QUERY
    assert out.resolved_fields.get("analysis_scopes") is None


def test_emergency_pending_unrecognized_cancels():
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {},
        "missing_fields": ["analysis_scopes", "horizon"],
    }
    out = build_emergency_fallback("asdfqwer", pending=pending, trade_mode=False, context={})
    assert out.action == GateRoute.GENERAL_CHAT
    assert "cancelled" in out.reason or "unrecognized" in out.reason


@pytest.mark.asyncio
async def test_pipeline_price_then_hi_is_general_chat(temp_db, monkeypatch):
    cid = "price_then_hi"
    async with sqlite_mod.get_connection() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, created_at) VALUES (?, ?)",
            (cid, "2020-01-01T00:00:00+00:00"),
        )
        await conn.commit()

    decisions = [
        ConversationGateOutput(
            action=GateRoute.FAST,
            intent=Intent.PRICE_QUERY,
            fast_kind="quote",
            context_relationship=ContextRelationship.INDEPENDENT,
            complexity=ComplexityLevel.FAST,
            confidence=0.95,
            reason="quote",
        ),
        ConversationGateOutput(
            action=GateRoute.GENERAL_CHAT,
            context_relationship=ContextRelationship.INDEPENDENT,
            complexity=ComplexityLevel.FAST,
            confidence=0.9,
            reason="greeting",
        ),
    ]
    i = {"n": 0}

    async def fake_gate(context, *, query, trade_mode, pending):
        d = decisions[i["n"]]
        i["n"] += 1
        return d

    quote_mock = AsyncMock(return_value={"close": 2650.0})
    manager = AsyncMock(side_effect=AssertionError("manager must not run for greeting"))
    monkeypatch.setattr("app.services.manager_runtime.run_conversation_gate", fake_gate)
    monkeypatch.setattr("app.services.manager_runtime.twelve_data.get_xau_quote", quote_mock)
    monkeypatch.setattr("app.services.manager_runtime._run_agent", manager)
    monkeypatch.setattr(
        "app.services.manager_runtime._stream_and_persist_agent_answer",
        AsyncMock(return_value="Hello! How can I help with gold today?"),
    )

    from app.services.manager_runtime import run_v2_pipeline

    async def collect(q):
        out = []
        async for c in run_v2_pipeline(q, cid):
            out.append(c)
        return "".join(out)

    t1 = await collect("What is the current XAU/USD price?")
    assert "fast_path" in t1
    assert quote_mock.await_count == 1

    # Avoid AssertionError on chat path: _handle_direct_chat uses stream helper
    async def fake_chat(query, conversation_id, hist, mode, emit, *, decision=None, answer_override=None):
        from app.services.manager_runtime import _emit_complete_answer, gate_diagnostics as _gd
        text = answer_override or "Hello!"
        meta = {"route": mode}
        if decision is not None:
            from app.services.conversation_gate import gate_diagnostics
            meta["gate"] = gate_diagnostics(decision)
        await _emit_complete_answer(text, conversation_id, query, emit, metadata=meta)

    monkeypatch.setattr("app.services.manager_runtime._handle_direct_chat", fake_chat)
    quote_before = quote_mock.await_count
    t2 = await collect("hi")
    assert "planning_started" not in t2
    assert quote_mock.await_count == quote_before
    msgs = await repositories.get_messages(cid, limit=20)
    assert msgs[-1]["metadata"].get("route") == "general_chat"
    gate = msgs[-1]["metadata"].get("gate") or {}
    assert gate.get("action") == "GENERAL_CHAT"


@pytest.mark.asyncio
async def test_pipeline_pending_hi_does_not_reclarify(temp_db, monkeypatch):
    cid = "pending_hi"
    async with sqlite_mod.get_connection() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, created_at) VALUES (?, ?)",
            (cid, "2020-01-01T00:00:00+00:00"),
        )
        await conn.commit()
    await repositories.add_message(cid, "user", "analyse gold")
    await repositories.add_message(
        cid,
        "assistant",
        "What type of analysis and time horizon should I use?",
        {
            "route": "clarify",
            "action": "clarify",
            "original_query": "analyse gold",
            "resolved_fields": {},
            "missing_fields": ["analysis_scopes", "horizon"],
            "clarification_turn": 1,
        },
    )

    monkeypatch.setattr(
        "app.services.manager_runtime.run_conversation_gate",
        AsyncMock(
            return_value=ConversationGateOutput(
                action=GateRoute.GENERAL_CHAT,
                context_relationship=ContextRelationship.INDEPENDENT,
                complexity=ComplexityLevel.FAST,
                confidence=0.9,
                reason="greeting during pending",
            )
        ),
    )
    quote_mock = AsyncMock(side_effect=AssertionError("no quote"))
    monkeypatch.setattr("app.services.manager_runtime.twelve_data.get_xau_quote", quote_mock)
    monkeypatch.setattr(
        "app.services.manager_runtime._run_agent",
        AsyncMock(side_effect=AssertionError("no manager")),
    )

    async def fake_chat(query, conversation_id, hist, mode, emit, *, decision=None, answer_override=None):
        from app.services.manager_runtime import _emit_complete_answer
        from app.services.conversation_gate import gate_diagnostics
        meta = {"route": mode}
        if decision is not None:
            meta["gate"] = gate_diagnostics(decision)
        await _emit_complete_answer(answer_override or "Hi!", conversation_id, query, emit, metadata=meta)

    monkeypatch.setattr("app.services.manager_runtime._handle_direct_chat", fake_chat)

    from app.services.manager_runtime import run_v2_pipeline

    chunks = []
    async for c in run_v2_pipeline("hi", cid):
        chunks.append(c)
    text = "".join(chunks)
    assert "planning_started" not in text
    msgs = await repositories.get_messages(cid, limit=20)
    assert msgs[-1]["metadata"].get("route") == "general_chat"
    assert "type of analysis" not in (msgs[-1]["content"] or "").lower()


@pytest.mark.asyncio
async def test_pipeline_cumulative_clarify_then_complete(temp_db, monkeypatch):
    cid = "cum_clarify"
    async with sqlite_mod.get_connection() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, created_at) VALUES (?, ?)",
            (cid, "2020-01-01T00:00:00+00:00"),
        )
        await conn.commit()

    turns = [
        ConversationGateLLMOutput(
            action=GateRoute.CLARIFY,
            context_relationship=ContextRelationship.INDEPENDENT,
            missing_fields=["analysis_scopes", "horizon"],
            clarification_question="What type of analysis and time horizon should I use?",
            confidence=0.9,
            reason="need both",
        ),
        ConversationGateLLMOutput(
            action=GateRoute.CLARIFY,
            context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
            newly_resolved_fields=NewlyResolvedFields(
                intent=Intent.FUNDAMENTAL_ANALYSIS,
                analysis_scopes=[AnalysisScope.FUNDAMENTAL],
            ),
            missing_fields=["analysis_scopes", "horizon"],
            clarification_question="What type of analysis and time horizon should I use?",
            confidence=0.9,
            reason="partial",
        ),
        ConversationGateLLMOutput(
            action=GateRoute.CLARIFY,
            context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
            newly_resolved_fields=NewlyResolvedFields(horizon=Horizon.SHORT_TERM),
            missing_fields=["horizon"],
            clarification_question="What time horizon should I use?",
            confidence=0.9,
            reason="partial",
        ),
    ]
    n = {"i": 0}

    async def fake_gate(context, *, query, trade_mode, pending):
        raw = ConversationGateOutput.model_validate(turns[n["i"]].model_dump())
        n["i"] += 1
        return validate_gate_output(postprocess_gate_output(raw, pending, query, context))

    monkeypatch.setattr("app.services.manager_runtime.run_conversation_gate", fake_gate)
    plan = ManagerPlan(
        goal="analyse gold fundamental short-term",
        horizon=Horizon.SHORT_TERM,
        complexity=ComplexityLevel.STANDARD,
        tasks=[ManagerTask(id="t1", kind="tool_quote", task="quote")],
    )

    async def fake_run(agent, *_a, **_k):
        name = getattr(agent, "name", "")
        if name == "GoldManagerPlan":
            return plan
        if name == "GoldManagerReview":
            from app.schemas.manager import ManagerReview
            return ManagerReview(enough_evidence=True)
        if name == "GoldManagerSynthesis":
            from app.schemas.synthesis import Scenario, SynthesisOutput
            return SynthesisOutput(
                overall_direction="NEUTRAL",
                confidence=0.5,
                horizon=Horizon.SHORT_TERM,
                base_case=Scenario(direction="NEUTRAL", weight=0.6),
                bull_case=Scenario(direction="BULLISH", weight=0.2),
                bear_case=Scenario(direction="BEARISH", weight=0.2),
            )
        return None

    monkeypatch.setattr("app.services.manager_runtime._run_agent", fake_run)
    monkeypatch.setattr(
        "app.services.manager_runtime.twelve_data.get_xau_quote",
        AsyncMock(return_value={"close": 2500}),
    )
    monkeypatch.setattr(
        "app.services.manager_runtime._stream_agent_text",
        AsyncMock(return_value="Fundamental short-term view."),
    )

    from app.services.manager_runtime import run_v2_pipeline

    async def collect(q):
        out = []
        async for c in run_v2_pipeline(q, cid):
            out.append(c)
        return "".join(out)

    await collect("analyse gold")
    msgs = await repositories.get_messages(cid, limit=10)
    assert msgs[-1]["metadata"]["route"] == "clarify"

    await collect("fundamental")
    msgs = await repositories.get_messages(cid, limit=10)
    assert msgs[-1]["metadata"]["missing_fields"] == ["horizon"]
    assert msgs[-1]["metadata"]["resolved_fields"].get("analysis_scopes") == ["FUNDAMENTAL"]

    text = await collect("short term")
    assert "planning_started" in text
    msgs = await repositories.get_messages(cid, limit=20)
    assert msgs[-1]["metadata"].get("route") == "standard"
    assert (msgs[-1]["metadata"].get("gate") or {}).get("action") == "STANDARD"


@pytest.mark.asyncio
async def test_independent_no_progress_triggers_compact_repair(monkeypatch):
    """INDEPENDENT empty-delta clarify while pending must invoke repair (repair_used=true)."""
    pending = {
        "original_query": "technical analyse gold",
        "resolved_fields": {"analysis_scopes": ["TECHNICAL"]},
        "missing_fields": ["horizon"],
        "previous_clarification_question": "What time horizon should I use?",
    }
    bad = ConversationGateLLMOutput(
        action=GateRoute.CLARIFY,
        context_relationship=ContextRelationship.INDEPENDENT,
        analysis_scopes=[AnalysisScope.TECHNICAL],
        newly_resolved_fields=NewlyResolvedFields(),
        missing_fields=["horizon"],
        clarification_question="What time horizon should I use?",
        confidence=0.0,
        reason="",
    )
    good = ConversationGateLLMOutput(
        action=GateRoute.STANDARD,
        context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
        intent=Intent.TECHNICAL_ANALYSIS,
        analysis_scopes=[AnalysisScope.TECHNICAL],
        horizon=Horizon.INTRADAY,
        newly_resolved_fields=NewlyResolvedFields(horizon=Horizon.INTRADAY),
        normalized_query="technical analyse gold Focus on TECHNICAL analysis. Time horizon: intraday.",
        confidence=0.95,
        reason="today answers pending horizon as intraday",
    )
    calls = {"n": 0, "payloads": []}

    async def fake_run(agent, payload):
        calls["n"] += 1
        calls["payloads"].append(payload if isinstance(payload, str) else json.dumps(payload))
        if calls["n"] == 1:
            return MagicMock(final_output=bad)
        return MagicMock(final_output=good)

    monkeypatch.setattr("app.services.conversation_gate.Runner.run", fake_run)
    monkeypatch.setattr(
        "app.services.conversation_gate.settings",
        MagicMock(openai_api_key="test", llm_timeout=30, conversation_gate_max_retries=1),
    )
    ctx = {
        "current_user_message": "today",
        "AUTHORITATIVE_CURRENT_USER_MESSAGE": "today",
        "pending_clarification": pending,
        "trade_mode": False,
    }
    result = await run_conversation_gate(
        ctx,
        query="today",
        trade_mode=False,
        pending=pending,
    )
    assert calls["n"] == 2
    assert result.repair_used is True
    assert result.context_relationship == ContextRelationship.CLARIFICATION_ANSWER
    assert result.horizon == Horizon.INTRADAY
    assert result.analysis_scopes == [AnalysisScope.TECHNICAL]
    assert result.action == GateRoute.STANDARD
    import json as _json

    repair_payload = _json.loads(calls["payloads"][1])
    assert repair_payload.get("repair_mode") is True
    assert repair_payload.get("pending_missing_fields") == ["horizon"]
    assert "TECHNICAL" in str(repair_payload.get("pending_resolved_fields"))
    assert "recent_messages" not in repair_payload


def test_gate_diagnostics_shape():
    d = ConversationGateOutput(
        action=GateRoute.FAST,
        intent=Intent.PRICE_QUERY,
        fast_kind="quote",
        context_relationship=ContextRelationship.INDEPENDENT,
        confidence=0.9,
        reason="quote",
        repair_used=False,
        emergency_fallback=False,
    )
    diag = gate_diagnostics(d)
    assert diag["action"] == "FAST"
    assert diag["fast_kind"] == "quote"
    assert diag["context_relationship"] == "INDEPENDENT"
    assert diag["is_follow_up"] is False
