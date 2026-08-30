from app.schemas.common import Horizon, Intent, ResearchDepth
from app.schemas.planner import GoldPlannerOutput
from app.schemas.query import QueryUnderstandingOutput

NEWS_INTENTS = {
    Intent.NEWS_ANALYSIS,
    Intent.EVENT_IMPACT,
    Intent.MARKET_MOVE_EXPLANATION,
}

NEWS_KEYWORDS = (
    "news", "headline", "headlines", "today", "breaking",
    "اخبار", "خبر", "امروز", "مهم", "رویداد",
)

EVENT_IMPACT_KEYWORDS = (
    "rate cut", "rate hike", "fed ", "federal reserve", "fomc", "central bank",
    "unexpected", "surprise", "basis point", "bps", "policy shock", "monetary policy",
    "cpi", "nfp", "nonfarm", "inflation report", "gdp", "dot plot", "powell",
    "how would", "what if", "impact", "affect", "scenario", "hypothetical",
)

FUNDAMENTAL_KEYWORDS = (
    "rate cut", "rate hike", "fed ", "federal reserve", "fomc", "macro",
    "fundamental", "real yield", "real yields", "us dollar", "dxy", "inflation",
    "yields", "treasury", "monetary",
)

HORIZON_PHRASES = (
    "short-term", "short term", "long-term", "long term",
    "medium-term", "medium term", "few days", "few-day",
)

INTRADAY_KEYWORDS = (
    "today", "now", "right now", "current", "currently",
    "امروز", "الان", "همین الان", "فعلی",
)

FEW_DAYS_KEYWORDS = (
    "this week", "weekly", "هفته", "چند روز",
)

TRADE_KEYWORDS = (
    "setup", "set up", "entry", "enter", "buy", "sell", "long", "short",
    "stop loss", "take profit", "position", "trade", "scalp",
    "ورود", "خرید", "فروش", "پوزیشن", "استاپ", "تارگت",
)

CASUAL_GREETINGS = (
    "hello", "hi", "hey", "howdy", "good morning", "good afternoon", "good evening",
    "greetings", "what's up", "whats up", "sup", "yo",
    "سلام", "درود", "صبح بخیر", "عصر بخیر", "شب بخیر",
)

CASUAL_THANKS = (
    "thanks", "thank you", "thx", "ty", "cheers",
    "متشکر", "ممنون", "مرسی", "سپاس",
)

CASUAL_META = (
    "who are you", "what are you", "what can you do", "what do you do",
    "introduce yourself", "help me", "help",
    "تو کی هستی", "کی هستی", "چیکار میکنی", "چه کاری", "معرفی",
)

CASUAL_ACK = ("ok", "okay", "k", "got it", "cool", "nice", "بله", "نه", "باشه")

GOLD_KEYWORDS = (
    "gold", "xau", "usd", "price", "trade", "buy", "sell", "fed", "rate",
    "technical", "fundamental", "news", "outlook", "analysis", "chart",
    "inflation", "cpi", "yield", "dxy", "macro", "setup", "entry",
    "طلا", "قیمت", "تحلیل", "خرید", "فروش", "اخبار", "نرخ",
)


def _normalize_query_for_keywords(query: str) -> str:
    q = query.lower()
    for phrase in HORIZON_PHRASES:
        q = q.replace(phrase, " ")
    return q


def _normalize_casual(query: str) -> str:
    q = query.strip().lower()
    for ch in "?!.,؛!":
        q = q.replace(ch, "")
    return q.strip()


def _contains_gold_keyword(query: str) -> bool:
    q = query.lower()
    return any(k in q for k in GOLD_KEYWORDS)


def is_casual_query(query: str) -> bool:
    """Return True for greetings, thanks, and meta chat — not research requests."""
    q = _normalize_casual(query)
    if not q:
        return False
    if _contains_gold_keyword(query):
        return False

    all_exact = CASUAL_GREETINGS + CASUAL_THANKS + CASUAL_ACK
    if q in all_exact:
        return True

    for greeting in CASUAL_GREETINGS:
        if q == greeting or q.startswith(greeting + " "):
            rest = q[len(greeting):].strip()
            if not rest or rest in ("there", "everyone", "friend", "gold agent", "agent"):
                return True

    raw_lower = query.lower()
    if any(m in raw_lower for m in CASUAL_META):
        return True

    words = q.split()
    if len(words) <= 2:
        casual_vocab: set[str] = set()
        for phrase in CASUAL_GREETINGS + CASUAL_THANKS + CASUAL_ACK:
            casual_vocab.update(phrase.split())
        if words and all(w in casual_vocab for w in words):
            return True

    return False


def _query_intents(profile: QueryUnderstandingOutput) -> set[Intent]:
    return {i if isinstance(i, Intent) else Intent(i) for i in profile.intents}


