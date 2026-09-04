"""Deterministic clarification + fast-path gate (before expensive Manager planning)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.manager import ComplexityLevel, GateRoute
from app.services.policy import GOLD_KEYWORDS, TRADE_KEYWORDS, _contains_gold_keyword


@dataclass
class GateDecision:
    route: GateRoute
    complexity: ComplexityLevel
    reason: str
    clarification_question: str | None = None
    fast_kind: str | None = None  # quote | high_low | rsi | sma | ema | macd | atr
    fast_params: dict | None = None


_PRICE_RE = re.compile(
    r"\b("
    r"current\s+(gold\s+)?price|gold\s+price|xau/?usd\s+price|what(?:'s| is)\s+gold\s+trading\s+at|"
    r"current\s+xau|xau/?usd\s+quote|live\s+(gold\s+)?price|gold\s+quote|"
    r"قیمت\s+طلا|طلا\s+چند"
    r")\b",
    re.I,
)

_HIGH_LOW_RE = re.compile(
    r"\b(today'?s?\s+(gold\s+)?(high|low)|gold\s+(high|low)\s+today|daily\s+(high|low))\b",
    re.I,
)

_INDICATOR_RE = re.compile(
    r"\b(?P<tf>\d+\s*[mhd]|1h|4h|15m|5m|1d|daily)?\s*"
    r"(?P<ind>rsi|sma|ema|macd|atr)\b"
    r"(?:\s*(?:for\s+)?(?:gold|xau/?usd))?",
    re.I,
)

_GREETING_RE = re.compile(
    r"^\s*(hi|hello|hey|thanks|thank you|bye|goodbye|how are you|what(?:'s| is) your name|"
    r"who are you|what can you do|help)\b.*$",
    re.I,
)

_AMBIGUOUS_ANALYZE_RE = re.compile(
    r"^\s*((please\s+)?(analyze|analyse|research|look at|review)\s+(gold|xau/?usd)(\s+for\s+me)?|"
    r"(give me|need)\s+(a\s+)?(trade\s+)?(setup|analysis)|"
    r"تحلیل\s+طلا)\s*\.?\s*$",
    re.I,
)

_HORIZON_MARKERS = (
    "intraday", "today", "this week", "few days", "short-term", "short term",
    "medium-term", "medium term", "long-term", "long term", "month", "week",
    "next two", "next 2", "hours", "days", "outlook",
)


def _interval_from_tf(tf: str | None) -> str:
    if not tf:
        return "1h"
    t = tf.lower().replace(" ", "")
    mapping = {
        "1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h",
        "1d": "1day", "daily": "1day", "1min": "1min", "5min": "5min",
        "15min": "15min", "1day": "1day",
    }
    return mapping.get(t, "1h")


def classify_gate(query: str, *, trade_mode: bool = False, has_prior_thesis: bool = False) -> GateDecision:
    q = query.strip()
    ql = q.lower()

    # Follow-ups that reference prior analysis stay on research path (Manager uses thesis).
    follow_up_markers = (
        "downside risk", "upside risk", "invalidate", "what about", "and the",
        "those risks", "that thesis", "that explanation", "same horizon",
    )
    if has_prior_thesis and any(m in ql for m in follow_up_markers):
        return GateDecision(
            route=GateRoute.RESEARCH,
            complexity=ComplexityLevel.STANDARD,
            reason="follow-up on prior thesis",
        )

    if _GREETING_RE.match(q) and not _contains_gold_keyword(q):
        return GateDecision(GateRoute.GENERAL_CHAT, ComplexityLevel.FAST, "greeting/meta")

    if not _contains_gold_keyword(q) and not any(k in ql for k in ("fed", "yield", "inflation", "cpi", "dxy", "macro")):
        # Likely off-topic if no gold/macro terms
        if len(q.split()) > 2 and not _GREETING_RE.match(q):
            return GateDecision(GateRoute.OFF_TOPIC, ComplexityLevel.FAST, "no gold/macro relevance")

    # Fast price
    if _PRICE_RE.search(q) and len(q.split()) <= 12:
        researchish = any(w in ql for w in ("why", "outlook", "analy", "forecast", "because", "despite"))
        if not researchish:
            return GateDecision(
                GateRoute.FAST,
                ComplexityLevel.FAST,
                "current price query",
                fast_kind="quote",
                fast_params={},
            )

    if _HIGH_LOW_RE.search(q) and len(q.split()) <= 12:
        which = "high" if "high" in ql else "low"
        return GateDecision(
            GateRoute.FAST,
            ComplexityLevel.FAST,
            "today high/low",
            fast_kind="high_low",
            fast_params={"which": which},
        )

    ind = _INDICATOR_RE.search(q)
    if ind and len(q.split()) <= 14:
        researchish = any(w in ql for w in ("why", "outlook", "analy", "interpret", "mean", "signal"))
        if not researchish:
            name = ind.group("ind").lower()
            interval = _interval_from_tf(ind.group("tf"))
            return GateDecision(
                GateRoute.FAST,
                ComplexityLevel.FAST,
                f"simple {name} request",
                fast_kind=name,
                fast_params={"interval": interval},
            )

    # Clarification: bare analyze / trade setup without horizon (unless trade_mode provides default)
    if _AMBIGUOUS_ANALYZE_RE.match(q):
        if trade_mode and any(k in ql for k in TRADE_KEYWORDS):
            return GateDecision(
                GateRoute.RESEARCH,
                ComplexityLevel.STANDARD,
                "trade mode supplies intraday default",
            )
        if any(h in ql for h in _HORIZON_MARKERS):
            return GateDecision(GateRoute.RESEARCH, ComplexityLevel.STANDARD, "horizon present")
        if "trade" in ql or "setup" in ql:
            if trade_mode:
                return GateDecision(GateRoute.RESEARCH, ComplexityLevel.STANDARD, "trade_mode on")
            return GateDecision(
                GateRoute.CLARIFY,
                ComplexityLevel.FAST,
                "trade setup needs timeframe/context",
                clarification_question=(
                    "I can build a trade setup — should I focus on intraday (scalp/day trade) "
                    "or a short swing (next few days)? You can also enable Trader Mode for a full desk view."
                ),
            )
        return GateDecision(
            GateRoute.CLARIFY,
            ComplexityLevel.FAST,
            "analysis needs horizon",
            clarification_question=(
                "What time horizon should I focus on — intraday, the next few days, "
                "or a longer-term outlook?"
            ),
        )

    # Complexity heuristic for research path
    research_markers = (
        "why", "despite", "outlook", "scenario", "would", "impact", "combine",
        "multi", "horizon", "medium-term", "long-term", "conflict",
    )
    if sum(1 for m in research_markers if m in ql) >= 2 or "despite" in ql:
        complexity = ComplexityLevel.RESEARCH
    elif any(k in ql for k in ("news", "fundamental", "technical", "macro", "fed", "cpi")):
        complexity = ComplexityLevel.STANDARD
    else:
        complexity = ComplexityLevel.STANDARD

    if any(k in ql for k in GOLD_KEYWORDS) or _contains_gold_keyword(q):
        return GateDecision(GateRoute.RESEARCH, complexity, "gold research query")

    return GateDecision(GateRoute.GENERAL_CHAT, ComplexityLevel.FAST, "default chat")
