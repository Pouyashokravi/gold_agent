"""
Run 20 user-job scenarios against the Gold Research Agent pipeline via HTTP SSE.
Collects horizon, agent routing, and final answers for evaluation.
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

API_BASE = "http://127.0.0.1:8000"


@dataclass
class Expected:
    horizon: str | None = None  # None = any acceptable
    horizon_acceptable: list[str] | None = None
    news: bool | None = None
    fundamental: bool | None = None
    technical: bool = True
    trade_mode: bool = False
    answer_must_contain: list[str] = field(default_factory=list)
    answer_must_not_contain: list[str] = field(default_factory=list)
    context_aware: bool = False


@dataclass
class UserJob:
    id: int
    name: str
    query: str
    expected: Expected
    setup_messages: list[tuple[str, str]] = field(default_factory=list)  # (role, content) prior turns


USER_JOBS: list[UserJob] = [
    UserJob(1, "Intraday price (EN)", "What is the current XAU/USD price right now?",
            Expected(horizon="intraday", news=False, fundamental=False, technical=True,
                     answer_must_contain=["xau"])),
    UserJob(2, "Intraday price (FA)", "قیمت فعلی طلا و XAU/USD الان چنده؟",
            Expected(horizon="intraday", news=False, fundamental=False, technical=True)),
    UserJob(3, "News today (EN)", "What are the most important gold news headlines today?",
            Expected(horizon_acceptable=["intraday", "few_days"], news=True, technical=True)),
    UserJob(4, "News today (FA)", "مهم‌ترین اخبار طلا امروز چیه؟",
            Expected(horizon_acceptable=["intraday", "few_days"], news=True, technical=True)),
    UserJob(5, "Fed multi-horizon event", (
        "How would an unexpected 50 basis point Federal Reserve rate cut affect "
        "XAU/USD in the intraday, short-term, and medium-term horizons?"
    ), Expected(
        horizon_acceptable=["medium_term", "short_term", "few_days", "intraday"],
        news=True, fundamental=True, technical=True,
        answer_must_contain=["fed", "rate"],
    )),
    UserJob(6, "Trade setup query", "Give me a gold buy setup with entry zone, stop loss and take profit",
            Expected(horizon="intraday", news=False, fundamental=False, technical=True,
                     answer_must_contain=["entry", "stop"])),
    UserJob(7, "Trade mode toggle", "Analyze XAU/USD for a scalp trade",
            Expected(horizon="intraday", news=False, fundamental=False, technical=True,
                     trade_mode=True, answer_must_contain=["trade"])),
    UserJob(8, "Short-term technical", "Technical analysis of gold for the next 2-3 weeks",
            Expected(horizon="short_term", technical=True)),
    UserJob(9, "Medium-term outlook", "What is the medium-term outlook for gold over the next 3 months?",
            Expected(horizon="medium_term", fundamental=True, technical=True)),
    UserJob(10, "Long-term structural", "Long-term structural view on gold for the next 2 years",
             Expected(horizon_acceptable=["long_term", "ages"], fundamental=True, technical=True)),
    UserJob(11, "Fundamental macro", "How do real yields and the US dollar affect gold fundamentals?",
             Expected(fundamental=True, technical=True)),
    UserJob(12, "Market move explanation", "Why did gold move sharply today?",
             Expected(horizon_acceptable=["intraday", "few_days"], news=True, technical=True)),
    UserJob(13, "Historical analysis", "How did gold perform during the 2020 pandemic crash?",
             Expected(horizon_acceptable=["ages", "long_term", "medium_term"],
                      answer_must_contain=["2020"])),
    UserJob(14, "Market outlook combined", "Give me a full market outlook on XAU/USD including news and fundamentals",
             Expected(news=True, fundamental=True, technical=True)),
    UserJob(15, "Few days / this week", "What should I expect from gold this week?",
             Expected(horizon="few_days", technical=True)),
    UserJob(16, "Multi-intent news+tech", "Today's gold news and key support/resistance levels",
             Expected(horizon_acceptable=["intraday", "few_days"], news=True, technical=True)),
    UserJob(17, "Persian trade query", "یک پوزیشن خرید طلا با استاپ و تارگت پیشنهاد بده",
             Expected(horizon="intraday", news=False, fundamental=False, technical=True)),
    UserJob(18, "Price only minimal", "XAU/USD price?",
             Expected(horizon="intraday", news=False, fundamental=False, technical=True)),
    UserJob(19, "CPI event impact", "What would happen to gold if CPI comes in much hotter than expected?",
             Expected(news=True, fundamental=True, technical=True,
                      answer_must_contain=["inflation", "cpi"])),
    UserJob(20, "Follow-up context", "What about the downside risk?",
             Expected(context_aware=True, technical=True),
             setup_messages=[
                 ("user", "What is the medium-term outlook for gold over the next 3 months?"),
                 ("assistant", "Gold's medium-term outlook is cautiously bullish due to falling real yields and central bank demand."),
             ]),
]


@dataclass
class JobResult:
    job: UserJob
    success: bool
    error: str | None
    horizon: str | None
    intents: list[str]
    agents: dict[str, bool]
    answer: str
    issues: list[str]
    warnings: list[str]


# English / Persian keyword alternatives for answer validation
KEYWORD_ALIASES: dict[str, list[str]] = {
    "fed": ["fed", "federal reserve", "fomc", "فدرال", "فدرال رزرو"],
    "rate": ["rate", "rates", "basis point", "bps", "نرخ", "بهره"],
    "inflation": ["inflation", "cpi", "تورم", "تورمی"],
    "gold": ["gold", "xau", "طل"],
    "2020": ["2020", "pandemic", "covid", "پاندمی"],
    "xau": ["xau", "xau/usd", "gold", "طل"],
}


def _answer_contains(answer_lower: str, phrase: str) -> bool:
    aliases = KEYWORD_ALIASES.get(phrase.lower(), [phrase.lower()])
    return any(a.lower() in answer_lower for a in aliases)
    events = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if block.startswith("data: "):
            try:
                events.append(json.loads(block[6:]))
            except json.JSONDecodeError:
                pass
    return events


def evaluate_job(job: UserJob, events: list[dict], answer: str) -> JobResult:
    exp = job.expected
    issues: list[str] = []
    warnings: list[str] = []

    profile: dict = {}
    agents: dict[str, bool] = {"news": False, "fundamental": False, "technical": False}
    policy_warnings: list[str] = []

    for ev in events:
        t = ev.get("type", "")
        if t == "understanding_completed":
            profile = ev.get("data") or {}
        elif t == "check_completed":
            agents = (ev.get("data") or {}).get("agents") or agents
            policy_warnings = (ev.get("data") or {}).get("warnings") or []
        elif t == "planning_completed":
            plan = ev.get("data") or {}
            agents = {
                "news": bool((plan.get("news_agent") or {}).get("enabled")),
                "fundamental": bool((plan.get("fundamental_agent") or {}).get("enabled")),
                "technical": bool((plan.get("technical_agent") or {}).get("enabled")),
            }

    horizon = profile.get("horizon")
    intents = profile.get("intents") or []

    # Horizon check
    if exp.horizon and horizon != exp.horizon:
        issues.append(f"Horizon: expected '{exp.horizon}', got '{horizon}'")
    if exp.horizon_acceptable and horizon not in exp.horizon_acceptable:
        issues.append(f"Horizon: expected one of {exp.horizon_acceptable}, got '{horizon}'")

    # Agent routing
    if exp.news is not None and agents.get("news") != exp.news:
        issues.append(f"News agent: expected enabled={exp.news}, got {agents.get('news')}")
    if exp.fundamental is not None and agents.get("fundamental") != exp.fundamental:
        issues.append(f"Fundamental agent: expected enabled={exp.fundamental}, got {agents.get('fundamental')}")
    if exp.technical and not agents.get("technical"):
        issues.append("Technical agent should be enabled but was not")

    # Answer completeness
    answer_lower = answer.lower()
    if not answer or len(answer.strip()) < 50:
        issues.append(f"Answer too short ({len(answer)} chars) — likely incomplete")

    for phrase in exp.answer_must_contain:
        if not _answer_contains(answer_lower, phrase):
            issues.append(f"Answer missing expected phrase: '{phrase}'")

    for phrase in exp.answer_must_not_contain:
        if phrase.lower() in answer_lower:
            issues.append(f"Answer contains forbidden phrase: '{phrase}'")

    # Context awareness (job 20)
    if exp.context_aware:
        context_markers = ("downside", "risk", "bearish", "support", "decline", "fall", "pullback", "ضعیف", "ریسک", "نزول")
        if not any(m in answer_lower for m in context_markers):
            issues.append("Follow-up answer doesn't appear context-aware (no risk/downside discussion)")

    # Trade mode
    if exp.trade_mode:
        trade_markers = ("entry", "stop", "trade setup", "bias", "take profit", "ورود", "استاپ")
        if not any(m in answer_lower for m in trade_markers):
            issues.append("Trade mode answer missing trade setup details")

    # Generic quality
    if "i cannot" in answer_lower or "i don't have access" in answer_lower:
        issues.append("Answer indicates inability to provide analysis")
    if answer_lower.count("n/a") > 5:
        warnings.append("Answer has many N/A values")

    for w in policy_warnings:
        warnings.append(f"Policy warning: {w}")

    return JobResult(
        job=job,
        success=len(issues) == 0,
        error=None,
        horizon=horizon,
        intents=intents,
        agents=agents,
        answer=answer,
        issues=issues,
        warnings=warnings,
    )


async def seed_conversation(client: httpx.AsyncClient, messages: list[tuple[str, str]]) -> str:
    resp = await client.post(f"{API_BASE}/api/conversations")
    resp.raise_for_status()
    conv_id = resp.json()["conversation_id"]
    # Direct DB seed would be ideal; use API history by running dummy or rely on orchestrator history fetch
    # The orchestrator reads from DB — we need to insert messages via a workaround.
    # Use internal repo if available, else skip seeding.
    try:
        from app.db import repositories
        for role, content in messages:
            await repositories.add_message(conv_id, role, content)
    except Exception:
        pass
    return conv_id


async def run_job(client: httpx.AsyncClient, job: UserJob) -> JobResult:
    try:
        if job.setup_messages:
            conv_id = await seed_conversation(client, job.setup_messages)
        else:
            resp = await client.post(f"{API_BASE}/api/conversations")
            resp.raise_for_status()
            conv_id = resp.json()["conversation_id"]

        payload = {
            "query": job.query,
            "conversation_id": conv_id,
            "trade_mode": job.expected.trade_mode,
        }

        answer_parts: list[str] = []
        events: list[dict] = []
        fallback_warnings: list[str] = []
        fatal_error: str | None = None

        async with client.stream("POST", f"{API_BASE}/api/analyze", json=payload, timeout=300.0) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                return JobResult(job, False, f"HTTP {resp.status_code}: {body.decode()[:200]}",
                                 None, [], {}, "", [f"HTTP error {resp.status_code}"], [])

            buffer = ""
            async for chunk in resp.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    part, buffer = buffer.split("\n\n", 1)
                    part = part.strip()
                    if part.startswith("data: "):
                        try:
                            ev = json.loads(part[6:])
                            events.append(ev)
                            ev_type = ev.get("type", "")
                            agent = ev.get("agent", "")
                            message = ev.get("message", "")

                            if ev_type == "answer_delta":
                                answer_parts.append((ev.get("data") or {}).get("delta", ""))
                            elif ev_type == "answer_completed":
                                final = (ev.get("data") or {}).get("answer")
                                if final:
                                    answer_parts = [final]
                            elif ev_type in ("agent_fallback",):
                                fallback_warnings.append(f"{agent}: {message}")
                            elif ev_type == "error":
                                # Specialist fallbacks are recoverable; only abort on fatal pipeline errors.
                                recoverable = (
                                    "fallback" in message.lower()
                                    or agent in ("news_agent", "fundamental_agent", "technical_agent",
                                                 "short_term_agent", "long_term_agent")
                                )
                                if recoverable:
                                    fallback_warnings.append(f"{agent}: {message}")
                                elif agent in ("query_understanding", "gold_planner", "synthesis", "answer", ""):
                                    fatal_error = message or "Pipeline error"
                        except json.JSONDecodeError:
                            pass

        if fatal_error:
            return JobResult(job, False, fatal_error, None, [], {}, "",
                             [fatal_error], fallback_warnings)

        answer = "".join(answer_parts)
        result = evaluate_job(job, events, answer)
        result.warnings.extend(fallback_warnings)
        return result

    except Exception as exc:
        return JobResult(job, False, str(exc), None, [], {}, "", [str(exc)], [])


async def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", type=int, nargs="*", help="Run only these job IDs")
    args = parser.parse_args()

    # Ensure DB repo works when seeding conversations
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 70)
    print("Gold Research Agent — 20 User Job Test Suite")
    print("=" * 70)

    health = httpx.get(f"{API_BASE}/health", timeout=10)
    if health.status_code != 200:
        print(f"ERROR: Backend not reachable at {API_BASE}")
        return 1
    print(f"Backend OK: {health.json()}\n")

    jobs_to_run = USER_JOBS
    if args.only:
        ids = set(args.only)
        jobs_to_run = [j for j in USER_JOBS if j.id in ids]

    results: list[JobResult] = []
    async with httpx.AsyncClient() as client:
        for job in jobs_to_run:
            print(f"[{job.id:02d}/{len(jobs_to_run)}] Running: {job.name} ...", flush=True)
            result = await run_job(client, job)
            results.append(result)
            status = "PASS" if result.success else "FAIL"
            print(f"       {status} | horizon={result.horizon} | agents={result.agents}")
            if result.issues:
                for issue in result.issues:
                    print(f"       ISSUE: {issue}")
            print()

    # Summary report
    passed = sum(1 for r in results if r.success)
    failed = len(results) - passed

    report = {
        "summary": {"total": len(results), "passed": passed, "failed": failed},
        "results": [],
    }

    print("=" * 70)
    print("FINAL REPORT")
    print("=" * 70)
    print(f"Total: {len(results)} | Passed: {passed} | Failed: {failed}\n")

    for r in results:
        report["results"].append({
            "id": r.job.id,
            "name": r.job.name,
            "query": r.job.query,
            "success": r.success,
            "horizon": r.horizon,
            "intents": r.intents,
            "agents": r.agents,
            "issues": r.issues,
            "warnings": r.warnings,
            "answer_preview": r.answer[:500] if r.answer else "",
            "error": r.error,
        })

    out_path = __import__("pathlib").Path(__file__).resolve().parents[1] / "test_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Full report saved to: {out_path}\n")

    for r in results:
        status_label = "PASS" if r.success else "FAIL"
        print(f"[{status_label}] Job {r.job.id:02d}: {r.job.name}")
        safe_query = r.job.query[:70].encode("ascii", errors="replace").decode("ascii")
        print(f"   Query: {safe_query}...")
        print(f"   Horizon: {r.horizon} | Intents: {r.intents}")
        print(f"   Agents: news={r.agents.get('news')} fund={r.agents.get('fundamental')} tech={r.agents.get('technical')}")
        if r.issues:
            print(f"   Issues: {'; '.join(r.issues)}")
        if r.warnings:
            print(f"   Warnings: {'; '.join(r.warnings)}")
        print()

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
