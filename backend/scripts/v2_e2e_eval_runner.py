"""
Gold Research Agent V2 — comprehensive E2E evaluation runner.
Sends real queries via HTTP SSE (and one in-process provider-failure test).
Writes raw evidence to v2_e2e_raw_results.json — does not invent answers.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

API_BASE = "http://127.0.0.1:8000"
OUT_PATH = Path(__file__).resolve().parents[1] / "v2_e2e_raw_results.json"
BACKEND_LOG_HINT = Path(__file__).resolve().parents[2]  # repo root
TIMEOUT = 360.0


@dataclass
class TurnSpec:
    query: str
    trade_mode: bool = False
    wait_after_s: float = 0.0
    note: str = ""


@dataclass
class TestSpec:
    id: int
    name: str
    clean_session: bool = True
    turns: list[TurnSpec] = field(default_factory=list)
    provider_failure: bool = False  # Test 19 — in-process
    force_stale_wait_s: float = 0.0  # after first turn (Test 15)


TESTS: list[TestSpec] = [
    TestSpec(1, "SIMPLE CURRENT PRICE / FAST PATH", turns=[
        TurnSpec("What is the current XAU/USD price?"),
    ]),
    TestSpec(2, "SIMPLE MARKET DATA", clean_session=True, turns=[
        TurnSpec("What are today's high and low for XAU/USD?"),
    ]),
    TestSpec(3, "TECHNICAL-ONLY REQUEST", turns=[
        TurnSpec(
            "Give me a technical outlook for XAU/USD for the next few days. "
            "Focus on trend, momentum, support and resistance."
        ),
    ]),
    TestSpec(4, "NEWS-ONLY REQUEST", clean_session=True, turns=[
        TurnSpec("What are the most important recent news events affecting gold right now?"),
    ]),
    TestSpec(5, "FUNDAMENTAL-ONLY REQUEST", clean_session=True, turns=[
        TurnSpec(
            "Analyze the current fundamental environment for gold. "
            "Focus on the Fed, real yields, the US dollar and inflation expectations."
        ),
    ]),
    TestSpec(6, "COMPLETE MULTI-AGENT RESEARCH", turns=[
        TurnSpec(
            "Give me a complete XAU/USD outlook for the next three months "
            "using news, fundamentals and technical analysis."
        ),
    ]),
    TestSpec(7, "CAUSAL MARKET EXPLANATION", clean_session=True, turns=[
        TurnSpec(
            "Why has gold moved the way it has today? Identify the main drivers "
            "and tell me which one appears most important."
        ),
    ]),
    TestSpec(8, "ECONOMIC SURPRISE", clean_session=True, turns=[
        TurnSpec(
            "Have any recent US economic releases materially surprised expectations, "
            "and what should those surprises imply for gold?"
        ),
    ]),
    TestSpec(9, "HIGH-IMPACT NEWS / EVENT WEIGHTING", clean_session=True, turns=[
        TurnSpec(
            "Rank the recent events affecting XAU/USD from most important to least important "
            "and explain why the top event matters more than the others."
        ),
    ]),
    TestSpec(10, "CONFLICT ANALYSIS", turns=[
        TurnSpec(
            "Compare the current news, fundamental and technical signals for gold. "
            "Do they agree or conflict?"
        ),
    ]),
    TestSpec(11, "HORIZON-AWARE REASONING", clean_session=True, turns=[
        TurnSpec(
            "Could gold be bearish for the next few days but bullish over the next three months? "
            "Analyze both horizons."
        ),
    ]),
    TestSpec(12, "CLARIFICATION", turns=[
        TurnSpec("Analyze gold."),
        TurnSpec("Focus on the next two weeks."),
    ]),
    TestSpec(13, "MULTI-TURN MEMORY", turns=[
        TurnSpec("Give me a one-month outlook for gold."),
        TurnSpec("What are the three biggest risks to that thesis?"),
        TurnSpec("What would invalidate it?"),
    ]),
    TestSpec(14, "SHORT-TERM DATA REUSE", turns=[
        TurnSpec("What is the current XAU/USD price?"),
        TurnSpec("What was the price you just used, and is gold trading near today's high or low?"),
    ]),
    TestSpec(15, "FRESHNESS / STALE MEMORY", force_stale_wait_s=18.0, turns=[
        TurnSpec("What is the current XAU/USD price?", note="populate STM quote"),
        TurnSpec("What is XAU/USD trading at now?", note="after quote TTL stale"),
    ]),
    TestSpec(16, "REPLANNING", turns=[
        TurnSpec(
            "Investigate whether today's gold move is mainly being driven by the dollar, "
            "Treasury yields, Fed expectations, technical positioning, or news. "
            "Don't assume the cause before checking the evidence."
        ),
    ]),
    TestSpec(17, "TRADER MODE / VALID SETUP", turns=[
        TurnSpec(
            "Analyze XAU/USD for a potential trade setup right now. "
            "Give me a trade only if the evidence supports one.",
            trade_mode=True,
        ),
    ]),
    TestSpec(18, "NO_TRADE", clean_session=False, turns=[  # keep trader mode; new session still ok
        TurnSpec(
            "If the current XAU/USD setup is unclear or conflicting, explicitly tell me not to trade. "
            "Do not force a BUY or SELL signal.",
            trade_mode=True,
        ),
    ]),
    TestSpec(19, "PROVIDER FAILURE / GRACEFUL DEGRADATION", provider_failure=True, turns=[
        TurnSpec(
            "Give me the current XAU/USD outlook and explain the main drivers.",
        ),
    ]),
    TestSpec(20, "FULL SYSTEM STRESS / INTEGRATION TEST", turns=[
        TurnSpec(
            "Give me a comprehensive XAU/USD outlook for the next 1–3 months. "
            "Identify the most important recent news and macro events, evaluate any meaningful "
            "economic surprises, analyze the Fed, dollar and real-yield environment, assess the "
            "technical structure, identify agreements or conflicts between the agents, give me "
            "base/bull/bear scenarios with invalidation conditions, and tell me what evidence "
            "would make you change your current view.",
            trade_mode=False,
        ),
    ]),
]


def _summarize_events(events: list[dict]) -> dict[str, Any]:
    types = [e.get("type") for e in events]
    route = None
    complexity = None
    path = "UNKNOWN"
    agents_enabled: dict | None = None
    agents_executed: list[str] = []
    tools: list[str] = []
    memory_msgs: list[str] = []
    memory_hits: list = []
    replanned = False
    replan_msgs: list[str] = []
    review_notes = []
    plan: dict | None = None
    synthesis: dict | None = None
    sse_stages = []
    warnings = []
    errors = []
    agent_start_times: dict[str, float] = {}
    agent_end_times: dict[str, float] = {}
    parallel_overlap = False

    for i, ev in enumerate(events):
        t = ev.get("type") or ""
        agent = ev.get("agent") or ""
        msg = ev.get("message") or ""
        data = ev.get("data") or {}
        sse_stages.append(t)

        if t == "understanding_completed":
            route = data.get("route")
            complexity = data.get("complexity")
            if route == "FAST":
                path = "FAST"
            elif route == "CLARIFY":
                path = "CLARIFICATION"
            elif route == "RESEARCH":
                path = complexity or "RESEARCH"
        if t == "fast_path":
            path = "FAST"
        if t == "chat_response" and path == "UNKNOWN":
            if "clarif" in msg.lower() or (data.get("route") == "clarify"):
                path = "CLARIFICATION"
        if t == "answer_completed" and data.get("route") == "clarify":
            path = "CLARIFICATION"
        if t == "answer_completed" and data.get("route") == "fast":
            path = "FAST"
        if t == "planning_completed":
            plan = data if isinstance(data, dict) else None
            if plan and plan.get("complexity"):
                path = str(plan.get("complexity"))
            if plan and plan.get("clarification_question") and not plan.get("tasks"):
                path = "CLARIFICATION"
        if t == "check_completed":
            agents_enabled = data.get("agents")
            if data.get("warnings"):
                warnings.extend(data["warnings"])
        if t.endswith("_started") and agent:
            agents_executed.append(agent)
            agent_start_times[agent] = i  # ordinal for overlap heuristic
        if t.endswith("_completed") and agent:
            agent_end_times[agent] = i
        if t == "direct_tool_started":
            tools.append(agent or msg)
        if t.startswith("memory_check"):
            memory_msgs.append(f"{t}: {msg}")
            if t == "memory_check_completed" and isinstance(data, dict):
                memory_hits = data.get("hits") or memory_hits
        if t == "replan_started":
            replanned = True
            replan_msgs.append(msg)
        if t == "review_completed":
            review_notes.append(data)
        if t == "synthesis_completed":
            synthesis = data
        if t == "agent_fallback":
            warnings.append(f"fallback:{agent}:{msg}")
        if t == "error":
            errors.append(msg)

    # Detect specialist overlap by interleaved start/complete ordinals
    specialists = ["news_agent", "fundamental_agent", "technical_agent"]
    started = [a for a in specialists if a in agent_start_times]
    if len(started) >= 2:
        # If second started before first completed → overlap signal from SSE order
        for a in started:
            for b in started:
                if a == b:
                    continue
                if a in agent_start_times and b in agent_start_times and a in agent_end_times:
                    if agent_start_times[b] < agent_end_times[a] and agent_start_times[a] < agent_end_times.get(b, 10**9):
                        parallel_overlap = True

    # Trade mode path label
    return {
        "event_types": types,
        "sse_stages_unique": list(dict.fromkeys(sse_stages)),
        "route_gate": route,
        "complexity": complexity,
        "path": path,
        "agents_enabled": agents_enabled,
        "agents_executed": list(dict.fromkeys(agents_executed)),
        "tools": list(dict.fromkeys(tools)),
        "memory_msgs": memory_msgs,
        "memory_hits": memory_hits,
        "replanned": replanned,
        "replan_msgs": replan_msgs,
        "review": review_notes[-1] if review_notes else None,
        "plan": plan,
        "synthesis": synthesis,
        "parallel_overlap_sse": parallel_overlap,
        "warnings": warnings,
        "errors": errors,
    }


async def create_conversation(client: httpx.AsyncClient) -> str:
    r = await client.post(f"{API_BASE}/api/conversations")
    r.raise_for_status()
    return r.json()["conversation_id"]


async def analyze_http(
    client: httpx.AsyncClient,
    query: str,
    conversation_id: str,
    trade_mode: bool,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    events: list[dict] = []
    answer_parts: list[str] = []
    answer_final = ""
    fatal = None

    async with client.stream(
        "POST",
        f"{API_BASE}/api/analyze",
        json={"query": query, "conversation_id": conversation_id, "trade_mode": trade_mode},
        timeout=TIMEOUT,
    ) as resp:
        if resp.status_code != 200:
            body = await resp.aread()
            return {
                "ok": False,
                "error": f"HTTP {resp.status_code}: {body.decode(errors='replace')[:500]}",
                "latency_s": time.perf_counter() - t0,
                "events": [],
                "answer": "",
                "summary": {},
            }
        buf = ""
        async for chunk in resp.aiter_text():
            buf += chunk
            while "\n\n" in buf:
                part, buf = buf.split("\n\n", 1)
                part = part.strip()
                if not part.startswith("data: "):
                    continue
                try:
                    ev = json.loads(part[6:])
                except json.JSONDecodeError:
                    continue
                events.append(ev)
                t = ev.get("type")
                if t == "answer_delta":
                    answer_parts.append((ev.get("data") or {}).get("delta") or "")
                elif t == "answer_completed":
                    answer_final = (ev.get("data") or {}).get("answer") or "".join(answer_parts)
                elif t == "error" and not (ev.get("agent") or "").endswith("_agent"):
                    # keep going; specialists may continue
                    if not answer_final and not answer_parts:
                        fatal = ev.get("message")

    latency = time.perf_counter() - t0
    answer = answer_final or "".join(answer_parts)
    summary = _summarize_events(events)
    if trade_mode and summary.get("path") not in ("FAST", "CLARIFICATION"):
        summary["path"] = "TRADER" if trade_mode else summary.get("path")
        summary["trade_mode"] = True
    elif trade_mode:
        summary["trade_mode"] = True

    return {
        "ok": bool(answer) and not (fatal and not answer),
        "error": fatal,
        "latency_s": round(latency, 3),
        "events": events,
        "answer": answer,
        "summary": summary,
    }


async def analyze_provider_failure(query: str) -> dict[str, Any]:
    """In-process Test 19: monkeypatch Twelve Data to fail, keep other providers."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.db import repositories
    from app.services.manager_runtime import run_v2_pipeline
    from app.tools import twelve_data

    conversation_id = await repositories.create_conversation()

    original = twelve_data._request

    async def failing_request(*args, **kwargs):
        return {"error": "Simulated Twelve Data provider failure (E2E Test 19)", "status": "error"}

    twelve_data._request = failing_request  # type: ignore
    t0 = time.perf_counter()
    events: list[dict] = []
    answer_parts: list[str] = []
    answer_final = ""
    try:
        async for raw in run_v2_pipeline(query, conversation_id, trade_mode=False):
            if not raw.startswith("data: "):
                continue
            try:
                ev = json.loads(raw[6:].strip())
            except json.JSONDecodeError:
                continue
            events.append(ev)
            t = ev.get("type")
            if t == "answer_delta":
                answer_parts.append((ev.get("data") or {}).get("delta") or "")
            elif t == "answer_completed":
                answer_final = (ev.get("data") or {}).get("answer") or "".join(answer_parts)
    finally:
        twelve_data._request = original  # type: ignore

    answer = answer_final or "".join(answer_parts)
    return {
        "ok": True,  # pipeline completed without hang
        "error": None,
        "latency_s": round(time.perf_counter() - t0, 3),
        "events": events,
        "answer": answer,
        "summary": _summarize_events(events),
        "provider_failure_simulated": "twelve_data",
        "conversation_id": conversation_id,
        "crashed": False,
    }


