"""Deterministic clarification + fast-path gate (before expensive Manager planning)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.common import Horizon
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

# Bare analyze / trade setup (legacy exact-style)
_AMBIGUOUS_ANALYZE_RE = re.compile(
    r"^\s*((please\s+)?(analyze|analyse|research|look at|review)\s+(gold|xau/?usd)(\s+for\s+me)?|"
    r"(give me|need)\s+(a\s+)?(trade\s+)?(setup|analysis)|"
    r"تحلیل\s+طلا)\s*\.?\s*$",
    re.I,
)

# Broader research asks that need an explicit timeframe when none is given
_AMBIGUOUS_RESEARCH_RE = re.compile(
    r"(?is)("
    r"\b(analyze|analyse|research|review|look\s+at)\b.{0,40}\b(gold|xau/?usd)\b|"
    r"\b(gold|xau/?usd)\b.{0,40}\b(outlook|analysis|view|bias|forecast|thesis|direction)\b|"
    r"\b(what(?:'s|\s+is)|how(?:'s|\s+is)|how\s+do\s+you\s+see)\b.{0,40}\b(gold|xau/?usd)\b|"
    r"\b(what\s+do\s+you\s+think|your\s+take|thoughts|opinion)\b.{0,40}\b(gold|xau/?usd)\b|"
    r"\b(should\s+i\s+(buy|sell)|give\s+me\s+a\s+(trade\s+)?(setup|analysis)|trade\s+setup)\b|"
    r"\b(how\s+would|what\s+if|impact|affect)\b.{0,80}\b(gold|xau/?usd)\b"
    r")"
)

# Explicit timeframe / date-range markers (NOT vague words like "outlook")
_EXPLICIT_HORIZON_RE = re.compile(
    r"(?i)\b("
    r"intraday|today|right\s+now|currently|"
    r"this\s+week|this\s+month|few\s+days|next\s+few\s+days|"
    r"short[-\s]?term|medium[-\s]?term|long[-\s]?term|"
    r"next\s+(?:two|2|\d+)\s+(?:hours?|days?|weeks?|months?)|"
    r"next\s+week|next\s+month|next\s+year|"
    r"swing|scalp|day\s*trad(?:e|ing)|"
    r"hourly|weekly|monthly|"
    r"\d+\s*(?:h|hr|hrs|hour|hours|d|day|days|w|wk|week|weeks|mo|month|months|y|year|years)|"
    r"1h|4h|15m|5m|1d"
    r")\b"
)

_HORIZON_REPLY_EXACT = {
    "intraday", "today", "now", "short", "short term", "short-term", "short_term",
    "medium", "medium term", "medium-term", "medium_term",
    "long", "long term", "long-term", "long_term", "longer term", "longer-term",
    "few days", "this week", "this month", "swing", "scalp", "day trade",
    "the next few days", "next few days", "next two weeks", "next 2 weeks",
}

HORIZON_CLARIFY_QUESTION = (
    "What time horizon and date range should I use for this analysis?\n\n"
    "Please pick one (or describe a range):\n"
    "- **Intraday** — today / next few hours\n"
    "- **Few days** — this week / next several sessions\n"
    "- **Short-term** — roughly 1–4 weeks\n"
    "- **Medium-term** — roughly 1–6 months\n"
    "- **Long-term** — 6+ months\n\n"
    "You can also say something like “next two weeks” or “through end of Q2”."
)

TRADE_CLARIFY_QUESTION = (
    "I can build a trade setup — which timeframe should I use?\n\n"
    "- **Intraday** — scalp / day trade (today)\n"
    "- **Swing** — next few days to ~1–2 weeks\n\n"
    "You can also enable Trader Mode for a full desk view."
)


def has_explicit_horizon(query: str) -> bool:
    return bool(_EXPLICIT_HORIZON_RE.search(query or ""))


def looks_like_horizon_reply(query: str) -> bool:
    """True when the user is answering a prior horizon clarification."""
    q = (query or "").strip().lower()
    if not q:
        return False
    if q in _HORIZON_REPLY_EXACT:
        return True
    if has_explicit_horizon(q) and len(q.split()) <= 12:
        return True
    # e.g. "focus on short-term" / "use the next two weeks"
    if len(q.split()) <= 10 and any(
        p in q for p in ("short", "medium", "long", "intraday", "week", "month", "day", "swing", "scalp")
    ):
        return True
    return False


def parse_horizon_from_text(query: str) -> Horizon | None:
    """Best-effort map of user text → Horizon. None if unclear."""
    ql = (query or "").lower()
    if not ql:
        return None
    if re.search(r"\b(intraday|scalp|day\s*trad|today|right\s+now|next\s+few\s+hours|\d+\s*h)\b", ql):
        return Horizon.INTRADAY
    if re.search(r"\b(few\s+days|this\s+week|next\s+few\s+days|next\s+(two|2)\s+days)\b", ql):
        return Horizon.FEW_DAYS
    if re.search(r"\b(short[-\s]?term|swing|next\s+(two|2|\d+)\s+weeks?|1\s*-\s*4\s*weeks?)\b", ql):
        return Horizon.SHORT_TERM
    if re.search(r"\b(medium[-\s]?term|next\s+(few\s+)?months?|1\s*-\s*6\s*months?|this\s+quarter)\b", ql):
        return Horizon.MEDIUM_TERM
    if re.search(r"\b(long[-\s]?term|longer[-\s]?term|6\s*\+\s*months?|next\s+year|structural)\b", ql):
        return Horizon.LONG_TERM
    if re.search(r"\b(ages|multi[-\s]?year|decade)\b", ql):
        return Horizon.AGES
    return None


def merge_clarification_query(prior_goal: str, reply: str) -> str:
    """Combine the original ask with the user's timeframe reply for the Manager."""
    prior = (prior_goal or "").strip()
    reply = (reply or "").strip()
    if not prior:
        return reply
    if not reply:
        return prior
    # Self-contained new research question — prefer the new message
    if _contains_gold_keyword(reply) and has_explicit_horizon(reply) and len(reply.split()) > 4:
        return reply
    if _contains_gold_keyword(reply) and not looks_like_horizon_reply(reply) and len(reply.split()) > 6:
        return reply
    horizon = parse_horizon_from_text(reply)
    if horizon:
        return f"{prior} Focus on the {horizon.value.replace('_', '-')} time horizon (user said: {reply})."
    return f"{prior} Focus on this time horizon / date range: {reply}."


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


