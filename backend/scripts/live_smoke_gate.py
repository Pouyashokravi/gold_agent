"""Focused live smoke for Gate routing (configured model). Not part of pytest suite."""

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


async def _collect(cid: str, query: str) -> tuple[list[dict], str]:
    events: list[dict] = []
    async for chunk in run_v2_pipeline(query, cid):
        if chunk.startswith("data: "):
            events.append(json.loads(chunk[6:]))
    msgs = await repositories.get_messages(cid, limit=50)
    last = msgs[-1] if msgs else {}
    return events, last


def _diag(last: dict) -> dict:
    meta = last.get("metadata") or {}
    gate = meta.get("gate") or {}
    return {
        "route": meta.get("route"),
        "fast_kind": meta.get("fast_kind"),
        "gate": {
            "action": gate.get("action"),
            "intent": gate.get("intent"),
            "context_relationship": gate.get("context_relationship"),
            "is_follow_up": gate.get("is_follow_up"),
            "fast_kind": gate.get("fast_kind"),
            "resolved_fields": gate.get("resolved_fields"),
            "missing_fields": gate.get("missing_fields"),
            "confidence": gate.get("confidence"),
            "reason": gate.get("reason"),
            "repair_used": gate.get("repair_used"),
            "emergency_fallback": gate.get("emergency_fallback"),
        },
        "content_preview": (last.get("content") or "")[:160],
    }


async def main() -> None:
    db_path = Path(__file__).resolve().parents[1] / "live_smoke_gate.db"
    if db_path.exists():
        db_path.unlink()
    sqlite_mod.DB_PATH = str(db_path)
    await init_db()

    cid_a = str(uuid.uuid4())
    async with sqlite_mod.get_connection() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, created_at) VALUES (?, datetime('now'))",
            (cid_a,),
        )
        await conn.commit()

    print("=== Sequence A: price -> hi -> hello ===")
    results_a = []
    for q in [
        "What is the current XAU/USD price?",
        "hi",
        "hello",
    ]:
        events, last = await _collect(cid_a, q)
        types = [e.get("type") for e in events]
        d = _diag(last)
        d["events"] = types
        d["query"] = q
        results_a.append(d)
        print(json.dumps(d, indent=2, default=str))

    cid_b = str(uuid.uuid4())
    async with sqlite_mod.get_connection() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, created_at) VALUES (?, datetime('now'))",
            (cid_b,),
        )
        await conn.commit()

    print("=== Sequence B: analyse gold -> fundamental -> short term ===")
    results_b = []
    for q in ["analyse gold", "fundamental", "short term"]:
        events, last = await _collect(cid_b, q)
        types = [e.get("type") for e in events]
        d = _diag(last)
        d["events"] = types
        d["query"] = q
        results_b.append(d)
        print(json.dumps(d, indent=2, default=str))

    out = {"sequence_a": results_a, "sequence_b": results_b}
    Path(__file__).resolve().parent.joinpath("live_smoke_gate_results.json").write_text(
        json.dumps(out, indent=2, default=str),
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main())
