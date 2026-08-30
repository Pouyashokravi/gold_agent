from app.schemas.common import Direction
from app.schemas.technical import TradeSetup
from app.tools import technical, twelve_data


async def build_trade_setup(direction: Direction = "NEUTRAL", query: str = "") -> TradeSetup | None:
    quote = await twelve_data.get_xau_quote()
    ts = await twelve_data.get_xau_time_series("1h", 50)
    values = ts.get("values") or []

    try:
        price = float(quote.get("close") or quote.get("price") or values[0].get("close", 0))
    except (TypeError, ValueError, IndexError):
        return None

    if price <= 0:
        return None

    sr = technical.calculate_support_resistance(values, 20)
    vol = technical.calculate_volatility(values, 20)
    supports = sr.get("support_levels") or []
    resistances = sr.get("resistance_levels") or []

    vol_pct = (vol.get("volatility_pct") or 0.3) / 100
    buffer = max(price * vol_pct * 2, price * 0.002)

    q = query.lower()
    want_long = "sell" not in q and "short" not in q
    want_short = "buy" not in q and "long" not in q
    if "sell" in q or "short" in q:
        want_short = True
        want_long = False
    elif "buy" in q or "long" in q:
        want_long = True
        want_short = False
    elif direction == "BEARISH":
        want_short = True
        want_long = False
    elif direction == "BULLISH":
        want_long = True
        want_short = False

    support = supports[0] if supports else round(price - buffer * 3, 2)
    resistance = resistances[-1] if resistances else round(price + buffer * 3, 2)

    if want_short and not want_long:
        entry_hi = round(price, 2)
        entry_lo = round(max(support, price - buffer), 2)
        sl = round(max(resistance, price + buffer), 2)
        tp1 = round(price - buffer * 2, 2)
        tp2 = round(max(support, price - buffer * 4), 2)
        rr = abs(entry_lo - tp1) / max(abs(sl - entry_lo), 0.01)
        return TradeSetup(
            bias="SHORT",
            entry_zone=[entry_lo, entry_hi],
            stop_loss=sl,
            take_profit=[tp1, tp2],
            risk_reward=round(rr, 2),
            invalidation=f"Close above {sl} invalidates bearish setup",
            confidence=0.62,
        )

    if want_long:
        entry_lo = round(min(resistance, price - buffer) if price > support else price - buffer, 2)
        entry_hi = round(price, 2)
        sl = round(min(support, price - buffer * 2), 2)
        tp1 = round(price + buffer * 2, 2)
        tp2 = round(resistance if resistance > price else price + buffer * 4, 2)
        rr = abs(tp1 - entry_hi) / max(abs(entry_hi - sl), 0.01)
        return TradeSetup(
            bias="LONG",
            entry_zone=[entry_lo, entry_hi],
            stop_loss=sl,
            take_profit=[tp1, tp2],
            risk_reward=round(rr, 2),
            invalidation=f"Close below {sl} invalidates bullish setup",
            confidence=0.62,
        )

    return TradeSetup(
        bias="NO_TRADE",
        entry_zone=[round(price - buffer, 2), round(price + buffer, 2)],
        stop_loss=None,
        take_profit=[],
        risk_reward=None,
        invalidation="No clear directional edge — wait for breakout",
        confidence=0.4,
    )
