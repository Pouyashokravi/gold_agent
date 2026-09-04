"""Gold Manager V2 hybrid runtime: gate → plan → parallel execute → review/replan → answer."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from agents import Runner
from openai.types.responses import ResponseTextDeltaEvent

from app.agents.direct_chat import direct_chat_agent
from app.agents.gold_manager import (
    gold_manager_answer_agent,
    gold_manager_plan_agent,
    gold_manager_review_agent,
    gold_manager_synthesis_agent,
)
from app.agents.specialists import fundamental_agent, news_agent, technical_agent
from app.config import settings
from app.db import repositories
from app.schemas.common import Horizon
from app.schemas.fundamental import FundamentalAgentOutput, FundamentalDriver
from app.schemas.fundamental_lite import FundamentalAgentResponse
from app.schemas.manager import (
    ComplexityLevel,
    EvidenceCategory,
    EvidenceItem,
    EvidencePool,
    GateRoute,
    ManagerPlan,
    ManagerReview,
    ManagerTask,
)
from app.schemas.news import NewsAgentOutput, NewsEvent
from app.schemas.news_lite import NewsAgentResponse
from app.schemas.synthesis import Scenario, SynthesisOutput
from app.schemas.technical import ChartAnnotations, ChartLevels, TechnicalAgentOutput, TradeSetup
from app.schemas.technical_lite import TechnicalAgentResponse
from app.services.agent_conflict import ConflictType, analyze_agent_relations, max_direction_conflict_severity
from app.services.chart_levels import resolve_technical_chart_output
from app.services.economic_surprise import enrich_news_event
from app.services.evidence import clamp_confidence
from app.services.fundamental_fallback import build_fundamental_fallback
from app.services.gate import GateDecision, classify_gate
from app.services.news_fallback import build_news_fallback
from app.services.policy import apply_manager_plan_constraints, validate_manager_plan
from app.services.session import history_for_manager, history_text
from app.services.technical_fallback import build_technical_fallback
from app.services.trade_setup import build_trade_setup
from app.services import working_memory as stm
from app.tools import twelve_data

logger = logging.getLogger(__name__)

EmitFn = Callable[[str], Awaitable[None]]


def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj


def _dumps(data: Any) -> str:
    return json.dumps(data, default=str)


def _sse(event_type: str, agent: str = "", message: str = "", data: dict | None = None) -> str:
    payload = {"type": event_type, "agent": agent, "message": message, "data": data or {}}
    return f"data: {json.dumps(payload, default=str)}\n\n"


async def _run_agent(agent, user_input: str, max_retries: int = 1) -> Any:
    if not settings.openai_api_key:
        raise RuntimeError(
            "OpenAI API key is not configured. Set OPENAI_API_KEY in the backend environment."
        )
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            result = await asyncio.wait_for(
                Runner.run(agent, user_input),
                timeout=settings.llm_timeout,
            )
            return result.final_output
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Agent %s failed attempt %d (%s): %s",
                agent.name,
                attempt + 1,
                type(exc).__name__,
                exc,
            )
    raise last_exc or RuntimeError("Agent failed")


def _format_trade_setup_section(ts: TradeSetup) -> str:
    tp = ", ".join(str(x) for x in (ts.take_profit or []))
    sl = ts.stop_loss if ts.stop_loss is not None else "N/A"
    rr = ts.risk_reward if ts.risk_reward is not None else "N/A"
    ez = ts.entry_zone
    entry = f"{ez[0]} – {ez[1]}" if len(ez) >= 2 else (str(ez[0]) if ez else "N/A")
    return (
        "\n\n## Trade Setup\n\n"
        f"- **Bias:** {ts.bias}\n"
        f"- **Entry Zone:** {entry}\n"
        f"- **Stop Loss:** {sl}\n"
        f"- **Take Profit:** {tp or 'N/A'}\n"
        f"- **Risk/Reward:** {rr}\n"
        f"- **Invalidation:** {ts.invalidation}\n\n"
        "*This output is market analysis only and is not financial or investment advice.*"
    )


def _answer_includes_trade_setup(text: str) -> bool:
    t = text.lower()
    return "trade setup" in t or ("entry" in t and "stop" in t)


async def _emit_complete_answer(
    text: str,
    conversation_id: str,
    query: str,
    emit: EmitFn,
    metadata: dict | None = None,
) -> None:
    """Emit a finished non-LLM answer immediately (no fake typewriter chunking)."""
    await emit(_sse("answer_started", "answer", "Responding"))
    if text:
        await emit(_sse("answer_delta", "answer", data={"delta": text}))
    await emit(_sse("answer_completed", "answer", "Done", {"answer": text, **(metadata or {})}))
    await repositories.add_message(conversation_id, "user", query)
    await repositories.add_message(conversation_id, "assistant", text, metadata or {})


async def _stream_agent_text(
    agent,
    user_input: str,
    emit: EmitFn,
    *,
    started_message: str = "Responding",
) -> str:
    """True token streaming from an Agents SDK free-text agent via SSE answer_delta."""
    if not settings.openai_api_key:
        raise RuntimeError(
            "OpenAI API key is not configured. Set OPENAI_API_KEY in the backend environment."
        )

    await emit(_sse("answer_started", "answer", started_message))
    result = Runner.run_streamed(agent, user_input)
    parts: list[str] = []

    async def _consume() -> None:
        async for event in result.stream_events():
            if event.type != "raw_response_event":
                continue
            data = event.data
            delta: str | None = None
            if isinstance(data, ResponseTextDeltaEvent):
                delta = data.delta
            else:
                # Fallback for SDK/event shape variants
                ev_type = getattr(data, "type", None)
                if ev_type in {"response.output_text.delta", "response.text.delta"}:
                    raw = getattr(data, "delta", None)
                    if isinstance(raw, str):
                        delta = raw
            if delta:
                parts.append(delta)
                await emit(_sse("answer_delta", "answer", data={"delta": delta}))

    await asyncio.wait_for(_consume(), timeout=settings.llm_timeout)

    text = "".join(parts).strip()
    if not text:
        final = getattr(result, "final_output", None)
        text = str(final).strip() if final is not None else ""
        if text:
            await emit(_sse("answer_delta", "answer", data={"delta": text}))
    return text


async def _stream_and_persist_agent_answer(
    agent,
    user_input: str,
    conversation_id: str,
    query: str,
    emit: EmitFn,
    metadata: dict | None = None,
    *,
    started_message: str = "Responding",
    suffix: str = "",
) -> str:
    text = await _stream_agent_text(agent, user_input, emit, started_message=started_message)
    if suffix:
        await emit(_sse("answer_delta", "answer", data={"delta": suffix}))
        text = f"{text}{suffix}"
    await emit(_sse("answer_completed", "answer", "Done", {"answer": text, **(metadata or {})}))
    await repositories.add_message(conversation_id, "user", query)
    await repositories.add_message(conversation_id, "assistant", text, metadata or {})
    return text


# --- Specialist runners (preserve enrichment / fallbacks) ---

async def _run_technical_specialist(name: str, agent, payload: dict, emit: EmitFn) -> TechnicalAgentOutput | None:
    await emit(_sse(f"{name}_started", name, f"{name} analyzing"))
    trade_mode = bool(payload.get("trade_mode"))
    query = payload.get("query", "")
    t0 = time.perf_counter()
    try:
        lite: TechnicalAgentResponse = await _run_agent(agent, _dumps(payload), max_retries=2)
        horizon_raw = payload.get("horizon", "intraday")
        try:
            horizon = Horizon(horizon_raw)
        except ValueError:
            horizon = Horizon.INTRADAY

        trade_setup: TradeSetup | None = None
        if lite.trade_setup:
            ts = lite.trade_setup
            trade_setup = TradeSetup(
                bias=ts.bias,
                entry_zone=ts.entry_zone,
                stop_loss=ts.stop_loss,
                take_profit=ts.take_profit,
                risk_reward=ts.risk_reward,
                invalidation=ts.invalidation,
                invalidation_level=getattr(ts, "invalidation_level", None),
                confidence=ts.confidence,
            )
        elif trade_mode:
            trade_setup = await build_trade_setup(lite.direction, query)

        chart_levels, trade_setup = await resolve_technical_chart_output(
            lite.chart_levels,
            trade_setup,
            lite.direction,
        )
        if trade_mode and not trade_setup:
            trade_setup = await build_trade_setup(lite.direction, query)
            if trade_setup:
                from app.services.chart_levels import sync_trade_setup_levels
                trade_setup, chart_levels = sync_trade_setup_levels(trade_setup, chart_levels)

        output = TechnicalAgentOutput(
            direction=lite.direction,
            confidence=lite.confidence,
            horizon=horizon,
            drivers=lite.drivers,
            risks=lite.risks,
            evidence=[],
            sources=[],
            timestamp=datetime.now(UTC),
            freshness="FRESH",
            short_term_view=lite.short_term_view,
            long_term_view=lite.long_term_view,
            trade_setup=trade_setup,
            chart_levels=chart_levels,
        )
        logger.info("timing technical_agent elapsed=%.3fs", time.perf_counter() - t0)
        await emit(_sse(f"{name}_completed", name, f"{name} done"))
        return output
    except Exception as exc:
        logger.error("%s failed, using fallback: %s", name, exc)
        await emit(_sse("agent_fallback", name, f"{exc} — using live data fallback"))
        try:
            fallback = await build_technical_fallback(payload)
            if trade_mode:
                fallback.trade_setup = await build_trade_setup(fallback.direction, query)
                fallback.chart_levels = (await resolve_technical_chart_output(None, fallback.trade_setup, fallback.direction))[0]
            await emit(_sse(f"{name}_completed", name, f"{name} done (fallback)"))
            return fallback
        except Exception as fb_exc:
            logger.error("%s fallback failed: %s", name, fb_exc)
            await emit(_sse("error", name, str(fb_exc)))
            return None


async def _run_news_specialist(name: str, agent, payload: dict, emit: EmitFn) -> NewsAgentOutput | None:
    await emit(_sse(f"{name}_started", name, f"{name} analyzing"))
    t0 = time.perf_counter()
    try:
        lite: NewsAgentResponse = await _run_agent(agent, _dumps(payload))
        horizon_raw = payload.get("horizon", "few_days")
        try:
            horizon = Horizon(horizon_raw)
        except ValueError:
            horizon = Horizon.FEW_DAYS
        events = []
        for i, e in enumerate(lite.events):
            enriched = enrich_news_event(
                event_type=e.event_type,
                actual=e.actual,
                forecast=e.forecast,
                previous=e.previous,
                base_importance=e.importance,
                gold_relevance=0.7,
                event_importance=0.6,
                magnitude=0.5,
                persistence=0.5,
                source_confidence=0.6,
            )
            assessment = enriched["assessment"]
            mechanism = assessment.mechanism if assessment.surprise_measurable else ["news impact"]
            direction = e.direction
            if assessment.surprise_measurable and assessment.surprise_gold_bias:
                direction = assessment.surprise_gold_bias
            events.append(NewsEvent(
                event_id=f"evt_{i}",
                event_type=assessment.event_type,
                title=e.title,
                summary=e.summary,
                importance=enriched["importance"],
                gold_relevance=0.7,
                impact_score=enriched["impact_score"],
                direction=direction,
                mechanism=mechanism,
                impact_by_horizon={},
                confidence=0.6,
                source_ids=[],
                actual=e.actual,
                forecast=e.forecast,
                previous=e.previous,
                unit=e.unit,
                surprise_measurable=assessment.surprise_measurable,
                surprise_delta=assessment.surprise_delta,
                surprise_magnitude=assessment.surprise_magnitude,
                surprise_interpretation=assessment.surprise_interpretation,
                surprise_gold_bias=assessment.surprise_gold_bias,
            ))
        output = NewsAgentOutput(
            direction=lite.direction,
            confidence=lite.confidence,
            horizon=horizon,
            drivers=lite.drivers,
            risks=lite.risks,
            events=events,
            evidence=[],
            sources=[],
            timestamp=datetime.now(UTC),
            freshness="FRESH",
        )
        logger.info("timing news_agent elapsed=%.3fs", time.perf_counter() - t0)
        await emit(_sse(f"{name}_completed", name, f"{name} done"))
        return output
    except Exception as exc:
        logger.error("%s failed, using fallback: %s", name, exc)
        await emit(_sse("agent_fallback", name, f"{exc} — using Tavily fallback"))
        try:
            fallback = await build_news_fallback(payload)
            await emit(_sse(f"{name}_completed", name, f"{name} done (fallback)"))
            return fallback
        except Exception as fb_exc:
            logger.error("%s fallback failed: %s", name, fb_exc)
            await emit(_sse("error", name, str(fb_exc)))
            return None


async def _run_fundamental_specialist(name: str, agent, payload: dict, emit: EmitFn) -> FundamentalAgentOutput | None:
    await emit(_sse(f"{name}_started", name, f"{name} analyzing"))
    t0 = time.perf_counter()
    try:
        lite: FundamentalAgentResponse = await _run_agent(agent, _dumps(payload))
        horizon_raw = payload.get("horizon", "medium_term")
        try:
            horizon = Horizon(horizon_raw)
        except ValueError:
            horizon = Horizon.MEDIUM_TERM
        fund_drivers = [
            FundamentalDriver(
                name=d.name,
                current_state=d.current_state,
                direction_for_gold=d.direction_for_gold,
                importance=d.importance,
                confidence=d.confidence,
                horizon_relevance={},
                evidence_ids=[],
            )
            for d in lite.fundamental_drivers
        ]
        output = FundamentalAgentOutput(
            direction=lite.direction,
            confidence=lite.confidence,
            horizon=horizon,
            drivers=lite.drivers,
            risks=lite.risks,
            evidence=[],
            sources=[],
            timestamp=datetime.now(UTC),
            freshness="FRESH",
            fundamental_drivers=fund_drivers,
        )
        logger.info("timing fundamental_agent elapsed=%.3fs", time.perf_counter() - t0)
        await emit(_sse(f"{name}_completed", name, f"{name} done"))
        return output
    except Exception as exc:
        logger.error("%s failed, using fallback: %s", name, exc)
        await emit(_sse("agent_fallback", name, f"{exc} — using FRED fallback"))
        try:
            fallback = await build_fundamental_fallback(payload)
            await emit(_sse(f"{name}_completed", name, f"{name} done (fallback)"))
            return fallback
        except Exception as fb_exc:
            logger.error("%s fallback failed: %s", name, fb_exc)
            await emit(_sse("error", name, str(fb_exc)))
            return None


def _collect_economic_surprises(specialist_outputs: dict[str, Any]) -> list[dict]:
    news = specialist_outputs.get("news") or {}
    events = news.get("events") or []
    surprises = []
    for e in events:
        if e.get("surprise_measurable"):
            surprises.append({
                "title": e.get("title"),
                "event_type": e.get("event_type"),
                "actual": e.get("actual"),
                "forecast": e.get("forecast"),
                "previous": e.get("previous"),
                "surprise_delta": e.get("surprise_delta"),
                "surprise_magnitude": e.get("surprise_magnitude"),
                "surprise_interpretation": e.get("surprise_interpretation"),
                "surprise_gold_bias": e.get("surprise_gold_bias"),
                "importance": e.get("importance"),
                "impact_score": e.get("impact_score"),
            })
    return surprises


def _has_critical_surprise(specialist_outputs: dict[str, Any]) -> bool:
    for s in _collect_economic_surprises(specialist_outputs):
        if s.get("surprise_magnitude") in ("LARGE", "EXTREME"):
            return True
        if s.get("importance") == "CRITICAL":
            return True
    return False


def _apply_synthesis_trade_overrides(
    synthesis: SynthesisOutput,
    horizon: Horizon,
    specialist_outputs: dict[str, Any],
    trade_mode: bool,
    conflict_analysis=None,
) -> SynthesisOutput:
    updates: dict[str, Any] = {"horizon": horizon}
    tech_out = specialist_outputs.get("technical") or {}
    ts_data = tech_out.get("trade_setup")
    chart_data = tech_out.get("chart_levels")
    if ts_data:
        trade_setup = TradeSetup(**ts_data) if isinstance(ts_data, dict) else ts_data
        if conflict_analysis and trade_mode:
            if conflict_analysis.dominant_conflict == ConflictType.DIRECTION_CONFLICT.value:
                trade_setup = trade_setup.model_copy(
                    update={"confidence": round(trade_setup.confidence * 0.7, 3)}
                )
                if max_direction_conflict_severity(conflict_analysis) > 0.8:
                    trade_setup = trade_setup.model_copy(update={"bias": "NO_TRADE"})
        updates["trade_setup"] = trade_setup
        bias = trade_setup.bias
        if trade_mode and bias == "LONG":
            updates["overall_direction"] = "BULLISH"
        elif trade_mode and bias == "SHORT":
            updates["overall_direction"] = "BEARISH"

    if trade_mode and (ts_data or chart_data):
        updates["chart_annotations"] = ChartAnnotations(
            levels=ChartLevels(**chart_data) if isinstance(chart_data, dict) else chart_data,
            trade_setup=updates.get("trade_setup"),
            default_interval="1h",
        )
    return synthesis.model_copy(update=updates)


# --- Fast path tools ---

async def _execute_fast(decision: GateDecision, conversation_id: str, emit: EmitFn) -> str:
    await emit(_sse("memory_check_started", "memory", "Checking short-term memory"))
    kind = decision.fast_kind or "quote"
    params = decision.fast_params or {}

    if kind == "quote":
        cached, freshness, _ = await stm.get_fresh(conversation_id, "quote")
        if cached is None:
            cached, freshness, _ = await stm.get_fresh("global", "quote")
        await emit(_sse("memory_check_completed", "memory", f"quote={freshness or 'miss'}"))
        if cached is None:
            await emit(_sse("direct_tool_started", "tool", "Fetching XAU/USD quote"))
            cached = await twelve_data.get_xau_quote()
            await stm.put(conversation_id, "quote", cached, "quote")
            await stm.put("global", "quote", cached, "quote")
            await emit(_sse("direct_tool_completed", "tool", "Quote ready"))
        close = cached.get("close") or cached.get("price")
        high = cached.get("high")
        low = cached.get("low")
        change = cached.get("percent_change")
        return (
            f"**XAU/USD** is trading near **{close}**"
            + (f" (high {high} / low {low})" if high is not None else "")
            + (f", change {change}%" if change is not None else "")
            + "."
        )

    if kind == "high_low":
        await emit(_sse("memory_check_completed", "memory", "Checking quote for high/low"))
        quote, _, _ = await stm.get_fresh(conversation_id, "quote")
        if quote is None:
            quote, _, _ = await stm.get_fresh("global", "quote")
        if quote is None:
            await emit(_sse("direct_tool_started", "tool", "Fetching quote"))
            quote = await twelve_data.get_xau_quote()
            await stm.put(conversation_id, "quote", quote, "quote")
            await stm.put("global", "quote", quote, "quote")
            await emit(_sse("direct_tool_completed", "tool", "Done"))
        which = params.get("which", "high")
        val = quote.get(which)
        return f"Today's XAU/USD **{which}** is **{val}** (from the current session quote)."

    # Indicators
    interval = params.get("interval", "1h")
    mem_key = f"{kind}:{interval}"
    cached, freshness, _ = await stm.get_fresh(conversation_id, mem_key)
    await emit(_sse("memory_check_completed", "memory", f"{kind}={freshness or 'miss'}"))
    if cached is None:
        await emit(_sse("direct_tool_started", "tool", f"Fetching {kind.upper()} ({interval})"))
        fetchers = {
            "rsi": twelve_data.get_xau_rsi,
            "sma": twelve_data.get_xau_sma,
            "ema": twelve_data.get_xau_ema,
            "macd": twelve_data.get_xau_macd,
            "atr": twelve_data.get_xau_atr,
        }
        fn = fetchers.get(kind, twelve_data.get_xau_rsi)
        if kind == "macd":
            cached = await fn(interval=interval)
        else:
            cached = await fn(interval=interval)
        await stm.put(conversation_id, mem_key, cached, "indicator")
        await emit(_sse("direct_tool_completed", "tool", f"{kind.upper()} ready"))

    # Format briefly
    values = cached.get("values") or cached.get("value") or cached
    latest = values[0] if isinstance(values, list) and values else values
    return f"**XAU/USD {kind.upper()} ({interval})**: `{_dumps(latest)}`"


async def _handle_direct_chat(
    query: str,
    conversation_id: str,
    hist: str,
    mode: str,
    emit: EmitFn,
) -> None:
    await emit(_sse("chat_response", message="Direct chat"))
    chat_input = _dumps({
        "mode": mode,
        "query": query,
        "response_language": "en",
        "recent_conversation": hist,
    })
    await _stream_and_persist_agent_answer(
        direct_chat_agent,
        chat_input,
        conversation_id,
        query,
        emit,
        metadata={"route": mode},
        started_message="Responding",
    )


def _default_plan_from_gate(query: str, decision: GateDecision, trade_mode: bool) -> ManagerPlan:
    """Fallback plan if Manager plan call fails."""
    horizon = Horizon.INTRADAY if trade_mode else Horizon.FEW_DAYS
    tasks: list[ManagerTask] = []
    if decision.complexity == ComplexityLevel.RESEARCH or any(
        w in query.lower() for w in ("why", "despite", "outlook", "fed", "news", "macro")
    ):
        tasks = [
            ManagerTask(id="n1", kind="agent_news", task=f"Investigate catalysts for: {query}", depth="STANDARD"),
            ManagerTask(id="f1", kind="agent_fundamental", task=f"Macro context for: {query}", depth="STANDARD"),
            ManagerTask(id="t1", kind="agent_technical", task=f"Technical structure for: {query}", depth="STANDARD"),
            ManagerTask(id="q1", kind="tool_quote", task="Current XAU/USD quote"),
        ]
    else:
        tasks = [
            ManagerTask(id="t1", kind="agent_technical", task=query, depth="STANDARD"),
        ]
    if trade_mode:
        tasks = [
            ManagerTask(
                id="t1",
                kind="agent_technical",
                depth="DEEP",
                task="Produce trade setup with entry/SL/TP and bias LONG/SHORT/NO_TRADE.",
            ),
            ManagerTask(id="q1", kind="tool_quote", task="Current quote"),
        ]
    return ManagerPlan(
        goal=query,
        horizon=horizon,
        complexity=decision.complexity,
        tasks=tasks,
        rationale="fallback plan",
    )


def _enabled_agents_from_plan(plan: ManagerPlan) -> dict[str, bool]:
    kinds = {t.kind for t in plan.tasks}
    return {
        "news": "agent_news" in kinds,
        "fundamental": "agent_fundamental" in kinds,
        "technical": "agent_technical" in kinds,
    }


async def _run_tool_task(task: ManagerTask, conversation_id: str, emit: EmitFn) -> dict[str, Any]:
    await emit(_sse("direct_tool_started", task.kind, task.task or task.kind))
    t0 = time.perf_counter()
    kind = task.kind
    params = task.params or {}
    interval = params.get("interval", "1h")

    mem_map = {
        "tool_quote": ("quote", "quote", lambda: twelve_data.get_xau_quote()),
        "tool_ohlc": (
            f"ohlc:{interval}",
            "ohlc_intraday" if interval not in {"1day", "1week", "1month"} else "ohlc_daily",
            lambda: twelve_data.get_xau_time_series(interval, int(params.get("outputsize", 50))),
        ),
        "tool_rsi": (f"rsi:{interval}", "indicator", lambda: twelve_data.get_xau_rsi(interval)),
        "tool_sma": (f"sma:{interval}", "indicator", lambda: twelve_data.get_xau_sma(interval)),
        "tool_ema": (f"ema:{interval}", "indicator", lambda: twelve_data.get_xau_ema(interval)),
        "tool_macd": (f"macd:{interval}", "indicator", lambda: twelve_data.get_xau_macd(interval)),
        "tool_atr": (f"atr:{interval}", "indicator", lambda: twelve_data.get_xau_atr(interval)),
    }

    if kind == "tool_macro_snapshot":
        from app.tools import fred
        cached, freshness, _ = await stm.get_fresh(conversation_id, "macro_snapshot")
        if cached is None:
            cached, freshness, _ = await stm.get_fresh("global", "macro_snapshot")
        if cached is None:
            cached = await fred.get_macro_snapshot()
            await stm.put(conversation_id, "macro_snapshot", cached, "macro_snapshot")
            await stm.put("global", "macro_snapshot", cached, "macro_snapshot")
            freshness = "FRESH"
        logger.info("timing %s elapsed=%.3fs memory=%s", kind, time.perf_counter() - t0, freshness)
        await emit(_sse("direct_tool_completed", kind, "Done"))
        return {"kind": kind, "data": cached, "freshness": freshness, "from_memory": freshness is not None}

    if kind not in mem_map:
        await emit(_sse("direct_tool_completed", kind, "Unknown tool"))
        return {"kind": kind, "error": "unknown tool"}

    mem_key, stm_kind, fetcher = mem_map[kind]
    cached, freshness, _ = await stm.get_fresh(conversation_id, mem_key)
    if cached is None and kind == "tool_quote":
        cached, freshness, _ = await stm.get_fresh("global", mem_key)
    from_memory = cached is not None
    if cached is None:
        cached = await fetcher()
        await stm.put(conversation_id, mem_key, cached, stm_kind)
        if kind == "tool_quote":
            await stm.put("global", mem_key, cached, stm_kind)
        freshness = "FRESH"
    logger.info(
        "timing %s elapsed=%.3fs from_memory=%s",
        kind,
        time.perf_counter() - t0,
        from_memory,
    )
    await emit(_sse("direct_tool_completed", kind, "Done"))
    return {"kind": kind, "data": cached, "freshness": freshness, "from_memory": from_memory}


async def _execute_tasks(
    tasks: list[ManagerTask],
    *,
    query: str,
    horizon: str,
    trade_mode: bool,
    conversation_id: str,
    pool: EvidencePool,
    emit: EmitFn,
) -> None:
    """Execute independent tasks in parallel waves based on depends_on."""
    remaining = {t.id: t for t in tasks}
    done: set[str] = set()

    while remaining:
        ready = [
            t for t in remaining.values()
            if all(d in done or d not in {x.id for x in tasks} for d in t.depends_on)
        ]
        if not ready:
            # Break dependency deadlock — run all remaining
            ready = list(remaining.values())

        async def _one(task: ManagerTask):
            start = time.perf_counter()
            try:
                if task.kind == "agent_news":
                    # STM reuse
                    cached, freshness, _ = await stm.get_fresh(conversation_id, "specialist_news")
                    if cached and freshness in {"FRESH", "ACCEPTABLE"} and not trade_mode:
                        pool.specialist_outputs["news"] = cached
                        pool.memory_hits.append("specialist_news")
                        pool.add(EvidenceItem(
                            evidence_id=f"mem_news_{task.id}",
                            category=EvidenceCategory.MEMORY,
                            source="stm",
                            claim="Reused fresh news specialist output",
                            data=cached if isinstance(cached, dict) else {},
                            freshness=freshness or "FRESH",
                        ))
                        await emit(_sse("news_agent_started", "news_agent", "Reusing memory"))
                        await emit(_sse("news_agent_completed", "news_agent", "From memory"))
                        return
                    payload = {
                        "query": query,
                        "horizon": horizon,
                        "trade_mode": trade_mode,
                        "depth": task.depth,
                        "task": task.task,
                        "focus": task.focus,
                    }
                    out = await _run_news_specialist("news_agent", news_agent, payload, emit)
                    if out:
                        dumped = _dump(out)
                        pool.specialist_outputs["news"] = dumped
                        await stm.put(conversation_id, "specialist_news", dumped, "specialist_news", trade_mode)
                elif task.kind == "agent_fundamental":
                    cached, freshness, _ = await stm.get_fresh(conversation_id, "specialist_fundamental")
                    if cached and freshness in {"FRESH", "ACCEPTABLE"} and not trade_mode:
                        pool.specialist_outputs["fundamental"] = cached
                        pool.memory_hits.append("specialist_fundamental")
                        await emit(_sse("fundamental_agent_started", "fundamental_agent", "Reusing memory"))
                        await emit(_sse("fundamental_agent_completed", "fundamental_agent", "From memory"))
                        return
                    payload = {
                        "query": query,
                        "horizon": horizon,
                        "trade_mode": trade_mode,
                        "depth": task.depth,
                        "task": task.task,
                        "focus": task.focus,
                    }
                    out = await _run_fundamental_specialist("fundamental_agent", fundamental_agent, payload, emit)
                    if out:
                        dumped = _dump(out)
                        pool.specialist_outputs["fundamental"] = dumped
                        await stm.put(
                            conversation_id,
                            "specialist_fundamental",
                            dumped,
                            "specialist_fundamental",
                            trade_mode,
                        )
                elif task.kind == "agent_technical":
                    mem_key = "specialist_technical_trade" if trade_mode else "specialist_technical"
                    cached, freshness, _ = await stm.get_fresh(conversation_id, mem_key)
                    if cached and freshness == "FRESH" and not trade_mode:
                        pool.specialist_outputs["technical"] = cached
                        pool.memory_hits.append(mem_key)
                        await emit(_sse("technical_agent_started", "technical_agent", "Reusing memory"))
                        await emit(_sse("technical_agent_completed", "technical_agent", "From memory"))
                        return
                    payload = {
                        "query": query,
                        "horizon": horizon,
                        "trade_mode": trade_mode,
                        "depth": task.depth,
                        "task": task.task,
                        "focus": task.focus,
                    }
                    out = await _run_technical_specialist("technical_agent", technical_agent, payload, emit)
                    if out:
                        dumped = _dump(out)
                        pool.specialist_outputs["technical"] = dumped
                        kind = "specialist_technical_trade" if trade_mode else "specialist_technical"
                        await stm.put(conversation_id, mem_key, dumped, kind, trade_mode)
                elif task.kind.startswith("tool_"):
                    result = await _run_tool_task(task, conversation_id, emit)
                    pool.tool_outputs[task.id or task.kind] = result
                    pool.add(EvidenceItem(
                        evidence_id=f"tool_{task.id}",
                        category=EvidenceCategory.TOOL if task.kind != "tool_quote" else EvidenceCategory.MARKET_DATA,
                        source=task.kind,
                        claim=task.task or task.kind,
                        data=result.get("data") if isinstance(result.get("data"), dict) else {"raw": result.get("data")},
                        freshness=result.get("freshness") or "FRESH",
                    ))
                else:
                    logger.warning("Unknown task kind: %s", task.kind)
            finally:
                logger.info("task %s (%s) wall=%.3fs", task.id, task.kind, time.perf_counter() - start)

        wave_start = time.perf_counter()
        results = await asyncio.gather(*[_one(t) for t in ready], return_exceptions=True)
        logger.info(
            "parallel wave size=%d elapsed=%.3fs",
            len(ready),
            time.perf_counter() - wave_start,
        )
        for t, res in zip(ready, results):
            done.add(t.id)
            remaining.pop(t.id, None)
            if isinstance(res, Exception):
                logger.error("Task %s failed: %s", t.id, res)
                await emit(_sse("error", t.kind, str(res)))


def _neutral_synthesis(horizon: Horizon) -> SynthesisOutput:
    return SynthesisOutput(
        overall_direction="NEUTRAL",
        confidence=0.4,
        horizon=horizon,
        base_case=Scenario(direction="NEUTRAL", weight=0.6),
        bull_case=Scenario(direction="BULLISH", weight=0.2),
        bear_case=Scenario(direction="BEARISH", weight=0.2),
        key_drivers=[],
        key_risks=["Limited evidence"],
    )


async def run_v2_pipeline(
    query: str,
    conversation_id: str,
    trade_mode: bool = False,
) -> AsyncGenerator[str, None]:
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def emit(event: str) -> None:
        await queue.put(event)

    async def produce() -> None:
        request_id = str(uuid.uuid4())
        try:
            await emit(_sse("query_received", message="Query received", data={"request_id": request_id}))

            hist = await history_text(conversation_id)
            hist_msgs = await history_for_manager(conversation_id)
            prior = await stm.get_thesis(conversation_id)

            await emit(_sse("understanding_started", "gate", "Understanding request"))
            decision = classify_gate(query, trade_mode=trade_mode, has_prior_thesis=bool(prior))
            await emit(_sse(
                "understanding_completed",
                "gate",
                decision.reason,
                {"route": decision.route.value, "complexity": decision.complexity.value},
            ))

            # --- Chat / off-topic ---
            if decision.route == GateRoute.GENERAL_CHAT:
                await _handle_direct_chat(query, conversation_id, hist, "general_chat", emit)
                return
            if decision.route == GateRoute.OFF_TOPIC:
                await _handle_direct_chat(query, conversation_id, hist, "off_topic", emit)
                return

            # --- Clarification ---
            if decision.route == GateRoute.CLARIFY and decision.clarification_question:
                await emit(_sse("chat_response", message="Clarification"))
                await _emit_complete_answer(
                    decision.clarification_question,
                    conversation_id,
                    query,
                    emit,
                    metadata={"route": "clarify"},
                )
                return

            # --- Fast path ---
            if decision.route == GateRoute.FAST:
                await emit(_sse("fast_path", message="Fast path", data={"kind": decision.fast_kind}))
                await emit(_sse("chat_response", message="Fast path"))
                answer = await _execute_fast(decision, conversation_id, emit)
                await _emit_complete_answer(
                    answer,
                    conversation_id,
                    query,
                    emit,
                    metadata={"route": "fast", "fast_kind": decision.fast_kind},
                )
                return

            # --- Research / Manager path ---
            await emit(_sse("memory_check_started", "memory", "Checking short-term memory"))
            stm_summary = await stm.summary_for_prompt(conversation_id)
            await emit(_sse("memory_check_completed", "memory", f"{len(stm_summary.get('hits', []))} hits", stm_summary))

            await emit(_sse("planning_started", "gold_manager", "Planning research"))
            plan_input = _dumps({
                "query": query,
                "trade_mode": trade_mode,
                "suggested_complexity": decision.complexity.value,
                "conversation": hist_msgs[-8:],
                "short_term_memory": stm_summary,
                "prior_thesis": prior,
            })
            try:
                plan_raw = await _run_agent(gold_manager_plan_agent, plan_input)
                plan = plan_raw if isinstance(plan_raw, ManagerPlan) else ManagerPlan(**_dump(plan_raw))
            except Exception as exc:
                logger.warning("Manager plan failed, using fallback: %s", exc)
                plan = _default_plan_from_gate(query, decision, trade_mode)

            if plan.clarification_question and not plan.tasks and not plan.use_prior_thesis:
                await emit(_sse("planning_completed", "gold_manager", "Needs clarification", _dump(plan)))
                await emit(_sse("chat_response", message="Clarification"))
                await _emit_complete_answer(
                    plan.clarification_question,
                    conversation_id,
                    query,
                    emit,
                    metadata={"route": "clarify"},
                )
                return

            plan = apply_manager_plan_constraints(plan, query, trade_mode)
            warnings = validate_manager_plan(plan)
            await emit(_sse("planning_completed", "gold_manager", "Done", _dump(plan)))
            await emit(_sse("check_completed", "policy", "Done", {
                "warnings": warnings,
                "agents": _enabled_agents_from_plan(plan),
            }))

            horizon = plan.horizon if isinstance(plan.horizon, Horizon) else Horizon(plan.horizon)
            pool = EvidencePool()

            # Reuse prior thesis for follow-ups with minimal tasks
            if plan.use_prior_thesis and prior and not plan.tasks:
                pool.add(EvidenceItem(
                    evidence_id="prior_thesis",
                    category=EvidenceCategory.MEMORY,
                    source="stm",
                    claim="Prior thesis",
                    data=prior,
                    freshness="ACCEPTABLE",
                ))

            await _execute_tasks(
                plan.tasks,
                query=query,
                horizon=horizon.value,
                trade_mode=trade_mode,
                conversation_id=conversation_id,
                pool=pool,
                emit=emit,
            )

            # Bounded replan loop
            for replan_round in range(settings.max_replan_rounds):
                # Deterministic engines before review
                specialist_outputs = {
                    k: pool.specialist_outputs.get(k)
                    for k in ("news", "fundamental", "technical")
                }
                # Allow empty slots as None
                for k in ("news", "fundamental", "technical"):
                    specialist_outputs.setdefault(k, pool.specialist_outputs.get(k))

                has_any = any(v for v in specialist_outputs.values()) or pool.tool_outputs or plan.use_prior_thesis
                if not has_any and replan_round == 0:
                    # Force a minimal technical+quote replan
                    await emit(_sse("replan_started", "gold_manager", "No evidence — requesting quote+technical"))
                    await _execute_tasks(
                        [
                            ManagerTask(id=f"re_q_{replan_round}", kind="tool_quote", task="Current quote"),
                            ManagerTask(id=f"re_t_{replan_round}", kind="agent_technical", task=query, depth="STANDARD"),
                        ],
                        query=query,
                        horizon=horizon.value,
                        trade_mode=trade_mode,
                        conversation_id=conversation_id,
                        pool=pool,
                        emit=emit,
                    )
                    continue

                await emit(_sse("review_started", "gold_manager", "Reviewing evidence"))
                try:
                    review_raw = await _run_agent(
                        gold_manager_review_agent,
                        _dumps({
                            "query": query,
                            "horizon": horizon.value,
                            "specialist_outputs": pool.specialist_outputs,
                            "tool_outputs": pool.tool_outputs,
                            "memory_hits": pool.memory_hits,
                            "replan_round": replan_round,
                            "max_replan_rounds": settings.max_replan_rounds,
                        }),
                    )
                    review = review_raw if isinstance(review_raw, ManagerReview) else ManagerReview(**_dump(review_raw))
                except Exception as exc:
                    logger.warning("Review failed: %s", exc)
                    review = ManagerReview(enough_evidence=True, notes=f"review fallback: {exc}")

                await emit(_sse("review_completed", "gold_manager", "Done", _dump(review)))
                if review.enough_evidence or not review.replan_tasks:
                    break
                if replan_round >= settings.max_replan_rounds - 1:
                    break
                await emit(_sse("replan_started", "gold_manager", f"Replan round {replan_round + 1}"))
                await _execute_tasks(
                    review.replan_tasks,
                    query=query,
                    horizon=horizon.value,
                    trade_mode=trade_mode,
                    conversation_id=conversation_id,
                    pool=pool,
                    emit=emit,
                )

            specialist_outputs = {
                "news": pool.specialist_outputs.get("news"),
                "fundamental": pool.specialist_outputs.get("fundamental"),
                "technical": pool.specialist_outputs.get("technical"),
            }
            if not any(v for v in specialist_outputs.values()) and not pool.tool_outputs and not prior:
                await emit(_sse("error", message="Insufficient reliable evidence to produce analysis"))
                return

            conflict_analysis = analyze_agent_relations(
                specialist_outputs,
                horizon.value,
                has_critical_surprise=_has_critical_surprise(specialist_outputs),
            )
            economic_surprises = _collect_economic_surprises(specialist_outputs)
            pool.economic_surprises = economic_surprises

            await emit(_sse("synthesis_started", "gold_manager", "Synthesizing"))
            try:
                syn_raw = await _run_agent(
                    gold_manager_synthesis_agent,
                    _dumps({
                        "query": query,
                        "horizon": horizon.value,
                        "trade_mode": trade_mode,
                        "specialist_outputs": specialist_outputs,
                        "tool_outputs": pool.tool_outputs,
                        "agent_conflicts": _dump(conflict_analysis),
                        "economic_surprises": economic_surprises,
                        "prior_thesis": prior,
                        "memory_hits": pool.memory_hits,
                    }),
                )
                synthesis = syn_raw if isinstance(syn_raw, SynthesisOutput) else SynthesisOutput(**_dump(syn_raw))
            except Exception as exc:
                logger.error("Manager synthesis failed: %s", exc)
                synthesis = _neutral_synthesis(horizon)
                dirs = [
                    v.get("direction")
                    for v in specialist_outputs.values()
                    if isinstance(v, dict) and v.get("direction")
                ]
                if dirs:
                    synthesis = synthesis.model_copy(update={"overall_direction": dirs[0], "key_drivers": dirs})

            synthesis = synthesis.model_copy(update={
                "confidence": clamp_confidence(synthesis.confidence + conflict_analysis.confidence_adjustment),
                "agent_conflicts": conflict_analysis,
            })
            synthesis = _apply_synthesis_trade_overrides(
                synthesis, horizon, specialist_outputs, trade_mode, conflict_analysis
            )
            await emit(_sse("synthesis_completed", "synthesis", "Done", _dump(synthesis)))

            answer_input = _dumps({
                "query": query,
                "horizon": horizon.value,
                "trade_mode": trade_mode,
                "synthesis": _dump(synthesis),
                "specialist_outputs": specialist_outputs,
                "economic_surprises": economic_surprises,
            })
            suffix = ""
            try:
                answer_text = await _stream_agent_text(
                    gold_manager_answer_agent,
                    answer_input,
                    emit,
                    started_message="Generating answer",
                )
                if trade_mode and synthesis.trade_setup and not _answer_includes_trade_setup(answer_text):
                    suffix = _format_trade_setup_section(synthesis.trade_setup)
                    await emit(_sse("answer_delta", "answer", data={"delta": suffix}))
                    answer_text = f"{answer_text}{suffix}"
            except Exception as exc:
                logger.error("Manager answer stream failed: %s", exc)
                answer_text = (
                    f"XAU/USD view based on available evidence (degraded mode).\n\n"
                    f"Direction: {synthesis.overall_direction}\n"
                    f"Confidence: {synthesis.confidence}\n"
                    f"Note: answer streaming failed ({exc})."
                )
                await emit(_sse("answer_started", "answer", "Generating answer"))
                await emit(_sse("answer_delta", "answer", data={"delta": answer_text}))

            await emit(_sse("answer_completed", "answer", "Done", {
                "answer": answer_text,
                "synthesis": _dump(synthesis),
                "specialist_outputs": specialist_outputs,
            }))

            await repositories.add_message(conversation_id, "user", query)
            await repositories.add_message(conversation_id, "assistant", answer_text, {
                "synthesis": _dump(synthesis),
                "specialist_outputs": specialist_outputs,
            })
            await stm.put_thesis(conversation_id, {
                "query": query,
                "horizon": horizon.value,
                "synthesis": _dump(synthesis),
                "answer_excerpt": answer_text[:500],
            })
        except Exception as exc:
            logger.exception("V2 pipeline failed")
            await emit(_sse("error", message=str(exc)))
        finally:
            await queue.put(None)

    worker = asyncio.create_task(produce())
    while True:
        item = await queue.get()
        if item is None:
            break
        yield item
    await worker
