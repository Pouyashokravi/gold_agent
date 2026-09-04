"""Export full answers + key execution fields for report generation."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
raw = json.loads((BACKEND / "v2_e2e_raw_results.json").read_text(encoding="utf-8"))

# Redact anything that looks like a key
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]{10,}|tvly-[A-Za-z0-9_-]{10,}|api[_-]?key[\"']?\s*[:=]\s*[\"'][^\"']+)", re.I)


def scrub(s: str) -> str:
    return SECRET_RE.sub("[REDACTED]", s)


export = []
for r in raw["results"]:
    item = {"id": r["id"], "name": r["name"], "status": r["status"], "conversation_id": r.get("conversation_id"), "turns": []}
    for t in r["turns"]:
        s = t.get("summary") or {}
        events = t.get("events") or []
        # Keep only event type timeline, not full payloads (smaller + safer)
        timeline = []
        for ev in events:
            timeline.append({
                "type": ev.get("type"),
                "agent": ev.get("agent"),
                "message": scrub(str(ev.get("message") or ""))[:200],
            })
        # Extract conflict details if present
        syn = s.get("synthesis") or {}
        ac = syn.get("agent_conflicts")
        item["turns"].append({
            "query": t.get("query"),
            "trade_mode": t.get("trade_mode"),
            "note": t.get("note"),
            "ok": t.get("ok"),
            "error": t.get("error"),
            "latency_s": t.get("latency_s"),
            "answer": scrub(t.get("answer") or ""),
            "path": s.get("path"),
            "route_gate": s.get("route_gate"),
            "complexity": s.get("complexity"),
            "agents_enabled": s.get("agents_enabled"),
            "agents_executed": s.get("agents_executed"),
            "tools": s.get("tools"),
            "memory_msgs": s.get("memory_msgs"),
            "memory_hits": s.get("memory_hits"),
            "replanned": s.get("replanned"),
            "replan_msgs": s.get("replan_msgs"),
            "review": s.get("review"),
            "parallel_overlap_sse": s.get("parallel_overlap_sse"),
            "plan": s.get("plan"),
            "synthesis_summary": {
                "overall_direction": syn.get("overall_direction"),
                "confidence": syn.get("confidence"),
                "horizon": syn.get("horizon"),
                "key_drivers": syn.get("key_drivers"),
                "key_risks": syn.get("key_risks"),
                "contradictions": syn.get("contradictions"),
                "agreements": syn.get("agreements"),
                "dominant_conflict": (ac or {}).get("dominant_conflict") if isinstance(ac, dict) else None,
                "confidence_adjustment": (ac or {}).get("confidence_adjustment") if isinstance(ac, dict) else None,
                "relations": (ac or {}).get("relations") if isinstance(ac, dict) else None,
                "trade_bias": (syn.get("trade_setup") or {}).get("bias"),
                "trade_setup": syn.get("trade_setup"),
                "base_case": syn.get("base_case"),
                "bull_case": syn.get("bull_case"),
                "bear_case": syn.get("bear_case"),
                "economic_surprises_in_syn": syn.get("economic_surprises"),
            } if syn else None,
            "warnings": s.get("warnings"),
            "errors": s.get("errors"),
            "sse_timeline": timeline,
            "provider_failure_simulated": t.get("provider_failure_simulated"),
        })
    export.append(item)

out = BACKEND / "v2_e2e_report_source.json"
out.write_text(json.dumps(export, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
print("Wrote", out, "bytes", out.stat().st_size)
# also print answer lengths
for item in export:
    for i, t in enumerate(item["turns"]):
        print(f"{item['id']:02d}.{i+1} path={t['path']} lat={t['latency_s']} ans={len(t['answer'])} replan={t['replanned']} parallel={t['parallel_overlap_sse']}")
