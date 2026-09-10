"""Live smoke: technical clarify → today / short term (fresh conversations)."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")

from app.db import repositories
from app.db import sqlite as sqlite_mod
from app.db.sqlite import init_db
from app.services.manager_runtime import run_v2_pipeline


async def _collect(cid: str, query: str) -> tuple[list[dict], dict]:
    events: list[dict] = []
    async for chunk in run_v2_pipeline(query, cid):
        if chunk.startswith("data: "):
            events.append(json.loads(chunk[6:]))
    msgs = await repositories.get_messages(cid, limit=50)
    last = msgs[-1] if msgs else {}
    return events, last


def _diag(last: dict, query: str, events: list[dict]) -> dict:
    meta = last.get("metadata") or {}
    gate = meta.get("gate") or {}
    agent_events = [
        e.get("type")
        for e in events
        if str(e.get("type") or "").endswith("_agent_started")
        or str(e.get("type") or "").endswith("_agent_completed")
    ]
    return {
        "query": query,
        "route": meta.get("route"),
        "gate": {
            "action": gate.get("action"),
            "intent": gate.get("intent"),
            "analysis_scopes": gate.get("analysis_scopes"),
            "horizon": gate.get("horizon"),
            "context_relationship": gate.get("context_relationship"),
            "newly_resolved_fields": gate.get("newly_resolved_fields"),
            "resolved_fields": gate.get("resolved_fields"),
            "missing_fields": gate.get("missing_fields"),
            "confidence": gate.get("confidence"),
            "reason": (gate.get("reason") or "")[:120],
            "repair_used": gate.get("repair_used"),
            "emergency_fallback": gate.get("emergency_fallback"),
            "delta_conflict": gate.get("delta_conflict"),
        },
        "specialist_events": agent_events,
        "content_preview": (last.get("content") or "")[:160],
    }


async def _new_cid() -> str:
    cid = str(uuid.uuid4())
    async with sqlite_mod.get_connection() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, created_at) VALUES (?, datetime('now'))",
            (cid,),
        )
        await conn.commit()
    return cid


async def _seq(name: str, queries: list[str]) -> list[dict]:
    cid = await _new_cid()
    print(f"=== {name} (fresh {cid[:8]}) ===")
    out = []
    for q in queries:
        events, last = await _collect(cid, q)
        d = _diag(last, q, events)
        out.append(d)
        print(json.dumps(d, indent=2, default=str))
    return out


async def main() -> None:
    db = ROOT / "live_smoke_clarify_repair.db"
    if db.exists():
        db.unlink()
    sqlite_mod.DB_PATH = str(db)
    await init_db()

    results = {
        "technical_today": await _seq(
            "technical analyse gold -> today",
            ["technical analyse gold", "today"],
        ),
        "technical_short_term": await _seq(
            "technical analyse gold -> short term",
            ["technical analyse gold", "short term"],
        ),
    }
    path = Path(__file__).resolve().parent / "live_smoke_clarify_repair_results.json"
    path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print("wrote", path)


if __name__ == "__main__":
    asyncio.run(main())
