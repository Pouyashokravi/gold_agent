"""Focused cumulative clarification: analyse gold → partial answers → complete."""

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
from app.services.conversation_gate import postprocess_gate_output, validate_gate_output
from app.services.gate import parse_horizon_from_text


@pytest.fixture
async def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "clarify_partial.db"
    monkeypatch.setattr(sqlite_mod, "DB_PATH", str(db_path))
    await init_db()
    return str(db_path)


def test_short_term_maps_to_canonical_short_term():
    assert parse_horizon_from_text("short term") == Horizon.SHORT_TERM
    assert parse_horizon_from_text("short-term") == Horizon.SHORT_TERM


def test_fundamental_reply_asks_only_horizon():
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {},
        "missing_fields": ["analysis_scopes", "horizon"],
        "previous_clarification_question": "What focus and time horizon should I use?",
    }
    llm = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
        newly_resolved_fields=NewlyResolvedFields(
            intent=Intent.FUNDAMENTAL_ANALYSIS,
            analysis_scopes=[AnalysisScope.FUNDAMENTAL],
        ),
        missing_fields=["horizon"],
        clarification_question="What focus and time horizon should I use?",
        confidence=0.9,
        reason="fundamental focus resolved",
    )
    out = validate_gate_output(postprocess_gate_output(llm, pending, "fundamental", {}))
    assert out.action == GateRoute.CLARIFY
    assert out.resolved_fields.get("analysis_scopes") == ["FUNDAMENTAL"]
    assert out.missing_fields == ["horizon"]
    q = (out.clarification_question or "").lower()
    assert "horizon" in q
    assert "type of analysis" not in q


def test_short_term_after_fundamental_completes():
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {"analysis_scopes": ["FUNDAMENTAL"]},
        "missing_fields": ["horizon"],
        "previous_clarification_question": "What time horizon should I use?",
    }
    llm = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
        newly_resolved_fields=NewlyResolvedFields(horizon=Horizon.SHORT_TERM),
        missing_fields=["horizon"],
        clarification_question="What time horizon should I use?",
        confidence=0.9,
        reason="horizon provided",
    )
    out = validate_gate_output(postprocess_gate_output(llm, pending, "short term", {}))
    assert out.action == GateRoute.STANDARD
    assert out.resolved_fields["analysis_scopes"] == ["FUNDAMENTAL"]
    assert out.resolved_fields["horizon"] == "short_term"
    assert out.horizon == Horizon.SHORT_TERM
    assert out.missing_fields == []
    assert "analyse gold" in (out.normalized_query or "").lower()
    assert "FUNDAMENTAL" in (out.normalized_query or "")
    assert "short_term" in (out.normalized_query or "")


def test_reverse_order_short_term_then_fundamental():
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {},
        "missing_fields": ["analysis_scopes", "horizon"],
        "previous_clarification_question": "What focus and time horizon should I use?",
    }
    turn1 = validate_gate_output(
        postprocess_gate_output(
            ConversationGateOutput(
                action=GateRoute.CLARIFY,
                context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
                newly_resolved_fields=NewlyResolvedFields(horizon=Horizon.SHORT_TERM),
                missing_fields=["analysis_scopes", "horizon"],
                clarification_question="What focus and time horizon should I use?",
                confidence=0.9,
                reason="horizon first",
            ),
            pending,
            "short term",
            {},
        )
    )
    assert turn1.resolved_fields.get("horizon") == "short_term"
    assert "analysis_scopes" in turn1.missing_fields

    pending2 = {
        "original_query": "analyse gold",
        "resolved_fields": turn1.resolved_fields,
        "missing_fields": turn1.missing_fields,
        "previous_clarification_question": turn1.clarification_question,
    }
    turn2 = validate_gate_output(
        postprocess_gate_output(
            ConversationGateOutput(
                action=GateRoute.CLARIFY,
                context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
                newly_resolved_fields=NewlyResolvedFields(
                    intent=Intent.FUNDAMENTAL_ANALYSIS,
                    analysis_scopes=[AnalysisScope.FUNDAMENTAL],
                ),
                confidence=0.9,
                reason="fundamental second",
            ),
            pending2,
            "fundamental",
            {},
        )
    )
    assert turn2.action == GateRoute.STANDARD
    assert turn2.resolved_fields["analysis_scopes"] == ["FUNDAMENTAL"]
    assert turn2.resolved_fields["horizon"] == "short_term"


