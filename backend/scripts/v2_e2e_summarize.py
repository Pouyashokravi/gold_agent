"""Compact summary + fix Test 19 re-run with env loaded."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
# Agents SDK needs env var
if not os.environ.get("OPENAI_API_KEY"):
    # settings may still load via pydantic; export for SDK
    from app.config import settings
    if settings.openai_api_key:
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key

sys.path.insert(0, str(BACKEND))


def summarize():
    raw = json.loads((BACKEND / "v2_e2e_raw_results.json").read_text(encoding="utf-8"))
    for r in raw["results"]:
        for i, t in enumerate(r["turns"]):
            s = t.get("summary") or {}
            ans = t.get("answer") or ""
            mem = (s.get("memory_msgs") or [])[:2]
            print(
                f"T{r['id']:02d}.{i+1} path={s.get('path')} "
                f"agents={s.get('agents_executed')} replan={s.get('replanned')} "
                f"parallel={s.get('parallel_overlap_sse')} lat={t.get('latency_s')} "
                f"ans_len={len(ans)} mem={mem}"
            )
            if s.get("agents_enabled"):
                print("   enabled", s.get("agents_enabled"))
            plan = s.get("plan")
            if plan:
                kinds = [x.get("kind") for x in (plan.get("tasks") or [])]
                print(
                    f"   horizon={plan.get('horizon')} complexity={plan.get('complexity')} "
                    f"tasks={kinds} rationale={(plan.get('rationale') or '')[:120]}"
                )
            syn = s.get("synthesis")
            if syn:
                ac = syn.get("agent_conflicts") or {}
                ts = syn.get("trade_setup") or {}
                print(
                    f"   syn_dir={syn.get('overall_direction')} conf={syn.get('confidence')} "
                    f"conflict={ac.get('dominant_conflict')} trade_bias={ts.get('bias')}"
                )
            # print first 200 of answer
            print("   ANS:", ans[:220].replace("\n", " | "))
            print()


async def rerun_test19():
    from app.db import repositories
    from app.services.manager_runtime import run_v2_pipeline
    from app.tools import twelve_data

    conversation_id = await repositories.create_conversation()
    query = "Give me the current XAU/USD outlook and explain the main drivers."
    original = twelve_data._request

    async def failing_request(*args, **kwargs):
        return {"error": "Simulated Twelve Data provider failure (E2E Test 19)", "status": "error"}

    twelve_data._request = failing_request  # type: ignore
    events = []
    answer_parts = []
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
    # reuse summarizer from runner
    from scripts.v2_e2e_eval_runner import _summarize_events

    summary = _summarize_events(events)
    payload = {
        "ok": True,
        "error": None,
        "latency_s": None,
        "events": events,
        "answer": answer,
        "summary": summary,
        "provider_failure_simulated": "twelve_data",
        "conversation_id": conversation_id,
        "crashed": False,
        "openai_available": bool(os.environ.get("OPENAI_API_KEY")),
    }
    raw_path = BACKEND / "v2_e2e_raw_results.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    for r in raw["results"]:
        if r["id"] == 19:
            r["turns"] = [{
                "query": query,
                "trade_mode": False,
                "note": "provider failure simulated (twelve_data) — rerun with OPENAI_API_KEY",
                **payload,
            }]
            r["status"] = "EXECUTED"
    raw_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("TEST19 answer_len", len(answer))
    print("TEST19 path", summary.get("path"), "agents", summary.get("agents_executed"))
    print("TEST19 ANS:", answer[:400])
    print("warnings", summary.get("warnings"))
    print("errors", summary.get("errors"))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) > 1 and sys.argv[1] == "rerun19":
        asyncio.run(rerun_test19())
    else:
        summarize()
