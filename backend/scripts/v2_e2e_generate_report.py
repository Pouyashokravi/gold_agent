"""Generate GOLD_AGENT_V2_TEST_REPORT.md (+ HTML) from scrubbed E2E evidence."""
from __future__ import annotations

import html
import json
import statistics
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
SRC = json.loads((BACKEND / "v2_e2e_report_source.json").read_text(encoding="utf-8"))

# Manual evaluator judgments grounded in observed evidence (not invented answers).
# Scores: answer, architecture, data_freshness (or None), efficiency, overall, verdict, problems, fix, analysis
EVAL = {
    1: {
        "answer": 9, "arch": 10, "data": 9, "eff": 10, "overall": 9.5, "verdict": "PASS",
        "analysis": (
            "Gate correctly selected FAST. Quote was fetched via Twelve Data after STM reported quote=STALE; "
            "no News/Fundamental/Technical specialists ran. Answer was concise with price, high/low and % change. "
            "Architecture matched the Fast Path contract."
        ),
        "problems": [],
        "fix": None,
        "expected": "FAST path; direct market data; no research agents.",
    },
    2: {
        "answer": 5, "arch": 7, "data": 7, "eff": 10, "overall": 6.5, "verdict": "PARTIAL",
        "analysis": (
            "FAST path activated and reused session quote from STM (0.017s, no new tool call) — efficient. "
            "However the high/low gate only returns ONE field (`which` high OR low), so the answer reported "
            "today's high but omitted today's low despite the user asking for both."
        ),
        "problems": [
            "Fast high/low handler returns only high or only low, not both when the user asks for both.",
            "Gate regex classifies the query as high_low with a single `which` based on first keyword match.",
        ],
        "fix": "When query contains both high and low, return both values from the session quote in one FAST answer.",
        "expected": "Direct structured retrieval of today's high and low; no research agents.",
    },
    3: {
        "answer": 9, "arch": 10, "data": 8, "eff": 9, "overall": 9, "verdict": "PASS",
        "analysis": (
            "Manager planned only agent_technical at horizon=few_days. News/Fundamental stayed disabled. "
            "Answer covered trend, momentum and S/R with moderate-high confidence. Selective routing worked."
        ),
        "problems": [],
        "fix": None,
        "expected": "Technical primary; few_days; no automatic news/fundamental.",
    },
    4: {
        "answer": 8, "arch": 4, "data": 7, "eff": 3, "overall": 5.5, "verdict": "PARTIAL",
        "analysis": (
            "Answer quality was decent (ranked/news-driven narrative). Architecture failed the news-only contract: "
            "Manager enabled news+fundamental+technical and all three executed in parallel. "
            "Unnecessary cost for a news ranking question."
        ),
        "problems": [
            "Over-routing: news-only query executed Fundamental and Technical agents.",
            "Horizon set to intraday for 'recent news' — acceptable but aggressive.",
        ],
        "fix": "Tighten Manager/plan constraints so news-only questions do not auto-enable fund/tech without justification.",
        "expected": "News Agent primary; tech not without justification; event weighting visible.",
    },
    5: {
        "answer": 9, "arch": 9, "data": 8, "eff": 8, "overall": 8.5, "verdict": "PASS",
        "analysis": (
            "Manager enabled only Fundamental initially; a bounded replan added tool_quote — useful, not performative. "
            "Answer explained Fed/real yields/USD/inflation mechanisms rather than dumping series. Technical did not dominate."
        ),
        "problems": [],
        "fix": None,
        "expected": "Fundamental Agent; macro mechanisms; tech not dominant.",
    },
    6: {
        "answer": 9, "arch": 9, "data": 8, "eff": 8, "overall": 8.5, "verdict": "PASS",
        "analysis": (
            "All three specialists ran with SSE-detected parallel overlap; horizon=medium_term for 3-month outlook. "
            "Final answer synthesized a coherent thesis with confidence. Complexity labeled STANDARD rather than RESEARCH "
            "despite multi-domain scope — minor labeling issue only."
        ),
        "problems": [
            "Complexity remained STANDARD for a full multi-domain 3-month request (gate/manager labeling).",
        ],
        "fix": "Map explicit multi-domain medium-term outlooks to ComplexityLevel.RESEARCH.",
        "expected": "RESEARCH path; N+F+T parallel; medium_term; coherent thesis.",
    },
    7: {
        "answer": 8, "arch": 8, "data": 7, "eff": 8, "overall": 8, "verdict": "PASS",
        "analysis": (
            "Manager chose news+fundamental (no technical) for today's move — evidence-driven planning. "
            "Answer identified primary drivers and relative importance. Did not call an explicit quote tool; "
            "relied on specialist context for the move description."
        ),
        "problems": [
            "No direct tool_quote observed; causal explanation of 'today's move' would benefit from explicit price delta evidence.",
        ],
        "fix": "For intraday causal 'why did it move' queries, require tool_quote (and ideally session range) in the plan.",
        "expected": "Evidence-needed planning; price + news/fund; causal prioritization.",
    },
    8: {
        "answer": 7, "arch": 7, "data": 6, "eff": 6, "overall": 6.5, "verdict": "PARTIAL",
        "analysis": (
            "System ran news+fund+tech with a replan adding tool_quote. Answer discussed surprises at a narrative level "
            "and stayed Neutral. Hard to verify Actual vs Forecast fields were present in evidence (not clearly "
            "surfaced in synthesis economic_surprises). Technical was likely unnecessary for this question."
        ),
        "problems": [
            "Economic Surprise structured Actual/Forecast evidence not clearly visible in synthesis summary.",
            "Technical agent executed for a macro-surprise question without strong justification.",
        ],
        "fix": "Ensure surprise engine outputs are passed into the answer and UI; avoid defaulting tech on for surprise queries.",
        "expected": "Actual vs Forecast when available; no fabrication; mechanism to gold.",
    },
    9: {
        "answer": 8, "arch": 6, "data": 7, "eff": 5, "overall": 6.5, "verdict": "PARTIAL",
        "analysis": (
            "Answer ranked Fed decision first with rationale — aligns with Smart News Weighting intent. "
            "Architecture again over-enabled fundamental+technical for a ranking-of-events question."
        ),
        "problems": [
            "Over-routing to all three specialists for an event-ranking question.",
        ],
        "fix": "Prefer news (+ optional fund) for event ranking; keep tech optional.",
        "expected": "Event weighting drives ranking; not recency-only.",
    },
    10: {
        "answer": 8, "arch": 7, "data": 7, "eff": 7, "overall": 7.5, "verdict": "PARTIAL",
        "analysis": (
            "All three specialists ran in parallel as required. Final answer argued agreement (bearish) rather than conflict. "
            "synthesis.agent_conflicts.dominant_conflict was null in captured payload — Conflict Matrix signal was weak/absent "
            "even though the feature is wired. Confidence still produced."
        ),
        "problems": [
            "dominant_conflict was null in captured synthesis for an explicit conflict-comparison query.",
            "UI/conflict contract may be under-populated when agents agree.",
        ],
        "fix": "Always emit agent_conflicts structure (including AGREE / NO_CONFLICT) so the matrix is observable.",
        "expected": "Multi-specialist + Conflict Analysis; direction vs horizon conflicts; confidence impact.",
    },
    11: {
        "answer": 9, "arch": 9, "data": 8, "eff": 8, "overall": 9, "verdict": "PASS",
        "analysis": (
            "Manager separated horizons in the answer (few-days bearish vs 3-month bullish potential) without treating them "
            "as a single contradiction. Technical+Fundamental only — appropriate. Strong horizon-aware reasoning."
        ),
        "problems": [
            "Plan horizon field was few_days while query spans medium_term — dual-horizon encoding is only in prose.",
        ],
        "fix": "Consider multi-horizon plan metadata when user explicitly asks for two horizons.",
        "expected": "Horizon separation; not auto-conflict short vs medium.",
    },
    12: {
        "answer": 3, "arch": 3, "data": None, "eff": 5, "overall": 3.5, "verdict": "FAIL",
        "analysis": (
            "Turn 1 correctly clarified with a horizon question and did not launch specialists (excellent). "
            "Turn 2 ('Focus on the next two weeks.') was classified off-topic / out-of-scope because it lacked gold keywords, "
            "so the session did NOT resume analysis. Critical clarification+conversation-state failure."
        ),
        "problems": [
            "Clarification follow-ups without gold keywords are treated as OFF_TOPIC/GENERAL_CHAT.",
            "Prior clarification turn is not used as session context to continue research.",
        ],
        "fix": "If the previous assistant message was a clarification, treat the next user turn as continuing that analysis (inherit gold domain + apply horizon).",
        "expected": "Clarify first; then resume with short_term analysis after user specifies horizon.",
    },
    13: {
        "answer": 9, "arch": 8, "data": 8, "eff": 6, "overall": 8, "verdict": "PASS",
        "analysis": (
            "Turns 2–3 correctly referenced the one-month thesis without restating it. STM showed 3–4 hits. "
            "Turn 3 planned empty tasks with use_prior_thesis and still triggered a news replan — somewhat extra. "
            "Overall multi-turn memory works."
        ),
        "problems": [
            "Follow-up turns still re-ran multiple specialists instead of preferentially reusing thesis when fresh.",
            "Turn 3 replan pulled news despite plan tasks=[] / agents disabled in policy check.",
        ],
        "fix": "When use_prior_thesis and question is about risks/invalidation, answer from thesis unless freshness demands refresh.",
        "expected": "Resolve anaphora; reuse analysis when fresh; research only if needed.",
    },
    14: {
        "answer": 8, "arch": 8, "data": 8, "eff": 8, "overall": 8, "verdict": "PASS",
        "analysis": (
            "Turn 1 FAST quote. Turn 2 did not re-run full research; Manager planned tool_ohlc only and answered with "
            "the prior ~4428.98 price vs range. Memory showed 1 hit. Good working-memory behavior for a compound follow-up."
        ),
        "problems": [
            "Turn 2 used Manager/STANDARD instead of a FAST compound path; still relatively efficient (15s).",
        ],
        "fix": "Optional FAST handler for 'price you just used + vs high/low' using STM quote.",
        "expected": "Reuse fresh quote; fetch only missing high/low/OHLC.",
    },
    15: {
        "answer": 6, "arch": 6, "data": 8, "eff": 5, "overall": 6, "verdict": "PARTIAL",
        "analysis": (
            "After 18s wait (quote TTL=15s), turn 2 showed 0 STM hits and fetched tool_quote — stale invalidation worked. "
            "However gate did not classify 'What is XAU/USD trading at now?' as FAST, so Manager produced a verbose "
            "research-style answer instead of a concise current price. Freshness OK; path efficiency not."
        ),
        "problems": [
            "Price phrasing 'trading at now' misses Fast Path regex → unnecessary Manager call.",
            "Verbose answer for a simple current-price ask after refresh.",
        ],
        "fix": "Expand FAST price patterns (trading at / now / spot) and keep concise quote formatting.",
        "expected": "Stale cache not presented as current; refresh; update STM.",
    },
    16: {
        "answer": 8, "arch": 8, "data": 8, "eff": 8, "overall": 8, "verdict": "PASS",
        "analysis": (
            "Manager planned fund+tech+news in parallel for causal attribution without assuming a single cause. "
            "Review found enough evidence — no replan (correct per 'do not replan performatively'). "
            "Answer ranked drivers. Good evidence-driven planning."
        ),
        "problems": [],
        "fix": None,
        "expected": "Evidence-driven plan; parallel sources; bounded replan only if needed.",
    },
    17: {
        "answer": 8, "arch": 9, "data": 8, "eff": 8, "overall": 8.5, "verdict": "PASS",
        "analysis": (
            "Trader Mode path with tool_quote + technical. Synthesis trade_bias=SHORT with setup fields. "
            "Did not force a buy. Levels presented in answer. Appropriate specialist selection."
        ),
        "problems": [
            "News/fundamental risk overlay was not included (may be OK if technical alone justified SHORT).",
        ],
        "fix": None,
        "expected": "Trader Mode; technical central; coherent setup or no force.",
    },
    18: {
        "answer": 9, "arch": 9, "data": 8, "eff": 8, "overall": 9, "verdict": "PASS",
        "analysis": (
            "With Trader Mode on, synthesis trade_bias=NO_TRADE and the answer explicitly refused to force BUY/SELL "
            "citing unclear/conflicting setup. Strong anti-signal-forcing discipline."
        ),
        "problems": [],
        "fix": None,
        "expected": "NO_TRADE valid; explain briefly when conflicting/weak.",
    },
    19: {
        "answer": 7, "arch": 7, "data": 5, "eff": 7, "overall": 6.5, "verdict": "PARTIAL",
        "analysis": (
            "Twelve Data was monkeypatched to fail in-process. Pipeline did not crash and still produced a full prose "
            "outlook via Fundamental/Technical paths (fallbacks). However the final answer did not clearly disclose "
            "that live XAU market-data provider failed — risk of sounding more data-complete than it was. "
            "First attempt also showed missing OPENAI_API_KEY when env not exported to the SDK (test harness issue)."
        ),
        "problems": [
            "Degraded mode did not clearly label unavailable Twelve Data / quote evidence in the user-facing answer.",
            "In-process eval requires OPENAI_API_KEY in os.environ (Agents SDK); pydantic .env alone is insufficient.",
        ],
        "fix": "When tool_quote/Twelve Data returns error, Manager Answer must state market-data gap explicitly; export API key for in-process runners.",
        "expected": "No crash; recognize missing evidence; degraded/limited answer; no fabrication; SSE completes.",
    },
    20: {
        "answer": 9, "arch": 8, "data": 8, "eff": 7, "overall": 8, "verdict": "PASS",
        "analysis": (
            "RESEARCH complexity, all three specialists, parallel overlap, synthesized base/bull/bear style outlook, "
            "no Trader Entry/SL/TP. Horizon labeled short_term for a 1–3 month ask (should be medium_term). "
            "Plan listed duplicate agent_fundamental tasks. Overall strong integration test."
        ),
        "problems": [
            "Horizon short_term for 1–3 months (expected medium_term).",
            "Duplicate fundamental tasks in Manager plan.",
            "dominant_conflict null despite asking for agreements/conflicts.",
        ],
        "fix": "Map 1–3 months to medium_term; dedupe plan tasks; always populate conflict structure.",
        "expected": "RESEARCH; parallel specialists; surprise/weighting/conflict; scenarios; no trade setup.",
    },
}