async def run_test(client: httpx.AsyncClient, spec: TestSpec) -> dict[str, Any]:
    print(f"\n=== TEST {spec.id:02d}: {spec.name} ===", flush=True)
    result: dict[str, Any] = {
        "id": spec.id,
        "name": spec.name,
        "status": "RUNNING",
        "turns": [],
        "blocked_reason": None,
    }

    if spec.provider_failure:
        try:
            turn = await analyze_provider_failure(spec.turns[0].query)
            result["turns"].append({
                "query": spec.turns[0].query,
                "trade_mode": False,
                "note": "provider failure simulated (twelve_data)",
                **turn,
            })
            result["status"] = "EXECUTED"
            print(f"  latency={turn['latency_s']}s path={turn['summary'].get('path')} answer_len={len(turn['answer'])}", flush=True)
        except Exception as exc:
            result["status"] = "BLOCKED"
            result["blocked_reason"] = str(exc)
            print(f"  BLOCKED: {exc}", flush=True)
        return result

    try:
        conv_id = await create_conversation(client)
    except Exception as exc:
        result["status"] = "BLOCKED"
        result["blocked_reason"] = f"Cannot create conversation: {exc}"
        return result

    result["conversation_id"] = conv_id

    for i, turn in enumerate(spec.turns):
        if i == 1 and spec.force_stale_wait_s > 0:
            print(f"  waiting {spec.force_stale_wait_s}s for STM quote TTL stale...", flush=True)
            await asyncio.sleep(spec.force_stale_wait_s)

        print(f"  Turn {i+1}: {turn.query[:80]}... trade_mode={turn.trade_mode}", flush=True)
        turn_result = await analyze_http(client, turn.query, conv_id, turn.trade_mode)
        result["turns"].append({
            "query": turn.query,
            "trade_mode": turn.trade_mode,
            "note": turn.note,
            **turn_result,
        })
        s = turn_result["summary"]
        print(
            f"    path={s.get('path')} agents={s.get('agents_executed')} "
            f"replan={s.get('replanned')} latency={turn_result['latency_s']}s "
            f"answer_len={len(turn_result['answer'])}",
            flush=True,
        )
        if turn_result.get("error") and not turn_result.get("answer"):
            print(f"    ERROR: {turn_result['error']}", flush=True)
        if turn.wait_after_s:
            await asyncio.sleep(turn.wait_after_s)

    result["status"] = "EXECUTED"
    return result