def _is_event_impact_query(query: str, intents: set[Intent]) -> bool:
    q = query.lower()
    if intents & {Intent.EVENT_IMPACT, Intent.MARKET_MOVE_EXPLANATION, Intent.NEWS_ANALYSIS}:
        return True
    return any(k in q for k in EVENT_IMPACT_KEYWORDS)


def _needs_fundamental(query: str, intents: set[Intent]) -> bool:
    q = query.lower()
    if intents & {Intent.FUNDAMENTAL_ANALYSIS, Intent.MARKET_OUTLOOK}:
        return True
    return any(k in q for k in FUNDAMENTAL_KEYWORDS)


def _is_trade_query(query: str, intents: set[Intent]) -> bool:
    if Intent.TRADE_ANALYSIS in intents:
        return True
    q = _normalize_query_for_keywords(query)
    return any(k in q for k in TRADE_KEYWORDS)


def _mentions_multiple_horizons(query: str) -> bool:
    q = query.lower()
    markers = (
        "intraday", "short-term", "short term", "medium-term", "medium term",
        "long-term", "long term", "few days", "few_days", "short_term", "medium_term",
    )
    return sum(1 for m in markers if m in q) >= 2


def apply_intent_overrides(profile: QueryUnderstandingOutput, query: str) -> QueryUnderstandingOutput:
    intents = list(profile.intents)
    intent_set = _query_intents(profile)
    q = query.lower()

    if _is_event_impact_query(q, intent_set):
        for intent in (Intent.EVENT_IMPACT, Intent.FUNDAMENTAL_ANALYSIS, Intent.MARKET_MOVE_EXPLANATION):
            if intent not in intent_set:
                intents.append(intent)
                intent_set.add(intent)

    if _needs_fundamental(q, intent_set) and Intent.FUNDAMENTAL_ANALYSIS not in intent_set:
        intents.append(Intent.FUNDAMENTAL_ANALYSIS)

    return profile.model_copy(update={"intents": intents}) if intents != list(profile.intents) else profile


def apply_horizon_overrides(profile: QueryUnderstandingOutput, query: str) -> QueryUnderstandingOutput:
    q = query.lower()
    intents = _query_intents(profile)

    if _mentions_multiple_horizons(query) and _is_event_impact_query(query, intents):
        if profile.horizon in (Horizon.INTRADAY, Horizon.FEW_DAYS):
            return profile.model_copy(update={"horizon": Horizon.MEDIUM_TERM})

    if _is_trade_query(query, intents) and not _is_event_impact_query(query, intents):
        if not _mentions_multiple_horizons(query):
            return profile.model_copy(update={"horizon": Horizon.INTRADAY})

    if any(k in q for k in INTRADAY_KEYWORDS) and not _mentions_multiple_horizons(query):
        return profile.model_copy(update={"horizon": Horizon.INTRADAY})

    if any(k in q for k in FEW_DAYS_KEYWORDS):
        return profile.model_copy(update={"horizon": Horizon.FEW_DAYS})

    long_markers = ("year", "years", "month outlook", "long term", "structural", "decade", "سال", "بلندمدت")
    is_news_query = bool(intents & NEWS_INTENTS) or any(k in q for k in NEWS_KEYWORDS)
    if (
        is_news_query
        and not any(m in q for m in long_markers)
        and not _mentions_multiple_horizons(query)
        and not _is_event_impact_query(query, intents)
    ):
        if profile.horizon in (Horizon.MEDIUM_TERM, Horizon.LONG_TERM, Horizon.AGES):
            return profile.model_copy(update={"horizon": Horizon.FEW_DAYS})

    if Intent.PRICE_QUERY in intents and profile.horizon in (Horizon.LONG_TERM, Horizon.AGES):
        return profile.model_copy(update={"horizon": Horizon.INTRADAY})

    return profile


def apply_trade_mode_overrides(
    profile: QueryUnderstandingOutput,
    plan: GoldPlannerOutput,
    query: str,
    trade_mode: bool,
) -> tuple[QueryUnderstandingOutput, GoldPlannerOutput]:
    if not trade_mode:
        return profile, plan

    intents = list(profile.intents)
    if Intent.TRADE_ANALYSIS not in intents:
        intents.append(Intent.TRADE_ANALYSIS)

    profile = profile.model_copy(update={
        "horizon": Horizon.INTRADAY,
        "intents": intents,
        "requested_depth": ResearchDepth.STANDARD if profile.requested_depth == ResearchDepth.LIGHT else profile.requested_depth,
    })

    plan.technical_agent.enabled = True
    plan.technical_agent.depth = "DEEP"
    plan.technical_agent.task = "Produce XAU/USD trade setup with entry zone, stop loss, take profit, and bias (LONG/SHORT/NO_TRADE)."
    plan.technical_agent.focus = ["entry", "stop loss", "take profit", "support", "resistance", "momentum"]

    if not plan.news_agent.enabled or plan.news_agent.depth == "OFF":
        plan.news_agent.enabled = False
        plan.news_agent.depth = "OFF"
    else:
        plan.news_agent.depth = "LIGHT"

    if not plan.fundamental_agent.enabled or plan.fundamental_agent.depth == "OFF":
        plan.fundamental_agent.enabled = False
        plan.fundamental_agent.depth = "OFF"
    else:
        plan.fundamental_agent.depth = "LIGHT"

    return profile, plan


