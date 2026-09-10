"""Focused tests for cumulative multi-turn clarification (Conversation Gate)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.db import repositories
from app.db import sqlite as sqlite_mod
from app.db.sqlite import init_db
from app.schemas.common import Horizon, Intent
from app.schemas.conversation_gate import (
    AnalysisPurpose,
    AnalysisScope,
    ContextRelationship,
    ConversationGateOutput,
    NewlyResolvedFields,
)
from app.schemas.manager import ComplexityLevel, GateRoute, ManagerPlan, ManagerTask
from app.services.conversation_gate import (
    apply_clarification_limit,
    apply_clarify_question_guard,
    merge_clarification_state,
)


@pytest.fixture
async def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "clarify_test.db"
    monkeypatch.setattr(sqlite_mod, "DB_PATH", str(db_path))
    await init_db()
    return str(db_path)


async def _collect(agen):
    out = []
    async for chunk in agen:
        out.append(chunk)
    return out


def _types(chunks: list[str]) -> list[str]:
    types = []
    for c in chunks:
        if c.startswith("data: "):
            types.append(json.loads(c[6:]).get("type"))
    return types


def test_merge_clarification_state_cumulative():
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {"analysis_type": "TECHNICAL"},
        "missing_fields": ["horizon", "purpose"],
        "previous_clarification_question": "What time horizon and purpose should I use?",
        "clarification_turn": 1,
    }
    decision = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        horizon=Horizon.SHORT_TERM,
        resolved_fields={},
        missing_fields=["horizon", "purpose", "analysis_scopes"],
        clarification_question="What focus, time horizon, and purpose should I use?",
        confidence=0.9,
        reason="partial",
    )
    merged = merge_clarification_state(pending, decision, allow_pending_merge=True)
    assert merged.resolved_fields["analysis_scopes"] == ["TECHNICAL"]
    assert merged.resolved_fields["horizon"] == "short_term"
    assert "analysis_scopes" not in merged.missing_fields
    assert "horizon" not in merged.missing_fields
    assert "purpose" in merged.missing_fields


def test_resolved_fields_removed_from_missing():
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {
            "analysis_type": "TECHNICAL",
            "horizon": "short_term",
        },
        "missing_fields": ["purpose"],
    }
    decision = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        purpose=AnalysisPurpose.INVESTMENT,
        missing_fields=["analysis_scopes", "horizon", "purpose"],
        clarification_question="What focus, time horizon, and purpose?",
        confidence=0.95,
        reason="done",
    )
    merged = merge_clarification_state(pending, decision, allow_pending_merge=True)
    assert merged.missing_fields == []
    assert merged.action == GateRoute.STANDARD
    assert "analyse gold" in (merged.normalized_query or "").lower()
    assert merged.resolved_fields["purpose"] == "INVESTMENT"
    assert merged.resolved_fields["analysis_scopes"] == ["TECHNICAL"]
    assert merged.resolved_fields["horizon"] == "short_term"


def test_question_guard_replaces_repeated_resolved_ask():
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {"analysis_scopes": ["TECHNICAL"]},
        "missing_fields": ["horizon", "purpose"],
        "previous_clarification_question": (
            "What type of analysis, time horizon, and purpose should I use?"
        ),
    }
    decision = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        resolved_fields={"analysis_scopes": ["TECHNICAL"], "horizon": "short_term"},
        missing_fields=["purpose"],
        clarification_question=(
            "What type of analysis, time horizon, and purpose should I use?"
        ),
        confidence=0.9,
        reason="ask again",
    )
    guarded = apply_clarify_question_guard(decision, pending)
    assert "purpose" in guarded.clarification_question.lower()
    assert "type of analysis" not in guarded.clarification_question.lower()


def test_clarification_limit_cancels_without_invented_fields():
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {
            "analysis_scopes": ["TECHNICAL"],
            "horizon": "short_term",
        },
        "missing_fields": ["purpose"],
    }
    decision = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        resolved_fields={"analysis_scopes": ["TECHNICAL"], "horizon": "short_term"},
        missing_fields=["purpose"],
        clarification_question="What is the purpose of this analysis?",
        horizon=Horizon.SHORT_TERM,
        confidence=0.8,
        reason="still missing purpose",
    )
    limited = apply_clarification_limit(decision, pending, "for investment")
    assert limited.action == GateRoute.GENERAL_CHAT
    assert limited.reason == "clarification_limit_cancelled"
    assert limited.normalized_query is None


@pytest.mark.asyncio
async def test_english_multi_turn_clarify_sequence(temp_db, monkeypatch):
    """analyse gold → technical → in short time → for investment."""
    cid = "clarify_seq"
    async with sqlite_mod.get_connection() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, created_at) VALUES (?, datetime('now'))",
            (cid,),
        )
        await conn.commit()

    # Scripted Gate outputs per turn (after merge/guard in runtime path we mock the full runner)
    turns = [
        ConversationGateOutput(
            action=GateRoute.CLARIFY,
            context_relationship=ContextRelationship.INDEPENDENT,
            missing_fields=["analysis_scopes", "horizon", "purpose"],
            clarification_question=(
                "What focus, time horizon, and purpose should I use for this analysis?"
            ),
            confidence=0.9,
            reason="ambiguous",
        ),
        ConversationGateOutput(
            action=GateRoute.CLARIFY,
            context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
            newly_resolved_fields=NewlyResolvedFields(
                intent=Intent.TECHNICAL_ANALYSIS,
                analysis_scopes=[AnalysisScope.TECHNICAL],
            ),
            missing_fields=["horizon", "purpose"],
            clarification_question=(
                "What focus, time horizon, and purpose should I use for this analysis?"
            ),
            confidence=0.9,
            reason="got technical",
        ),
        ConversationGateOutput(
            action=GateRoute.CLARIFY,
            context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
            newly_resolved_fields=NewlyResolvedFields(horizon=Horizon.SHORT_TERM),
            missing_fields=["purpose"],
            clarification_question=(
                "What focus, time horizon, and purpose should I use for this analysis?"
            ),
            confidence=0.9,
            reason="got horizon",
        ),
        ConversationGateOutput(
            action=GateRoute.STANDARD,
            context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
            newly_resolved_fields=NewlyResolvedFields(purpose=AnalysisPurpose.INVESTMENT),
            purpose=AnalysisPurpose.INVESTMENT,
            intent=Intent.TECHNICAL_ANALYSIS,
            analysis_scopes=[AnalysisScope.TECHNICAL],
            horizon=Horizon.SHORT_TERM,
            resolved_fields={
                "analysis_scopes": ["TECHNICAL"],
                "horizon": "short_term",
                "purpose": "INVESTMENT",
            },
            missing_fields=[],
            normalized_query=(
                "analyse gold Focus on TECHNICAL analysis. "
                "Time horizon: short_term. Purpose: INVESTMENT."
            ),
            complexity=ComplexityLevel.STANDARD,
            confidence=0.95,
            reason="complete",
        ),
    ]
    call_i = {"n": 0}

    async def fake_gate(context, *, query, trade_mode, pending):
        from app.services.conversation_gate import postprocess_gate_output, validate_gate_output

        raw = turns[call_i["n"]]
        call_i["n"] += 1
        processed = postprocess_gate_output(raw, pending, query, context)
        return validate_gate_output(processed)

    monkeypatch.setattr(
        "app.services.manager_runtime.run_conversation_gate",
        fake_gate,
    )

    plan = ManagerPlan(
        goal="analyse gold technical short-term investment",
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
        AsyncMock(return_value="Technical short-term investment view."),
    )

    from app.services.manager_runtime import run_v2_pipeline

    queries = ["analyse gold", "technical", "in short time", "for investment"]
    questions: list[str] = []

    for q in queries:
        chunks = await _collect(run_v2_pipeline(q, cid))
        types = _types(chunks)
        if "planning_started" in types:
            questions.append("PROCEED")
        else:
            # final assistant clarify text from answer_completed
            for c in chunks:
                if not c.startswith("data: "):
                    continue
                payload = json.loads(c[6:])
                if payload.get("type") == "answer_completed":
                    questions.append(payload.get("data", {}).get("answer") or "")

    assert len(questions) == 4
    # Turn 1: asks for focus/horizon/purpose
    assert "focus" in questions[0].lower() or "horizon" in questions[0].lower()
    # Turn 2: must not re-ask analysis type primarily — only horizon+purpose
    assert "purpose" in questions[1].lower() or "horizon" in questions[1].lower()
    assert questions[1].lower().count("type of analysis") == 0
    # Turn 3: purpose only
    assert "purpose" in questions[2].lower()
    assert "horizon" not in questions[2].lower()
    assert "type of analysis" not in questions[2].lower()
    # Turn 4: proceed
    assert questions[3] == "PROCEED"

    msgs = await repositories.get_messages(cid, limit=50)
    # 4 user + 4 assistant = 8
    assert len(msgs) == 8
    assert sum(1 for m in msgs if m["role"] == "user") == 4
    assert sum(1 for m in msgs if m["role"] == "assistant") == 4

    # Cumulative metadata on clarify turns
    clarify_assistants = [
        m for m in msgs if m["role"] == "assistant" and (m.get("metadata") or {}).get("action") == "clarify"
    ]
    assert len(clarify_assistants) == 3
    assert clarify_assistants[1]["metadata"]["resolved_fields"].get("analysis_scopes") == ["TECHNICAL"]
    assert "analysis_scopes" not in clarify_assistants[1]["metadata"]["missing_fields"]
    assert clarify_assistants[2]["metadata"]["resolved_fields"].get("horizon") == "short_term"
    assert clarify_assistants[2]["metadata"]["missing_fields"] == ["purpose"]