@pytest.mark.asyncio
async def test_pipeline_analyse_fundamental_short_term(temp_db, monkeypatch):
    from app.services import manager_runtime as mr

    monkeypatch.setattr(mr.settings, "openai_api_key", "test-key")

    outputs = [
        ConversationGateLLMOutput(
            action=GateRoute.CLARIFY,
            context_relationship=ContextRelationship.INDEPENDENT,
            missing_fields=["analysis_scopes", "horizon"],
            clarification_question="What focus and time horizon should I use?",
            confidence=0.9,
            reason="incomplete",
        ),
        ConversationGateLLMOutput(
            action=GateRoute.CLARIFY,
            context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
            newly_resolved_fields=NewlyResolvedFields(
                intent=Intent.FUNDAMENTAL_ANALYSIS,
                analysis_scopes=[AnalysisScope.FUNDAMENTAL],
            ),
            missing_fields=["horizon"],
            clarification_question="What time horizon should I use?",
            confidence=0.9,
            reason="fundamental",
        ),
        ConversationGateLLMOutput(
            action=GateRoute.STANDARD,
            context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
            newly_resolved_fields=NewlyResolvedFields(horizon=Horizon.SHORT_TERM),
            intent=Intent.FUNDAMENTAL_ANALYSIS,
            analysis_scopes=[AnalysisScope.FUNDAMENTAL],
            horizon=Horizon.SHORT_TERM,
            normalized_query="analyse gold Focus on FUNDAMENTAL analysis. Time horizon: short_term.",
            confidence=0.95,
            reason="complete",
        ),
    ]
    idx = {"i": 0}

    class _Raw:
        def __init__(self, out):
            self.final_output = out

    async def fake_run(agent, *_a, **_k):
        i = idx["i"]
        idx["i"] += 1
        return _Raw(outputs[min(i, len(outputs) - 1)])

    monkeypatch.setattr(mr, "Runner", MagicMock())
    from agents import Runner as RealRunner

    monkeypatch.setattr("app.services.conversation_gate.Runner.run", fake_run)

    plan = ManagerPlan(
        goal="analyse gold",
        horizon=Horizon.SHORT_TERM,
        complexity=ComplexityLevel.STANDARD,
        tasks=[ManagerTask(id="f1", kind="agent_fundamental", task="fund", depth="STANDARD")],
        rationale="test",
    )
    monkeypatch.setattr(mr, "_run_agent", AsyncMock(return_value=plan))
    monkeypatch.setattr(mr, "_execute_tasks", AsyncMock())
    monkeypatch.setattr(mr, "_stream_and_persist_agent_answer", AsyncMock())
    monkeypatch.setattr(
        mr,
        "_run_tool_task",
        AsyncMock(return_value={"kind": "tool_quote", "data": {}}),
    )

    conv = await repositories.create_conversation()
    cid = conv if isinstance(conv, str) else conv["id"]

    async def _collect(agen):
        out = []
        async for chunk in agen:
            out.append(chunk)
        return out

    await _collect(mr.run_v2_pipeline("analyse gold", cid, False))
    await _collect(mr.run_v2_pipeline("fundamental", cid, False))
    await _collect(mr.run_v2_pipeline("short term", cid, False))

    msgs = await repositories.get_messages(cid, limit=20)
    assert any(
        (m.get("metadata") or {}).get("route") == "clarify"
        for m in msgs
        if m["role"] == "assistant"
    )
