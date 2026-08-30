import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from agents import Runner

from app.agents.query_understanding import gold_planner_agent, query_understanding_agent
from app.agents.specialists import (
    answer_generator_agent,
    fundamental_agent,
    long_term_agent,
    news_agent,
    short_term_agent,
    synthesis_agent,
    technical_agent,
)
from app.config import settings
from app.db import repositories
from app.schemas.common import Horizon
from app.schemas.news import NewsAgentOutput, NewsEvent
from app.schemas.news_lite import NewsAgentResponse
from app.schemas.fundamental import FundamentalAgentOutput, FundamentalDriver
from app.schemas.fundamental_lite import FundamentalAgentResponse
from app.schemas.planner import GoldPlannerOutput
from app.schemas.query import QueryUnderstandingOutput
from app.schemas.synthesis import SynthesisOutput
from app.schemas.technical import ChartAnnotations, ChartLevels, TechnicalAgentOutput, TradeSetup
from app.schemas.technical_lite import TechnicalAgentResponse
from app.services.fundamental_fallback import build_fundamental_fallback
from app.services.news_fallback import build_news_fallback
from app.services.technical_fallback import build_technical_fallback
from app.services.freshness import classify_freshness
from app.services.policy import apply_horizon_overrides, apply_intent_overrides, apply_routing_overrides, apply_trade_mode_overrides, validate_plan
from app.services.agent_conflict import ConflictType, analyze_agent_relations, max_direction_conflict_severity
from app.services.chart_levels import resolve_technical_chart_output
from app.services.economic_surprise import enrich_news_event
from app.services.evidence import clamp_confidence
from app.services.trade_setup import build_trade_setup

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


def _profile_horizon(profile: QueryUnderstandingOutput) -> Horizon:
    if isinstance(profile.horizon, Horizon):
        return profile.horizon
    return Horizon(profile.horizon)


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


def _apply_synthesis_trade_overrides(
    synthesis: SynthesisOutput,
    profile: QueryUnderstandingOutput,
    specialist_outputs: dict[str, Any],
    trade_mode: bool,
    conflict_analysis=None,
) -> SynthesisOutput:
    horizon = _profile_horizon(profile)
    updates: dict[str, Any] = {"horizon": horizon}

    tech_out = specialist_outputs.get("technical") or {}
    ts_data = tech_out.get("trade_setup")
    chart_data = tech_out.get("chart_levels")
    if ts_data:
        trade_setup = TradeSetup(**ts_data)
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
            levels=ChartLevels(**chart_data) if chart_data else None,
            trade_setup=updates.get("trade_setup"),
            default_interval="1h",
        )

    return synthesis.model_copy(update=updates)


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
            logger.warning("Agent %s failed attempt %d: %s", agent.name, attempt + 1, exc)
    raise last_exc or RuntimeError("Agent failed")


async def _run_technical_specialist(name: str, agent, payload: dict, emit: EmitFn) -> TechnicalAgentOutput | None:
    await emit(_sse(f"{name}_started", name, f"{name} analyzing"))
    trade_mode = bool(payload.get("trade_mode"))
    query = payload.get("query", "")
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


async def _run_specialist(
    name: str,
    agent,
    payload: dict,
    emit: EmitFn,
) -> Any | None:
    await emit(_sse(f"{name}_started", name, f"{name} analyzing"))
    try:
        output = await _run_agent(agent, _dumps(payload))
        await emit(_sse(f"{name}_completed", name, f"{name} done"))
        return output
    except Exception as exc:
        logger.error("%s failed: %s", name, exc)
        await emit(_sse("error", name, str(exc)))
        return None


async def _maybe_refresh_technical(
    kind: str,
    agent,
    payload: dict,
    emit: EmitFn,
) -> dict | None:
    stored = await repositories.get_latest_technical_output(kind)
    short = kind == "short"
    if stored:
        freshness = classify_freshness(stored["_stored_at"], short_term=short)
        if freshness != "STALE":
            return stored

    event = f"{kind}_term_agent"
    await emit(_sse(f"{event}_started", event, f"Refreshing {kind}-term technical"))
    try:
        output = await _run_agent(agent, _dumps(payload))
        out_dict = _dump(output)
        await repositories.save_technical_output(kind, out_dict)
        await emit(_sse(f"{event}_completed", event, f"{kind}-term technical done"))
        return out_dict
    except Exception as exc:
        logger.error("%s-term refresh failed: %s", kind, exc)
        await emit(_sse("error", event, str(exc)))
        return stored


def _detect_response_language(query: str) -> str:
    persian = sum(1 for c in query if "\u0600" <= c <= "\u06FF")
    return "fa" if persian > max(3, len(query) * 0.12) else "en"