async def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    only = None
    if "--only" in sys.argv:
        idx = sys.argv.index("--only")
        only = {int(x) for x in sys.argv[idx + 1 :]}

    print("=" * 70)
    print("Gold Research Agent V2 — E2E Evaluation")
    print("=" * 70)

    try:
        health = httpx.get(f"{API_BASE}/health", timeout=10)
        health.raise_for_status()
        print(f"Backend OK: {health.json()}")
    except Exception as exc:
        print(f"BLOCKED: backend not reachable: {exc}")
        OUT_PATH.write_text(json.dumps({"blocked": str(exc)}, indent=2), encoding="utf-8")
        return 2

    tests = [t for t in TESTS if only is None or t.id in only]
    results: list[dict] = []

    async with httpx.AsyncClient() as client:
        for spec in tests:
            # Test 18: clean session but trade_mode on (spec says keep trader mode enabled)
            if spec.id == 18:
                spec = TestSpec(
                    id=18,
                    name=spec.name,
                    clean_session=True,
                    turns=spec.turns,
                )
            r = await run_test(client, spec)
            results.append(r)
            # Persist incrementally
            OUT_PATH.write_text(
                json.dumps({"results": results, "updated_at": time.time()}, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )

    print(f"\nRaw results saved to: {OUT_PATH}")
    print(f"Executed: {sum(1 for r in results if r['status']=='EXECUTED')}/{len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