def _is_price_only_query(query: str, intents: set[Intent]) -> bool:
    if Intent.PRICE_QUERY not in intents:
        return False
    non_price = intents - {Intent.PRICE_QUERY, Intent.TECHNICAL_ANALYSIS}
    if non_price:
        return False
    q = query.lower().strip()
    price_patterns = (
        "price", "quote", "xau/usd", "xauusd", "gold price",
        "قیمت", "چنده", "چقدره",
    )
    return any(p in q for p in price_patterns) and len(q.split()) <= 8


def apply_routing_overrides(
    plan: GoldPlannerOutput,
    profile: QueryUnderstandingOutput,
    query: str,
) -> GoldPlannerOutput:
    intents = _query_intents(profile)
    q = query.lower()
    depth = profile.requested_depth.value if isinstance(profile.requested_depth, ResearchDepth) else profile.requested_depth
    agent_depth = depth if depth in {"STANDARD", "DEEP"} else "STANDARD"

    event_query = _is_event_impact_query(q, intents)
    fundamental_query = _needs_fundamental(q, intents)
    trade_query = _is_trade_query(query, intents) and not event_query
    needs_news = bool(intents & NEWS_INTENTS) or any(k in q for k in NEWS_KEYWORDS) or event_query
    price_only = _is_price_only_query(query, intents)

    if price_only:
        plan.technical_agent.enabled = True
        if plan.technical_agent.depth == "OFF":
            plan.technical_agent.depth = "LIGHT"
        plan.news_agent.enabled = False
        plan.news_agent.depth = "OFF"
        plan.fundamental_agent.enabled = False
        plan.fundamental_agent.depth = "OFF"
        return plan

    if event_query:
        plan.news_agent.enabled = True
        plan.news_agent.depth = agent_depth
        plan.news_agent.task = (
            "Analyze market reaction, headlines, and event context for the Fed/macro scenario affecting XAU/USD."
        )
        plan.news_agent.focus = ["Federal Reserve", "rate decision", "US dollar", "US yields", "gold market"]

        plan.fundamental_agent.enabled = True
        plan.fundamental_agent.depth = agent_depth
        plan.fundamental_agent.task = (
            "Analyze macro transmission of the Fed rate scenario to gold drivers (real yields, USD, risk sentiment)."
        )
        plan.fundamental_agent.focus = ["real yields", "US dollar", "Fed policy", "inflation expectations"]

        plan.technical_agent.enabled = True
        if plan.technical_agent.depth == "OFF":
            plan.technical_agent.depth = "STANDARD"
        plan.technical_agent.task = plan.technical_agent.task or (
            "Assess XAU/USD technical levels and momentum across requested horizons."
        )
        return plan

    if trade_query:
        plan.technical_agent.enabled = True
        plan.technical_agent.depth = "DEEP"
        plan.technical_agent.task = plan.technical_agent.task or "XAU/USD trade setup with entry, SL, TP."
        plan.news_agent.enabled = False
        plan.news_agent.depth = "OFF"
        plan.fundamental_agent.enabled = False
        plan.fundamental_agent.depth = "OFF"
        return plan

    if needs_news and not price_only:
        plan.news_agent.enabled = True
        if plan.news_agent.depth in ("OFF",):
            plan.news_agent.depth = agent_depth
        if not plan.news_agent.task:
            plan.news_agent.task = "Analyze today's gold-relevant news and market-moving events for XAU/USD."
        if not plan.news_agent.focus:
            plan.news_agent.focus = ["Federal Reserve", "US dollar", "US yields", "geopolitical risk", "gold market"]

    if fundamental_query:
        plan.fundamental_agent.enabled = True
        if plan.fundamental_agent.depth == "OFF":
            plan.fundamental_agent.depth = agent_depth

    if Intent.TECHNICAL_ANALYSIS in intents or Intent.PRICE_QUERY in intents or _mentions_multiple_horizons(query):
        if plan.technical_agent.depth == "OFF":
            plan.technical_agent.enabled = True
            plan.technical_agent.depth = "STANDARD"

    return plan


def validate_plan(plan: GoldPlannerOutput) -> list[str]:
    warnings: list[str] = []
    enabled = [
        plan.news_agent.enabled,
        plan.fundamental_agent.enabled,
        plan.technical_agent.enabled,
    ]
    if not any(enabled):
        warnings.append("No specialist agents enabled")
    return warnings


TAVILY_LIMITS = {"LIGHT": 1, "STANDARD": 2, "DEEP": 2}
