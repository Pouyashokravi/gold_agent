"""Freshness-aware short-term working memory (not conversation history)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.config import settings
from app.db.sqlite import get_connection
from app.schemas.common import Freshness
from app.schemas.manager import EvidenceCategory, EvidenceItem
from app.tools.cache import cache

logger = logging.getLogger(__name__)

MemoryKind = str

KIND_TTL: dict[str, int] = {}


def _ttl_map() -> dict[str, int]:
    return {
        "quote": settings.stm_quote_ttl,
        "ohlc_intraday": settings.stm_ohlc_intraday_ttl,
        "ohlc_daily": settings.stm_ohlc_daily_ttl,
        "indicator": settings.stm_indicator_ttl,
        "fred": settings.stm_fred_ttl,
        "macro_snapshot": settings.stm_fred_ttl,
        "news": settings.stm_news_ttl,
        "economic_release": settings.stm_economic_release_ttl,
        "specialist_news": settings.stm_specialist_ttl,
        "specialist_fundamental": settings.stm_specialist_ttl,
        "specialist_technical": settings.stm_specialist_ttl,
        "specialist_technical_trade": settings.stm_trade_specialist_ttl,
        "thesis": settings.stm_thesis_ttl,
        "synthesis": settings.stm_thesis_ttl,
    }


def ttl_for(kind: MemoryKind, trade_mode: bool = False) -> int:
    if trade_mode and kind.startswith("specialist_technical"):
        return settings.stm_trade_specialist_ttl
    return _ttl_map().get(kind, settings.stm_specialist_ttl)


def _mem_key(scope: str, key: str) -> str:
    return f"stm:{scope}:{key}"


def classify_age(age_seconds: float, ttl: int) -> Freshness:
    if age_seconds <= ttl * 0.5:
        return "FRESH"
    if age_seconds <= ttl:
        return "ACCEPTABLE"
    return "STALE"


async def put(
    scope: str,
    key: str,
    value: Any,
    kind: MemoryKind,
    trade_mode: bool = False,
) -> None:
    ttl = ttl_for(kind, trade_mode)
    payload = {
        "value": value,
        "kind": kind,
        "stored_at": time.time(),
        "ttl": ttl,
    }
    cache_key = _mem_key(scope, key)
    await cache.set(cache_key, payload, ttl)
    expires_at = time.time() + ttl
    try:
        async with get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO api_cache (cache_key, value_json, expires_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    value_json = excluded.value_json,
                    expires_at = excluded.expires_at
                """,
                (cache_key, json.dumps(payload, default=str), expires_at),
            )
            await conn.commit()
    except Exception as exc:
        logger.warning("STM sqlite put failed: %s", exc)


async def get_fresh(
    scope: str,
    key: str,
    *,
    max_age: float | None = None,
    accept_acceptable: bool = True,
) -> tuple[Any | None, Freshness | None, dict | None]:
    """Return (value, freshness, meta) if still usable, else (None, STALE|None, meta)."""
    cache_key = _mem_key(scope, key)
    payload = await cache.get(cache_key)
    if payload is None:
        try:
            async with get_connection() as conn:
                cursor = await conn.execute(
                    "SELECT value_json, expires_at FROM api_cache WHERE cache_key = ?",
                    (cache_key,),
                )
                row = await cursor.fetchone()
            if row and row["expires_at"] > time.time():
                payload = json.loads(row["value_json"])
                remaining = int(row["expires_at"] - time.time())
                await cache.set(cache_key, payload, max(1, remaining))
            elif row:
                return None, "STALE", None
        except Exception as exc:
            logger.warning("STM sqlite get failed: %s", exc)
            return None, None, None

    if not payload:
        return None, None, None

    stored_at = float(payload.get("stored_at", 0))
    ttl = int(payload.get("ttl", 60))
    age = time.time() - stored_at
    if max_age is not None:
        ttl = min(ttl, int(max_age))
    freshness = classify_age(age, ttl)
    if freshness == "STALE":
        return None, "STALE", payload
    if freshness == "ACCEPTABLE" and not accept_acceptable:
        return None, "ACCEPTABLE", payload
    return payload.get("value"), freshness, payload


async def get_thesis(conversation_id: str) -> dict | None:
    value, freshness, _ = await get_fresh(conversation_id, "last_thesis", accept_acceptable=True)
    if value is None or freshness == "STALE":
        return None
    return value if isinstance(value, dict) else None


async def put_thesis(conversation_id: str, thesis: dict) -> None:
    await put(conversation_id, "last_thesis", thesis, "thesis")


async def summary_for_prompt(conversation_id: str) -> dict[str, Any]:
    """Compact STM summary for the Gold Manager (no huge blobs)."""
    hits: list[dict[str, Any]] = []
    keys = [
        ("quote", "quote"),
        ("macro_snapshot", "macro_snapshot"),
        ("specialist_news", "news"),
        ("specialist_fundamental", "fundamental"),
        ("specialist_technical", "technical"),
        ("last_thesis", "thesis"),
    ]
    for key, label in keys:
        value, freshness, meta = await get_fresh(conversation_id, key, accept_acceptable=True)
        if value is None:
            # also check global market scope for quote/macro
            if key in {"quote", "macro_snapshot"}:
                value, freshness, meta = await get_fresh("global", key, accept_acceptable=True)
        if value is None or freshness is None:
            continue
        age = None
        if meta:
            age = round(time.time() - float(meta.get("stored_at", time.time())), 1)
        snippet = value
        if isinstance(value, dict):
            snippet = {
                k: value.get(k)
                for k in (
                    "direction",
                    "confidence",
                    "overall_direction",
                    "close",
                    "drivers",
                    "key_drivers",
                    "key_risks",
                    "bias",
                )
                if k in value
            } or {"keys": list(value.keys())[:8]}
        hits.append({"key": label, "freshness": freshness, "age_seconds": age, "snippet": snippet})
    return {"hits": hits}


def to_evidence_item(
    evidence_id: str,
    category: EvidenceCategory,
    source: str,
    value: Any,
    freshness: Freshness = "FRESH",
    claim: str = "",
) -> EvidenceItem:
    data = value if isinstance(value, dict) else {"value": value}
    return EvidenceItem(
        evidence_id=evidence_id,
        category=category,
        source=source,
        claim=claim or source,
        data=data,
        freshness=freshness,
        timestamp=None,
    )