async def run_pipeline(
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

            history = await repositories.get_messages(conversation_id, limit=8)
            history_text = "\n".join(f"{m['role']}: {m['content']}" for m in history)

            await emit(_sse("understanding_started", "query_understanding", "Understanding query"))
            try:
                qu_input = f"Query: {query}\n\nRecent conversation:\n{history_text}"
                profile: QueryUnderstandingOutput = await _run_agent(query_understanding_agent, qu_input)
            except Exception as exc:
                await emit(_sse("error", "query_understanding", str(exc)))
                return
            profile = apply_horizon_overrides(profile, query)
            profile = apply_intent_overrides(profile, query)
            if trade_mode:
                profile = profile.model_copy(update={"horizon": Horizon.INTRADAY})
            await emit(_sse("understanding_completed", "query_understanding", "Done", _dump(profile)))

            await emit(_sse("planning_started", "gold_planner", "Planning research"))
            try:
                planner_input = _dumps({
                    "query": query,
                    "query_profile": _dump(profile),
                    "trade_mode": trade_mode,
                })
                plan: GoldPlannerOutput = await _run_agent(gold_planner_agent, planner_input)
            except Exception as exc:
                await emit(_sse("error", "gold_planner", str(exc)))
                return
            plan = apply_routing_overrides(plan, profile, query)
            profile, plan = apply_trade_mode_overrides(profile, plan, query, trade_mode)
            await emit(_sse("planning_completed", "gold_planner", "Done", _dump(plan)))

            await emit(_sse("check_started", "policy", "Running policy checks"))
            warnings = validate_plan(plan)
            await emit(_sse("check_completed", "policy", "Done", {
                "warnings": warnings,
                "agents": {
                    "news": plan.news_agent.enabled,
                    "fundamental": plan.fundamental_agent.enabled,
                    "technical": plan.technical_agent.enabled,
                },
            }))

            horizon = _profile_horizon(profile).value
            base_payload = {"query": query, "horizon": horizon, "trade_mode": trade_mode}
            specialist_outputs: dict[str, Any] = {}

            async def run_news():
                if not plan.news_agent.enabled or plan.news_agent.depth == "OFF":
                    return None
                p = {**base_payload, "depth": plan.news_agent.depth, "task": plan.news_agent.task, "focus": plan.news_agent.focus}
                return await _run_news_specialist("news_agent", news_agent, p, emit)

            async def run_fundamental():
                if not plan.fundamental_agent.enabled or plan.fundamental_agent.depth == "OFF":
                    return None
                p = {**base_payload, "depth": plan.fundamental_agent.depth, "task": plan.fundamental_agent.task, "focus": plan.fundamental_agent.focus}
                return await _run_fundamental_specialist("fundamental_agent", fundamental_agent, p, emit)

            async def run_technical():
                if not plan.technical_agent.enabled or plan.technical_agent.depth == "OFF":
                    return None
                tech_payload = {**base_payload, "depth": plan.technical_agent.depth, "task": plan.technical_agent.task, "focus": plan.technical_agent.focus}
                if plan.technical_agent.depth in {"STANDARD", "DEEP"} and not trade_mode:
                    if horizon in {"intraday", "few_days", "short_term"}:
                        await _maybe_refresh_technical("short", short_term_agent, tech_payload, emit)
                    if horizon in {"medium_term", "long_term", "ages", "short_term"}:
                        await _maybe_refresh_technical("long", long_term_agent, tech_payload, emit)
                return await _run_technical_specialist("technical_agent", technical_agent, tech_payload, emit)

            if plan.execution_mode == "PARALLEL":
                results = await asyncio.gather(run_news(), run_fundamental(), run_technical(), return_exceptions=True)
            else:
                results = [await run_news(), await run_fundamental(), await run_technical()]

            keys = ["news", "fundamental", "technical"]
            for key, result in zip(keys, results):
                if isinstance(result, Exception):
                    specialist_outputs[key] = None
                elif result is not None:
                    specialist_outputs[key] = _dump(result)
                else:
                    specialist_outputs[key] = None

            if not any(v for v in specialist_outputs.values()):
                await emit(_sse("error", message="Insufficient reliable evidence to produce analysis"))
                return

            await emit(_sse("synthesis_started", "synthesis", "Synthesizing"))
            try:
                conflict_analysis = analyze_agent_relations(
                    specialist_outputs,
                    horizon,
                    has_critical_surprise=_has_critical_surprise(specialist_outputs),
                )
                economic_surprises = _collect_economic_surprises(specialist_outputs)
                syn_input = _dumps({
                    "query": query,
                    "horizon": horizon,
                    "trade_mode": trade_mode,
                    "specialist_outputs": specialist_outputs,
                    "agent_conflicts": _dump(conflict_analysis),
                    "economic_surprises": economic_surprises,
                })
                synthesis: SynthesisOutput = await _run_agent(synthesis_agent, syn_input)
                synthesis = synthesis.model_copy(update={
                    "confidence": clamp_confidence(synthesis.confidence + conflict_analysis.confidence_adjustment),
                    "agent_conflicts": conflict_analysis,
                })
                synthesis = _apply_synthesis_trade_overrides(
                    synthesis, profile, specialist_outputs, trade_mode, conflict_analysis
                )
                await emit(_sse("synthesis_completed", "synthesis", "Done", _dump(synthesis)))
            except Exception as exc:
                await emit(_sse("error", "synthesis", str(exc)))
                return

            await emit(_sse("answer_started", "answer", "Generating answer"))
            try:
                response_language = _detect_response_language(query)
                ans_input = _dumps({
                    "query": query,
                    "query_profile": _dump(profile),
                    "synthesis": _dump(synthesis),
                    "trade_mode": trade_mode,
                    "response_language": response_language,
                })
                answer_result = await asyncio.wait_for(
                    Runner.run(answer_generator_agent, ans_input),
                    timeout=settings.llm_timeout,
                )
                answer_text = str(answer_result.final_output)
                if trade_mode and synthesis.trade_setup and not _answer_includes_trade_setup(answer_text):
                    answer_text += _format_trade_setup_section(synthesis.trade_setup)
                chunk_size = 80
                for i in range(0, len(answer_text), chunk_size):
                    await emit(_sse("answer_delta", "answer", data={"delta": answer_text[i:i + chunk_size]}))
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
            except Exception as exc:
                await emit(_sse("error", "answer", str(exc)))
        except Exception as exc:
            logger.exception("Pipeline failed")
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
