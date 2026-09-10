"""V2 Conversation Gate, conversation memory, and manager policy tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db import repositories, sqlite as sqlite_mod
from app.db.sqlite import init_db
from app.schemas.common import Horizon, Intent
from app.schemas.conversation_gate import ConversationGateOutput
from app.schemas.conversation_memory import ConversationSummary
from app.schemas.manager import ComplexityLevel, GateRoute, ManagerPlan, ManagerTask
from app.services.conversation_gate import (
    GateValidationError,
    gate_decision_to_output,
    validate_gate_output,
)
from app.services.gate import (
    classify_gate,
    has_explicit_horizon,
    looks_like_horizon_reply,
    parse_horizon_from_text,
)
from app.services.policy import apply_manager_plan_constraints, validate_manager_plan


@pytest.fixture
async def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_gold.db"
    monkeypatch.setattr(sqlite_mod, "DB_PATH", str(db_path))
    await init_db()
    return str(db_path)


def _gate(
    action: GateRoute,
    *,
    fast_kind: str | None = None,
    fast_interval: str | None = None,
    clarification_question: str | None = None,
    missing_fields: list[str] | None = None,
    normalized_query: str | None = None,
    complexity: ComplexityLevel | None = None,
    horizon: Horizon | None = None,
    reason: str = "test",
    confidence: float = 0.9,
) -> ConversationGateOutput:
    if complexity is None:
        if action == GateRoute.FAST:
            complexity = ComplexityLevel.FAST
        elif action == GateRoute.RESEARCH:
            complexity = ComplexityLevel.RESEARCH
        else:
            complexity = ComplexityLevel.STANDARD
    return ConversationGateOutput(
        action=action,
        intent=(
            Intent.PRICE_QUERY
            if action == GateRoute.FAST and (fast_kind or "quote") == "quote"
            else (
                Intent.MARKET_OUTLOOK
                if action in {GateRoute.STANDARD, GateRoute.RESEARCH, GateRoute.CLARIFY}
                else None
            )
        ),
        horizon=horizon if action != GateRoute.FAST else horizon,
        resolved_fields=(
            {
                "analysis_scopes": ["FUNDAMENTAL", "TECHNICAL", "NEWS"],
                "horizon": (horizon or Horizon.FEW_DAYS).value,
            }
            if action in {GateRoute.STANDARD, GateRoute.RESEARCH} and horizon
            else (
                {
                    "analysis_scopes": ["FUNDAMENTAL", "TECHNICAL", "NEWS"],
                    "horizon": Horizon.FEW_DAYS.value,
                }
                if action in {GateRoute.STANDARD, GateRoute.RESEARCH}
                else {}
            )
        ),
        missing_fields=missing_fields or [],
        clarification_question=clarification_question,
        fast_kind=fast_kind,
        fast_interval=fast_interval,
        normalized_query=normalized_query,
        complexity=complexity,
        confidence=confidence,
        reason=reason,
    )


# --- Emergency keyword gate still usable for fallback ---

def test_emergency_classify_fast_price():
    d = classify_gate("What is the current XAU/USD price?")
    assert d.route == GateRoute.FAST
    assert d.fast_kind == "quote"


def test_emergency_classify_fast_rsi():
    d = classify_gate("What is the 1H RSI for gold?")
    assert d.route == GateRoute.FAST
    assert d.fast_kind == "rsi"


def test_emergency_classify_why_not_fast():
    d = classify_gate("What is the gold price, and why did it fall today?")
    assert d.route == GateRoute.RESEARCH


def test_emergency_classify_clarify():
    d = classify_gate("Analyze gold for me.")
    assert d.route == GateRoute.CLARIFY


def test_gate_decision_to_output_maps_standard():
    d = classify_gate("Analyze XAU/USD for the next two weeks.")
    out = gate_decision_to_output(d, "Analyze XAU/USD for the next two weeks.")
    assert out.action in {GateRoute.STANDARD, GateRoute.RESEARCH}
    assert out.normalized_query
    assert out.reason.startswith("emergency_fallback:")


# --- Validation ---

def test_validate_fast_ok():
    out = validate_gate_output(_gate(GateRoute.FAST, fast_kind="quote"))
    assert out.action == GateRoute.FAST


def test_invalid_fast_rejected():
    with pytest.raises(GateValidationError):
        validate_gate_output(_gate(GateRoute.FAST, fast_kind="bogus"))  # type: ignore[arg-type]


def test_clarify_requires_question_and_missing():
    with pytest.raises(GateValidationError):
        validate_gate_output(_gate(GateRoute.CLARIFY, clarification_question=None, missing_fields=["horizon"]))
    with pytest.raises(GateValidationError):
        validate_gate_output(
            _gate(GateRoute.CLARIFY, clarification_question="What horizon?", missing_fields=[])
        )


def test_standard_requires_normalized_query():
    with pytest.raises(GateValidationError):
        validate_gate_output(_gate(GateRoute.STANDARD, normalized_query=None))


def test_gate_instructions_avoid_trade_defaults():
    from app.agents.conversation_gate import conversation_gate_agent
    text = (conversation_gate_agent.instructions or "").lower()
    assert "entry" in text and "stop-loss" in text
    assert "do not ask" in text


# --- Pipeline integration with mocked gate ---

async def _collect(agen):
    events = []
    async for chunk in agen:
        events.append(chunk)
    return events


def _event_types(chunks: list[str]) -> list[str]:
    import json
    types = []
    for c in chunks:
        if not c.startswith("data: "):
            continue
        payload = json.loads(c[6:])
        types.append(payload.get("type"))
    return types


def _has_planning(chunks: list[str]) -> bool:
    return "planning_started" in _event_types(chunks)


@pytest.mark.asyncio
async def test_price_only_fast_never_invokes_manager(temp_db, monkeypatch):
    gate_out = _gate(GateRoute.FAST, fast_kind="quote")
    monkeypatch.setattr(
        "app.services.manager_runtime.run_conversation_gate",
        AsyncMock(return_value=gate_out),
    )
    monkeypatch.setattr(
        "app.services.manager_runtime.twelve_data.get_xau_quote",
        AsyncMock(return_value={"close": 2500.0, "high": 2510, "low": 2490, "percent_change": 0.5}),
    )
    plan_spy = AsyncMock(side_effect=AssertionError("Manager must not run"))
    monkeypatch.setattr("app.services.manager_runtime._run_agent", plan_spy)

    from app.services.manager_runtime import run_v2_pipeline

    chunks = await _collect(run_v2_pipeline("What is the current gold price?", "c1"))
    assert not _has_planning(chunks)
    assert "fast_path" in _event_types(chunks)
    msgs = await repositories.get_messages("c1", limit=10)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_indicator_fast(temp_db, monkeypatch):
    gate_out = _gate(GateRoute.FAST, fast_kind="rsi", fast_interval="1h")
    monkeypatch.setattr(
        "app.services.manager_runtime.run_conversation_gate",
        AsyncMock(return_value=gate_out),
    )
    monkeypatch.setattr(
        "app.services.manager_runtime.twelve_data.get_xau_rsi",
        AsyncMock(return_value={"values": [{"rsi": 55.2}]}),
    )
    monkeypatch.setattr(
        "app.services.manager_runtime._run_agent",
        AsyncMock(side_effect=AssertionError("no manager")),
    )
    from app.services.manager_runtime import run_v2_pipeline

    chunks = await _collect(run_v2_pipeline("Give me the one-hour RSI for gold.", "c2"))
    assert "fast_path" in _event_types(chunks)
    assert not _has_planning(chunks)


@pytest.mark.asyncio
async def test_why_price_goes_to_manager(temp_db, monkeypatch):
    gate_out = _gate(
        GateRoute.RESEARCH,
        normalized_query="Explain why gold price fell today",
        complexity=ComplexityLevel.RESEARCH,
    )
    monkeypatch.setattr(
        "app.services.manager_runtime.run_conversation_gate",
        AsyncMock(return_value=gate_out),
    )

    plan = ManagerPlan(
        goal="why gold fell",
        horizon=Horizon.INTRADAY,
        complexity=ComplexityLevel.RESEARCH,
        tasks=[ManagerTask(id="q1", kind="tool_quote", task="quote")],
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
                overall_direction="BEARISH",
                confidence=0.6,
                horizon=Horizon.INTRADAY,
                base_case=Scenario(direction="BEARISH", weight=0.7),
                bull_case=Scenario(direction="BULLISH", weight=0.15),
                bear_case=Scenario(direction="BEARISH", weight=0.15),
            )
        raise AssertionError(f"unexpected agent {name}")

    monkeypatch.setattr("app.services.manager_runtime._run_agent", fake_run)
    monkeypatch.setattr(
        "app.services.manager_runtime.twelve_data.get_xau_quote",
        AsyncMock(return_value={"close": 2400}),
    )
    monkeypatch.setattr(
        "app.services.manager_runtime._stream_agent_text",
        AsyncMock(return_value="Gold fell on USD strength."),
    )

    from app.services.manager_runtime import run_v2_pipeline

    chunks = await _collect(
        run_v2_pipeline("What is the gold price, and why did it fall today?", "c3")
    )
    assert _has_planning(chunks)
    assert "fast_path" not in _event_types(chunks)


@pytest.mark.asyncio
async def test_ambiguous_clarify(temp_db, monkeypatch):
    gate_out = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        missing_fields=["horizon"],
        clarification_question="What time horizon should I use?",
        complexity=ComplexityLevel.STANDARD,
        confidence=0.9,
        reason="need horizon",
    )
    monkeypatch.setattr(
        "app.services.manager_runtime.run_conversation_gate",
        AsyncMock(return_value=gate_out),
    )
    monkeypatch.setattr(
        "app.services.manager_runtime._run_agent",
        AsyncMock(side_effect=AssertionError("no manager on clarify")),
    )
    from app.services.manager_runtime import run_v2_pipeline

    chunks = await _collect(run_v2_pipeline("Analyze gold.", "c4"))
    assert not _has_planning(chunks)
    msgs = await repositories.get_messages("c4", limit=10)
    assert msgs[-1]["metadata"].get("action") == "clarify"
    assert msgs[-1]["metadata"].get("missing_fields") == ["horizon"]


@pytest.mark.asyncio
async def test_clarification_follow_up_normalized(temp_db, monkeypatch):
    # Seed pending clarification
    cid = "c5"
    async with sqlite_mod.get_connection() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, created_at) VALUES (?, ?)",
            (cid, "2020-01-01T00:00:00+00:00"),
        )
        await conn.commit()
    await repositories.add_message(cid, "user", "I want to evaluate gold as an investment.")
    await repositories.add_message(
        cid,
        "assistant",
        "What time horizon?",
        {
            "route": "clarify",
            "action": "clarify",
            "pending_goal": "I want to evaluate gold as an investment.",
            "missing_fields": ["horizon"],
            "clarification_turn": 1,
        },
    )

    gate_out = ConversationGateOutput(
        action=GateRoute.STANDARD,
        intent=Intent.MARKET_OUTLOOK,
        horizon=Horizon.MEDIUM_TERM,
        is_follow_up=True,
        normalized_query="Evaluate gold as an investment over about six months",
        complexity=ComplexityLevel.STANDARD,
        confidence=0.95,
        reason="clarification resolved",
    )
    monkeypatch.setattr(
        "app.services.manager_runtime.run_conversation_gate",
        AsyncMock(return_value=gate_out),
    )

    plan = ManagerPlan(
        goal=gate_out.normalized_query or "goal",
        horizon=Horizon.MEDIUM_TERM,
        complexity=ComplexityLevel.STANDARD,
        tasks=[ManagerTask(id="t1", kind="agent_technical", task="structure")],
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
                horizon=Horizon.MEDIUM_TERM,
                base_case=Scenario(direction="NEUTRAL", weight=0.6),
                bull_case=Scenario(direction="BULLISH", weight=0.2),
                bear_case=Scenario(direction="BEARISH", weight=0.2),
            )
        return None

    class FakeTech:
        def model_dump(self, mode="json"):
            return {"direction": "NEUTRAL", "confidence": 0.5}

    monkeypatch.setattr("app.services.manager_runtime._run_agent", fake_run)
    monkeypatch.setattr(
        "app.services.manager_runtime._run_technical_specialist",
        AsyncMock(return_value=FakeTech()),
    )
    monkeypatch.setattr(
        "app.services.manager_runtime._stream_agent_text",
        AsyncMock(return_value="Medium-term investment view."),
    )

    from app.services.manager_runtime import run_v2_pipeline

    chunks = await _collect(run_v2_pipeline("Around six months.", cid))
    assert _has_planning(chunks)
    msgs = await repositories.get_messages(cid, limit=20)
    assert any(m["role"] == "assistant" and "Medium-term" in m["content"] for m in msgs)

@pytest.mark.asyncio
async def test_new_request_during_pending_clarify(temp_db, monkeypatch):
    cid = "c6"
    async with sqlite_mod.get_connection() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, created_at) VALUES (?, ?)",
            (cid, "2020-01-01T00:00:00+00:00"),
        )
        await conn.commit()
    await repositories.add_message(cid, "user", "Analyze gold.")
    await repositories.add_message(
        cid,
        "assistant",
        "What horizon?",
        {"route": "clarify", "action": "clarify", "pending_goal": "Analyze gold.", "missing_fields": ["horizon"]},
    )

    gate_out = _gate(GateRoute.FAST, fast_kind="quote")
    monkeypatch.setattr(
        "app.services.manager_runtime.run_conversation_gate",
        AsyncMock(return_value=gate_out),
    )
    monkeypatch.setattr(
        "app.services.manager_runtime.twelve_data.get_xau_quote",
        AsyncMock(return_value={"close": 2500}),
    )
    monkeypatch.setattr(
        "app.services.manager_runtime._run_agent",
        AsyncMock(side_effect=AssertionError("manager should not run")),
    )
    from app.services.manager_runtime import run_v2_pipeline

    chunks = await _collect(run_v2_pipeline("What is the current gold price?", cid))
    assert "fast_path" in _event_types(chunks)
    assert not _has_planning(chunks)


@pytest.mark.asyncio
async def test_standard_and_research_invoke_manager(temp_db, monkeypatch):
    async def _run_one(action, cid):
        gate_out = _gate(
            action,
            normalized_query="Gold analysis",
            complexity=ComplexityLevel.RESEARCH if action == GateRoute.RESEARCH else ComplexityLevel.STANDARD,
            horizon=Horizon.SHORT_TERM,
        )
        monkeypatch.setattr(
            "app.services.manager_runtime.run_conversation_gate",
            AsyncMock(return_value=gate_out),
        )
        plan = ManagerPlan(
            goal="Gold analysis",
            horizon=Horizon.SHORT_TERM,
            complexity=gate_out.complexity,
            tasks=[ManagerTask(id="q1", kind="tool_quote", task="q")],
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
            AsyncMock(return_value="Analysis."),
        )
        from app.services.manager_runtime import run_v2_pipeline
        return await _collect(run_v2_pipeline("Analyze gold short-term", cid))

    chunks_s = await _run_one(GateRoute.STANDARD, "c7s")
    chunks_r = await _run_one(GateRoute.RESEARCH, "c7r")
    assert _has_planning(chunks_s)
    assert _has_planning(chunks_r)


@pytest.mark.asyncio
async def test_gate_llm_failure_uses_emergency_fallback(temp_db, monkeypatch):
    from app.services import conversation_gate as cg

    async def boom(*_a, **_k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(cg, "Runner", MagicMock(run=boom))
    monkeypatch.setattr(cg.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(cg.settings, "conversation_gate_max_retries", 0)

    out = await cg.run_conversation_gate(
        {"current_user_message": "What is the current gold price?"},
        query="What is the current gold price?",
        trade_mode=False,
        pending=None,
    )
    assert out.action == GateRoute.FAST
    assert out.reason.startswith("emergency_fallback:")


@pytest.mark.asyncio
async def test_all_routes_persist_messages(temp_db, monkeypatch):
    monkeypatch.setattr(
        "app.services.manager_runtime.twelve_data.get_xau_quote",
        AsyncMock(return_value={"close": 2500}),
    )
    monkeypatch.setattr(
        "app.services.manager_runtime._stream_and_persist_agent_answer",
        AsyncMock(return_value="chat reply"),
    )

    async def persist_chat(*args, **kwargs):
        cid = args[2]
        query = args[3]
        await repositories.add_message(cid, "user", query)
        await repositories.add_message(cid, "assistant", "chat reply", {"route": "general_chat"})
        return "chat reply"

    monkeypatch.setattr(
        "app.services.manager_runtime._stream_and_persist_agent_answer",
        persist_chat,
    )

    cases = [
        ("cg1", _gate(GateRoute.GENERAL_CHAT)),
        ("cg2", _gate(GateRoute.OFF_TOPIC)),
        (
            "cg3",
            ConversationGateOutput(
                action=GateRoute.CLARIFY,
                clarification_question="Horizon?",
                missing_fields=["horizon"],
                confidence=0.9,
                reason="clarify",
            ),
        ),
        ("cg4", _gate(GateRoute.FAST, fast_kind="quote")),
    ]
    from app.services.manager_runtime import run_v2_pipeline

    for cid, gate_out in cases:
        monkeypatch.setattr(
            "app.services.manager_runtime.run_conversation_gate",
            AsyncMock(return_value=gate_out),
        )
        await _collect(run_v2_pipeline("hello" if gate_out.action == GateRoute.GENERAL_CHAT else "q", cid))
        msgs = await repositories.get_messages(cid, limit=10)
        assert len(msgs) >= 2


# --- Conversation memory / summarizer ---

@pytest.mark.asyncio
async def test_summary_not_before_20(temp_db, monkeypatch):
    cid = "sum1"
    async with sqlite_mod.get_connection() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, created_at) VALUES (?, ?)",
            (cid, "2020-01-01T00:00:00+00:00"),
        )
        await conn.commit()
    for i in range(19):
        await repositories.add_message(cid, "user" if i % 2 == 0 else "assistant", f"m{i}")

    called = False

    async def fake_sum(*_a, **_k):
        nonlocal called
        called = True
        return ConversationSummary(main_topic="x")

    monkeypatch.setattr(
        "app.services.conversation_memory._run_summarizer",
        fake_sum,
    )
    from app.services.conversation_memory import maybe_update_rolling_summary

    await maybe_update_rolling_summary(cid)
    assert called is False
    mem = await repositories.get_conversation_memory(cid)
    assert mem is None


@pytest.mark.asyncio
async def test_summary_runs_at_20_and_preserves_messages(temp_db, monkeypatch):
    cid = "sum2"
    async with sqlite_mod.get_connection() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, created_at) VALUES (?, ?)",
            (cid, "2020-01-01T00:00:00+00:00"),
        )
        await conn.commit()
    for i in range(20):
        await repositories.add_message(cid, "user" if i % 2 == 0 else "assistant", f"m{i}")

    async def fake_sum(prev, batch):
        assert len(batch) == 20
        return ConversationSummary(main_topic="gold", current_state="active")

    monkeypatch.setattr(
        "app.services.conversation_memory._run_summarizer",
        fake_sum,
    )
    from app.services.conversation_memory import maybe_update_rolling_summary

    before = await repositories.get_messages(cid, limit=50)
    await maybe_update_rolling_summary(cid)
    after = await repositories.get_messages(cid, limit=50)
    assert len(before) == len(after) == 20
    assert [m["content"] for m in before] == [m["content"] for m in after]
    mem = await repositories.get_conversation_memory(cid)
    assert mem is not None
    assert mem.summary.main_topic == "gold"
    assert mem.summarized_message_count == 20
    assert mem.last_summarized_message_id == after[-1]["id"]


@pytest.mark.asyncio
async def test_summary_incremental_next_batch(temp_db, monkeypatch):
    cid = "sum3"
    async with sqlite_mod.get_connection() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, created_at) VALUES (?, ?)",
            (cid, "2020-01-01T00:00:00+00:00"),
        )
        await conn.commit()
    for i in range(40):
        await repositories.add_message(cid, "user" if i % 2 == 0 else "assistant", f"m{i}")

    calls = []

    async def fake_sum(prev, batch):
        calls.append((prev.main_topic, len(batch), batch[0]["content"]))
        topic = "batch2" if prev.main_topic == "batch1" else "batch1"
        return ConversationSummary(main_topic=topic, current_state=topic)

    monkeypatch.setattr(
        "app.services.conversation_memory._run_summarizer",
        fake_sum,
    )
    from app.services.conversation_memory import maybe_update_rolling_summary

    await maybe_update_rolling_summary(cid)
    assert len(calls) == 2
    assert calls[0][1] == 20 and calls[1][1] == 20
    assert calls[1][0] == "batch1"  # previous summary topic fed into second call
    mem = await repositories.get_conversation_memory(cid)
    assert mem.summarized_message_count == 40
    assert mem.summary.main_topic == "batch2"


@pytest.mark.asyncio
async def test_summarizer_failure_does_not_advance_cursor(temp_db, monkeypatch):
    cid = "sum4"
    async with sqlite_mod.get_connection() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, created_at) VALUES (?, ?)",
            (cid, "2020-01-01T00:00:00+00:00"),
        )
        await conn.commit()
    for i in range(20):
        await repositories.add_message(cid, "user", f"m{i}")

    async def boom(*_a, **_k):
        raise RuntimeError("summarizer down")

    monkeypatch.setattr(
        "app.services.conversation_memory._run_summarizer",
        boom,
    )
    from app.services.conversation_memory import maybe_update_rolling_summary

    await maybe_update_rolling_summary(cid)
    mem = await repositories.get_conversation_memory(cid)
    assert mem is None
    assert await repositories.count_messages_after(cid, None) == 20


@pytest.mark.asyncio
async def test_cas_stale_cursor_discarded(temp_db):
    cid = "sum5"
    async with sqlite_mod.get_connection() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, created_at) VALUES (?, ?)",
            (cid, "2020-01-01T00:00:00+00:00"),
        )
        await conn.commit()
    mid = await repositories.add_message(cid, "user", "a")
    ok1 = await repositories.cas_save_conversation_memory(
        cid,
        ConversationSummary(main_topic="first"),
        mid,
        1,
        None,
    )
    assert ok1 is True
    # Stale write with expected None should fail
    ok2 = await repositories.cas_save_conversation_memory(
        cid,
        ConversationSummary(main_topic="stale"),
        mid,
        1,
        None,
    )
    assert ok2 is False
    mem = await repositories.get_conversation_memory(cid)
    assert mem.summary.main_topic == "first"


@pytest.mark.asyncio
async def test_memory_isolated_per_conversation(temp_db, monkeypatch):
    for cid, topic in (("iso_a", "alpha"), ("iso_b", "beta")):
        async with sqlite_mod.get_connection() as conn:
            await conn.execute(
                "INSERT INTO conversations (id, created_at) VALUES (?, ?)",
                (cid, "2020-01-01T00:00:00+00:00"),
            )
            await conn.commit()
        for i in range(20):
            await repositories.add_message(cid, "user", f"{topic}-{i}")

        async def fake_sum(prev, batch, _topic=topic):
            return ConversationSummary(main_topic=_topic)

        monkeypatch.setattr(
            "app.services.conversation_memory._run_summarizer",
            fake_sum,
        )
        from app.services.conversation_memory import maybe_update_rolling_summary

        await maybe_update_rolling_summary(cid)

    a = await repositories.get_conversation_memory("iso_a")
    b = await repositories.get_conversation_memory("iso_b")
    assert a.summary.main_topic == "alpha"
    assert b.summary.main_topic == "beta"


@pytest.mark.asyncio
async def test_history_survives_restart(temp_db, monkeypatch):
    cid = "restart1"
    async with sqlite_mod.get_connection() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, created_at) VALUES (?, ?)",
            (cid, "2020-01-01T00:00:00+00:00"),
        )
        await conn.commit()
    for i in range(20):
        await repositories.add_message(cid, "user", f"r{i}")

    async def fake_sum(prev, batch):
        return ConversationSummary(main_topic="persist", current_state="ok")

    monkeypatch.setattr(
        "app.services.conversation_memory._run_summarizer",
        fake_sum,
    )
    from app.services.conversation_memory import maybe_update_rolling_summary

    await maybe_update_rolling_summary(cid)
    # Re-init DB schema (idempotent) — data must remain
    await init_db()
    msgs = await repositories.get_messages(cid, limit=50)
    mem = await repositories.get_conversation_memory(cid)
    assert len(msgs) == 20
    assert mem.summary.main_topic == "persist"


@pytest.mark.asyncio
async def test_api_cache_still_used_without_stm(monkeypatch):
    from app.tools import cache as cache_mod

    # Clear via delete of known keys / reassign store
    cache_mod.cache._store.clear()
    calls = {"n": 0}

    async def fake_fetch():
        calls["n"] += 1
        return {"close": 2500}

    key = "td:quote:test"
    v1 = await cache_mod.cache.get(key)
    assert v1 is None
    data = await fake_fetch()
    await cache_mod.cache.set(key, data, ttl=60)
    v2 = await cache_mod.cache.get(key)
    assert v2 == data
    cached = await cache_mod.cache.get(key)
    if cached is None:
        cached = await fake_fetch()
    assert calls["n"] == 1
    assert cached["close"] == 2500


def test_no_stm_module():
    import importlib.util
    spec = importlib.util.find_spec("app.services.working_memory")
    assert spec is None


def test_schemas_removed_stm_fields():
    assert not hasattr(ManagerPlan, "model_fields") or "use_prior_thesis" not in ManagerPlan.model_fields
    from app.schemas.manager import EvidencePool, EvidenceCategory
    assert "memory_hits" not in EvidencePool.model_fields
    assert not hasattr(EvidenceCategory, "MEMORY")


def test_manager_plan_trade_mode_forces_technical():
    plan = ManagerPlan(
        goal="setup",
        horizon=Horizon.MEDIUM_TERM,
        tasks=[ManagerTask(id="n", kind="agent_news", depth="DEEP", task="news")],
    )
    out = apply_manager_plan_constraints(plan, "trade setup", trade_mode=True)
    assert out.horizon == Horizon.INTRADAY
    assert any(t.kind == "agent_technical" and t.depth == "DEEP" for t in out.tasks)


def test_validate_manager_plan_empty():
    plan = ManagerPlan(goal="x", tasks=[])
    warnings = validate_manager_plan(plan)
    assert warnings


def test_persian_emergency_gate_price():
    d = classify_gate("قیمت طلا")
    assert d.route == GateRoute.FAST


def test_horizon_helpers():
    assert has_explicit_horizon("gold outlook for next two weeks") is True
    assert looks_like_horizon_reply("short-term") is True
    assert parse_horizon_from_text("next two weeks") == Horizon.SHORT_TERM


def test_replan_bound_config():
    from app.config import settings
    assert settings.max_replan_rounds >= 1
    assert settings.recent_messages_limit == 20
    assert settings.max_clarification_turns == 3


@pytest.mark.asyncio
async def test_schedule_summary_after_persist_does_not_block(temp_db, monkeypatch):
    """Summary maintenance is scheduled after persist and failures do not break answers."""
    cid = "sched1"
    async with sqlite_mod.get_connection() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, created_at) VALUES (?, ?)",
            (cid, "2020-01-01T00:00:00+00:00"),
        )
        await conn.commit()

    gate_out = _gate(GateRoute.FAST, fast_kind="quote")
    monkeypatch.setattr(
        "app.services.manager_runtime.run_conversation_gate",
        AsyncMock(return_value=gate_out),
    )
    monkeypatch.setattr(
        "app.services.manager_runtime.twelve_data.get_xau_quote",
        AsyncMock(return_value={"close": 2500}),
    )

    slow = asyncio.Event()

    async def hang_summary(_cid):
        await slow.wait()

    monkeypatch.setattr(
        "app.services.conversation_memory.maybe_update_rolling_summary",
        hang_summary,
    )
    from app.services.manager_runtime import run_v2_pipeline

    chunks = await asyncio.wait_for(
        _collect(run_v2_pipeline("price?", cid)),
        timeout=2.0,
    )
    assert "answer_completed" in _event_types(chunks)
    slow.set()
    await asyncio.sleep(0.05)