def _needs_horizon_clarification(query: str, ql: str) -> bool:
    """Research-style ask about gold without an explicit timeframe."""
    if has_explicit_horizon(query):
        return False
    # Pure news/headline asks do not require a planning horizon first
    if re.search(r"\b(news|headline|headlines)\b", ql) and not re.search(
        r"\b(outlook|analy|forecast|setup|bias|trade)\b", ql
    ):
        return False
    if _AMBIGUOUS_ANALYZE_RE.match(query):
        return True
    if _AMBIGUOUS_RESEARCH_RE.search(query):
        return True
    # Short gold "what/how" prompts without timeframe
    if _contains_gold_keyword(query) and re.search(
        r"\b(outlook|analysis|view|bias|forecast|direction|setup)\b", ql
    ):
        return True
    return False


def classify_gate(
    query: str,
    *,
    trade_mode: bool = False,
    has_prior_thesis: bool = False,
    pending_clarification: bool = False,
    pending_goal: str | None = None,
) -> GateDecision:
    q = query.strip()
    ql = q.lower()

    # Resume after we asked for a timeframe: treat horizon replies as research.
    if pending_clarification:
        if looks_like_horizon_reply(q) or has_explicit_horizon(q):
            return GateDecision(
                route=GateRoute.RESEARCH,
                complexity=ComplexityLevel.STANDARD,
                reason="clarification reply supplies horizon",
            )
        if _contains_gold_keyword(q) or any(
            k in ql for k in ("fed", "yield", "inflation", "cpi", "dxy", "macro")
        ):
            return GateDecision(
                route=GateRoute.RESEARCH,
                complexity=ComplexityLevel.STANDARD,
                reason="clarification follow-up continues research",
            )
        # Short non-gold reply while clarifying — still continue research with merge
        if len(q.split()) <= 12:
            return GateDecision(
                route=GateRoute.RESEARCH,
                complexity=ComplexityLevel.STANDARD,
                reason="short clarification reply",
            )

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

    # Clarification: analysis / outlook / trade without an explicit timeframe
    if _needs_horizon_clarification(q, ql):
        if trade_mode and any(k in ql for k in TRADE_KEYWORDS):
            return GateDecision(
                GateRoute.RESEARCH,
                ComplexityLevel.STANDARD,
                "trade mode supplies intraday default",
            )
        if "trade" in ql or "setup" in ql:
            if trade_mode:
                return GateDecision(GateRoute.RESEARCH, ComplexityLevel.STANDARD, "trade_mode on")
            return GateDecision(
                GateRoute.CLARIFY,
                ComplexityLevel.FAST,
                "trade setup needs timeframe",
                clarification_question=TRADE_CLARIFY_QUESTION,
            )
        return GateDecision(
            GateRoute.CLARIFY,
            ComplexityLevel.FAST,
            "analysis needs horizon",
            clarification_question=HORIZON_CLARIFY_QUESTION,
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