def get_test(tid: int):
    for r in SRC:
        if r["id"] == tid:
            return r
    return None


def latencies():
    vals = []
    for r in SRC:
        for t in r["turns"]:
            if t.get("latency_s") is not None:
                vals.append(t["latency_s"])
    return vals


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Aggregate scores
    answers = [EVAL[i]["answer"] for i in range(1, 21)]
    archs = [EVAL[i]["arch"] for i in range(1, 21)]
    overalls = [EVAL[i]["overall"] for i in range(1, 21)]
    verdicts = [EVAL[i]["verdict"] for i in range(1, 21)]
    passed = sum(1 for v in verdicts if v == "PASS")
    partial = sum(1 for v in verdicts if v == "PARTIAL")
    failed = sum(1 for v in verdicts if v == "FAIL")
    lats = latencies()
    total_lat = sum(lats)
    avg_lat = statistics.mean(lats) if lats else None

    lines: list[str] = []
    def w(s=""):
        lines.append(s)

    w("# Gold Research Agent V2 — End-to-End Test Report")
    w()
    w("**Evaluation type:** Live E2E against running backend (`POST /api/analyze` SSE), plus in-process Twelve Data failure simulation for Test 19.")
    w("**Date of run:** 2026-09-04 (local)")
    w("**Answers:** Captured verbatim from the system — not simulated.")
    w("**Secrets:** Redacted from this report.")
    w()
    w("## Executive Summary")
    w()
    w(f"- **Tests executed:** 20/20")
    w(f"- **Passed:** {passed}")
    w(f"- **Partially passed:** {partial}")
    w(f"- **Failed:** {failed}")
    w(f"- **Blocked:** 0")
    w(f"- **Average Answer Quality:** {statistics.mean(answers):.2f}/10")
    w(f"- **Average Architecture Score:** {statistics.mean(archs):.2f}/10")
    w(f"- **Average Overall Score:** {statistics.mean(overalls):.2f}/10")
    w(f"- **Total measured latency (sum of turns with timing):** {total_lat:.1f}s")
    w(f"- **Average turn latency:** {avg_lat:.1f}s" if avg_lat else "- **Average turn latency:** N/A")
    w("- **Token usage / model cost:** Not exposed by the API/SSE payload in this build → **N/A** (not inventable).")
    w()
    w("### Critical bugs found")
    w("1. **Clarification follow-up broken (Test 12):** after asking for horizon, user reply without gold keywords is treated as out-of-scope — analysis never resumes.")
    w("2. **News-only / event-ranking over-routing (Tests 04, 09):** Manager frequently enables all three specialists when only News is needed.")
    w("3. **Fast high/low incomplete (Test 02):** asking for today's high **and** low returns only one side.")
    w()
    w("### Major architectural issues")
    w("1. Gate does not treat clarification continuations as in-domain research.")
    w("2. Fast Path regex coverage gaps (`trading at now`) push simple price asks onto Manager.")
    w("3. Conflict Analysis often leaves `dominant_conflict` null even for explicit conflict questions (matrix under-observed).")
    w("4. Economic Surprise structured Actual/Forecast evidence not clearly surfaced in final synthesis for Test 08.")
    w()
    w("## Summary Table")
    w()
    w("| # | Test | Path | Agents | Memory | Parallel | Replan | Answer | Architecture | Overall | Result |")
    w("|---|---|---|---|---|---|---|---:|---:|---:|---|")

    for i in range(1, 21):
        t = get_test(i)
        ev = EVAL[i]
        # primary turn = last turn for multi, or first
        turns = t["turns"]
        primary = turns[-1] if i == 12 else turns[0]
        if i in (13, 14, 15):
            # show multi-turn summary
            paths = "/".join(str(x.get("path")) for x in turns)
            agents = ",".join(sorted({a for x in turns for a in (x.get("agents_executed") or []) if a.endswith("_agent") or a == "gold_manager"}))
            mem = "yes" if any(x.get("memory_msgs") for x in turns) else "no"
            par = "yes" if any(x.get("parallel_overlap_sse") for x in turns) else "no"
            rep = "yes" if any(x.get("replanned") for x in turns) else "no"
            path = paths
        else:
            path = primary.get("path")
            agents = ",".join(a for a in (primary.get("agents_executed") or []) if a.endswith("_agent") or a in ("gold_manager", "tool", "tool_quote", "tool_ohlc"))
            mem = "yes" if primary.get("memory_msgs") else "no"
            # note memory hit text
            if primary.get("memory_msgs"):
                joined = " ".join(primary["memory_msgs"])
                if "STALE" in joined or "0 hits" in joined or "miss" in joined:
                    mem = "checked"
                if any("hits" in m and not m.endswith("0 hits") for m in primary["memory_msgs"]):
                    mem = "hit/checked"
            par = "yes" if primary.get("parallel_overlap_sse") else "no"
            rep = "yes" if primary.get("replanned") else "no"
        w(f"| {i:02d} | {t['name'][:40]} | {path} | {agents[:40]} | {mem} | {par} | {rep} | {ev['answer']} | {ev['arch']} | {ev['overall']} | {ev['verdict']} |")

    w()
    w("---")
    w()

    for i in range(1, 21):
        t = get_test(i)
        ev = EVAL[i]
        w(f"# Test {i:02d} — {t['name']}")
        w()
        w("## User Question")
        for j, turn in enumerate(t["turns"], 1):
            if len(t["turns"]) > 1:
                w(f"**Turn {j}:**")
            w()
            w(turn["query"])
            w()
            if turn.get("trade_mode"):
                w("*(Trader Mode: ON)*")
                w()
            if turn.get("note"):
                w(f"*Note: {turn['note']}*")
                w()

        w("## Agent Answer")
        for j, turn in enumerate(t["turns"], 1):
            if len(t["turns"]) > 1:
                w(f"### Turn {j} answer")
            w()
            w(turn.get("answer") or "*(empty)*")
            w()

        # Execution from primary / all turns
        w("## Execution")
        for j, turn in enumerate(t["turns"], 1):
            prefix = f"Turn {j} — " if len(t["turns"]) > 1 else ""
            w(f"**{prefix}Path:** {turn.get('path')}")
            w(f"**{prefix}Gate route/complexity:** {turn.get('route_gate')} / {turn.get('complexity')}")
            w(f"**{prefix}Agents executed:** {turn.get('agents_executed')}")
            w(f"**{prefix}Agents enabled (policy):** {turn.get('agents_enabled')}")
            w(f"**{prefix}Tools/providers:** {turn.get('tools')}")
            plan = turn.get("plan") or {}
            if plan:
                w(f"**{prefix}Plan horizon:** {plan.get('horizon')}")
                w(f"**{prefix}Plan tasks:** {[x.get('kind') for x in (plan.get('tasks') or [])]}")
                w(f"**{prefix}Plan rationale:** {plan.get('rationale')}")
            w(f"**{prefix}Models used:** Not reported in SSE (Manager/specialists per server config: MANAGER_MODEL / NEWS|FUNDAMENTAL|TECHNICAL_MODEL).")
            w(f"**{prefix}Memory/cache:** {turn.get('memory_msgs')}")
            w(f"**{prefix}Memory hits payload:** {turn.get('memory_hits')}")
            w(f"**{prefix}Parallel execution (SSE overlap heuristic):** {turn.get('parallel_overlap_sse')}")
            w(f"**{prefix}Replanning:** {turn.get('replanned')} {turn.get('replan_msgs')}")
            w(f"**{prefix}Review:** {turn.get('review')}")
            w(f"**{prefix}SSE stages:** {turn.get('sse_timeline') and [e['type'] for e in turn['sse_timeline']]}")
            w(f"**{prefix}Latency:** {turn.get('latency_s')}s")
            w(f"**{prefix}Token usage:** N/A (not in SSE)")
            w(f"**{prefix}Errors/warnings:** errors={turn.get('errors')} warnings={turn.get('warnings')}")
            if turn.get("provider_failure_simulated"):
                w(f"**{prefix}Provider failure simulated:** {turn.get('provider_failure_simulated')}")
            syn = turn.get("synthesis_summary")
            if syn:
                w(f"**{prefix}Synthesis:** dir={syn.get('overall_direction')} conf={syn.get('confidence')} horizon={syn.get('horizon')} conflict={syn.get('dominant_conflict')} trade_bias={syn.get('trade_bias')}")
            w()

        w("## Expected Behavior")
        w(ev["expected"])
        w()
        w("## Short Analysis")
        w(ev["analysis"])
        w()
        w("## Scores")
        w(f"Answer Quality: {ev['answer']}/10")
        w(f"Architecture Behavior: {ev['arch']}/10")
        df = ev["data"]
        w(f"Data/Freshness: {df}/10" if df is not None else "Data/Freshness: N/A")
        w(f"Efficiency: {ev['eff']}/10")
        w(f"Overall: {ev['overall']}/10")
        w()
        w("## Verdict")
        w(ev["verdict"])
        w()
        w("## Problems Found")
        if ev["problems"]:
            for p in ev["problems"]:
                w(f"- {p}")
        else:
            w("- None observed for this test.")
        w()
        w("## Recommended Fix")
        w(ev["fix"] or "None.")
        w()
        w("---")
        w()

    # Cross-test
    w("# Cross-Test Analysis")
    w()
    w("- **Fast Path effectiveness:** Strong for canonical price queries (T01/T14). Weak on phrasing variants (T15) and high+low (T02).")
    w("- **Gold Manager planning quality:** Generally good task selection for technical-only, fundamental-only, dual-horizon, trader, and full research. Weak on news-only restraint and clarification continuations.")
    w("- **Specialist selection accuracy:** Excellent on T03/T05/T11/T17; poor on T04/T09 over-inclusion.")
    w("- **Direct-tool usage:** Present (tool_quote, tool_ohlc) on several plans; Fast Path uses Twelve Data quote.")
    w("- **Parallel execution:** SSE start/complete interleaving showed overlap on multi-agent tests (T04, T06, T07, T08, T09, T10, T11, T13.1, T16, T18, T20). Not assumed from async alone.")
    w("- **Multi-turn behavior:** Thesis follow-ups work (T13). Clarification resume fails (T12).")
    w("- **Short-term memory:** Quote STM + specialist/thesis hits observed; reuse visible on T02/T13/T14.")
    w("- **Freshness handling:** After TTL wait, T15 showed 0 hits and refreshed — good invalidation; path not FAST.")
    w("- **News / Fundamental / Technical quality:** Prose quality generally strong when specialists run; sometimes overconfident without surfacing evidence gaps.")
    w("- **Economic Surprise / News Weighting:** Narrative present; structured surprise fields not clearly evidenced in synthesis summary.")
    w("- **Conflict Analysis:** Feature wired; `dominant_conflict` often null; agreement case under-instrumented.")
    w("- **Replanning:** Observed on T05/T08/T09/T13.3; correctly skipped when evidence enough (T16).")
    w("- **Trader Mode / NO_TRADE:** T17 SHORT setup; T18 NO_TRADE discipline solid.")
    w("- **Failure resilience:** No crash on simulated Twelve Data failure; disclosure of gap incomplete.")
    w("- **SSE visibility:** Gate, memory, plan, agents, review/replan, synthesis, answer stages emitted as documented.")
    w("- **Cost efficiency:** Fast path is cheap; research questions often over-spend specialists.")
    w("- **Latency:** Fast ~0.02–2s; research turns typically ~20–57s.")
    w("- **Final response quality:** Strong English synthesis overall; occasional language/verbosity mismatches on simple asks.")
    w()

    w("# V2 Architecture Verdict")
    w()
    w("1. **Manager-driven agentic system?** **Mostly yes** — live path is Gate → Manager Plan → tasks → Review/Replan → Synthesis/Answer. Legacy IntentRouter/QueryUnderstanding/GoldPlanner/GoldSynthesis/FinalAnswer were **not** observed in SSE agent names.")
    w("2. **Materially better than fixed pipeline?** **Yes** for Fast Path, selective technical/fundamental routing, trader/NO_TRADE, STM, and bounded replan. Still inherits over-routing habits on news-centric asks.")
    w("3. **Redundant LLM calls still present?** **Yes, situationally** — news-only and some follow-ups re-run extra specialists; clarification breakage causes wasted turns.")
    w("4. **Simple queries cheap/fast?** **Usually** (T01 ~1.8s, T02 ~0.02s). Exceptions when regex misses (T15 → Manager ~17s).")
    w("5. **Manager decides research depth?** **Often** (T03/T05/T07/T11). **Not reliably** for news-only.")
    w("6. **Multi-turn context?** **Works for thesis anaphora (T13)**; **fails for clarification continuation (T12)**.")
    w("7. **STM reduces duplicate retrieval?** **Yes** (T02 memory reuse; T13 hits; T14 prior price).")
    w("8. **Parallel execution real?** **Yes** — multi-agent SSE overlap observed on multiple tests.")
    w("9. **Replanning useful?** **Mostly** — quote backfill / evidence gaps; T16 correctly skipped.")
    w("10. **Specialist conflicts handled?** **Partially** — prose discusses agreement/conflict; structured conflict matrix often empty (`dominant_conflict=null`).")
    w("11. **Trader Mode reliable for demo?** **Yes enough** — coherent SHORT and disciplined NO_TRADE observed.")
    w("12. **Top 5 remaining weaknesses:**")
    w("    1. Clarification follow-up / session continuation")
    w("    2. News-only over-routing")
    w("    3. Fast Path coverage gaps + high/low both")
    w("    4. Weak observable Conflict Matrix / Economic Surprise structure in outputs")
    w("    5. Degraded-provider disclosure to the user")
    w()

    w("# Priority Bug List")
    w()
    w("## P0 — Critical")
    w("- **Clarification continuation treated as off-topic**")
    w("  - Affected: Test 12")
    w("  - Evidence: Turn1 clarify OK; Turn2 answer: out of scope / no gold research")
    w("  - Likely root cause: `classify_gate` lacks 'pending clarification' state; gold-keyword check fails on horizon-only replies")
    w("  - Fix: If last assistant turn was clarification, inherit domain and merge horizon into research plan")
    w()
    w("## P1 — High")
    w("- **News-only / event-rank over-routing to all specialists**")
    w("  - Affected: Tests 04, 09")
    w("  - Evidence: agents_enabled all true; all three executed")
    w("  - Likely root cause: Manager plan + weak constraints for news intent")
    w("  - Fix: Policy constraint: news_analysis primary → fund/tech off unless explicitly needed")
    w("- **Fast high+low returns only one side**")
    w("  - Affected: Test 02")
    w("  - Evidence: Answer only today's high")
    w("  - Likely root cause: `fast_params.which` single-valued")
    w("  - Fix: Detect both keywords; return both high and low")
    w()
    w("## P2 — Medium")
    w("- **Price phrasing misses Fast Path** (`trading at now`)")
    w("  - Affected: Test 15")
    w("  - Evidence: Turn2 path=STANDARD with Manager+tool_quote instead of FAST")
    w("  - Fix: Expand `_PRICE_RE`")
    w("- **Conflict matrix under-populated** (`dominant_conflict` null)")
    w("  - Affected: Tests 10, 20")
    w("  - Fix: Always emit relations including AGREE/NO_CONFLICT")
    w("- **Provider failure not clearly disclosed in user answer**")
    w("  - Affected: Test 19")
    w("  - Fix: Manager Answer must list unavailable providers/evidence gaps")
    w("- **1–3 month horizon labeled short_term**")
    w("  - Affected: Test 20")
    w("  - Fix: Horizon mapping rules in Manager instructions/policy")
    w()
    w("## P3 — Low")
    w("- Duplicate `agent_fundamental` tasks in stress plan (Test 20)")
    w("- Complexity STANDARD vs RESEARCH labeling for full multi-domain outlooks (Test 06)")
    w("- Token/cost telemetry not exposed for evaluation")
    w()
    w("## Architecture Confirmation Checklist")
    w()
    w("| Check | Result |")
    w("|---|---|")
    w("| Old IntentRouter / QueryUnderstanding / GoldPlanner / Synthesis / FinalAnswer on hot path | **Not observed** in SSE agent names |")
    w("| Gold Manager owns plan/review/answer | **Yes** (`gold_manager` planning/review/synthesis/answer events) |")
    w("| Specialists only when useful | **Mostly**; fails on news-only |")
    w("| Simple requests avoid full research | **Yes** for canonical price; **No** for some phrasings |")
    w("| Independent agents overlap in time | **Yes** (SSE overlap) |")
    w("| Memory/cache reuse real | **Yes** (explicit memory_check messages / hits) |")
    w("| Stale financial info refreshed | **Yes** after TTL (Test 15) |")
    w("| No Long-Term / vector user memory | **Confirmed absent** in architecture docs + runtime (STM + chat history only) |")
    w("| Twelve Data preferred for structured market data | **Yes** on Fast Path / tool_quote |")
    w("| Tavily only when appropriate | **News agent path**; not used for simple quotes |")
    w("| SSE stages match work | **Yes** |")
    w("| No secrets in report | **Redacted** |")
    w()
    w("## Raw evidence files")
    w()
    w("- `backend/v2_e2e_raw_results.json` — full SSE payloads")
    w("- `backend/v2_e2e_report_source.json` — scrubbed answers + timelines")
    w("- `backend/scripts/v2_e2e_eval_runner.py` — runner used")
    w()

    md_path = REPO / "GOLD_AGENT_V2_TEST_REPORT.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print("Wrote", md_path)

    # Minimal HTML wrapper
    body = html.escape("\n".join(lines))
    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Gold Research Agent V2 — E2E Test Report</title>
<style>
body {{ font-family: ui-sans-serif, system-ui, sans-serif; max-width: 980px; margin: 2rem auto; padding: 0 1rem; line-height: 1.45; }}
pre {{ white-space: pre-wrap; background: #f6f8fa; padding: 1rem; border-radius: 8px; }}
</style>
</head>
<body>
<h1>Gold Research Agent V2 — E2E Test Report</h1>
<p>Rendered from markdown source. Prefer the .md file for navigation.</p>
<pre>{body}</pre>
</body>
</html>
"""
    html_path = REPO / "GOLD_AGENT_V2_TEST_REPORT.html"
    html_path.write_text(html_doc, encoding="utf-8")
    print("Wrote", html_path)
    print(f"PASS={passed} PARTIAL={partial} FAIL={failed}")
    print(f"Avg answer={statistics.mean(answers):.2f} arch={statistics.mean(archs):.2f} overall={statistics.mean(overalls):.2f}")


if __name__ == "__main__":
    main()
