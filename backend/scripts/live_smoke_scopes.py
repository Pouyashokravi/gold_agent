"""Focused live smoke for analysis_scopes Gate routing (configured model)."""

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
    return {
        "query": query,
        "route": meta.get("route"),
        "gate": {
            "action": gate.get("action"),
            "intent": gate.get("intent"),
            "analysis_scopes": gate.get("analysis_scopes"),
            "horizon": gate.get("horizon"),
            "context_relationship": gate.get("context_relationship"),
            "is_follow_up": gate.get("is_follow_up"),
            "resolved_fields": gate.get("resolved_fields"),
            "missing_fields": gate.get("missing_fields"),
            "newly_resolved_fields": gate.get("newly_resolved_fields"),
            "delta_conflict": gate.get("delta_conflict"),
            "confidence": gate.get("confidence"),
            "reason": gate.get("reason"),
            "repair_used": gate.get("repair_used"),
            "emergency_fallback": gate.get("emergency_fallback"),
        },
        "events": [e.get("type") for e in events],
        "content_preview": (last.get("content") or "")[:180],
    }


async def _new_conversation() -> str:
    cid = str(uuid.uuid4())
    async with sqlite_mod.get_connection() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, created_at) VALUES (?, datetime('now'))",
            (cid,),
        )
        await conn.commit()
    return cid


async def _run_sequence(name: str, queries: list[str]) -> list[dict]:
    cid = await _new_conversation()
    print(f"=== {name} ===")
    results = []
    for q in queries:
        events, last = await _collect(cid, q)
        d = _diag(last, q, events)
        results.append(d)
        print(json.dumps(d, indent=2, default=str))
    return results


async def main() -> None:
    db_path = Path(__file__).resolve().parents[1] / "live_smoke_gate_scopes.db"
    if db_path.exists():
        db_path.unlink()
    sqlite_mod.DB_PATH = str(db_path)
    await init_db()

    out = {
        "case1_complete_outlook": await _run_sequence(
            "Case 1: complete outlook",
            ["3-month gold outlook analysis"],
        ),
        "case2_all_of_them": await _run_sequence(
            "Case 2: analyse gold -> all of them",
            ["analyse gold", "all of them"],
        ),
        "case3_whatever_necessary": await _run_sequence(
            "Case 3: analyse gold -> use whatever analysis is necessary",
            ["analyse gold", "use whatever analysis is necessary"],
        ),
        "case4_outlook": await _run_sequence(
            "Case 4: analyse gold -> outlook",
            ["analyse gold", "outlook"],
        ),
        "case5_descriptive_fundamental": await _run_sequence(
            "Case 5: analyse gold -> rates/inflation/Fed",
            ["analyse gold", "focus on rates, inflation, and Fed policy"],
        ),
        "case6_combined": await _run_sequence(
            "Case 6: macro + momentum next month",
            ["Combine the macro picture with price momentum for the next month"],
        ),
    }

    Path(__file__).resolve().parent.joinpath("live_smoke_scopes_results.json").write_text(
        json.dumps(out, indent=2, default=str),
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main())
