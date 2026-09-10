"""Conversation Gate runner, validation, cumulative clarification, and emergency fallback."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from agents import Runner

from app.agents.conversation_gate import conversation_gate_agent
from app.config import settings
from app.schemas.common import Horizon, Intent
from app.schemas.conversation_gate import (
    ANALYSIS_INTENTS,
    ANALYSIS_TYPE_TO_INTENT,
    CLARIFY_CANONICAL_FIELDS,
    CLARIFY_FIELD_ANALYSIS_SCOPES,
    CLARIFY_FIELD_ANALYSIS_TYPE,
    CLARIFY_FIELD_HORIZON,
    CLARIFY_FIELD_PURPOSE,
    FAST_KIND_ALLOWLIST,
    HORIZON_REQUIRED_INTENTS,
    TIMING_FLEXIBLE_INTENTS,
    AnalysisPurpose,
    AnalysisScope,
    ContextRelationship,
    ConversationGateLLMOutput,
    ConversationGateOutput,
    NewlyResolvedFields,
    coerce_analysis_scopes,
    normalize_legacy_analysis_type,
    normalize_resolved_fields,
    scope_values,
    scopes_from_intent,
)
from app.schemas.manager import ComplexityLevel, GateRoute
from app.services.gate import GateDecision, classify_gate, parse_horizon_from_text
from app.services.session import build_compact_repair_context

logger = logging.getLogger(__name__)

_GREETING_RE = re.compile(
    r"^\s*(hi|hello|hey|hiya|howdy|good\s+(morning|afternoon|evening)|yo|sup)\s*[!.?]?\s*$",
    re.I,
)


class GateValidationError(ValueError):
    pass


def _enum_val(v: Any) -> Any:
    return v.value if hasattr(v, "value") else v


def _llm_to_output(raw: ConversationGateLLMOutput | ConversationGateOutput | dict) -> ConversationGateOutput:
    if isinstance(raw, ConversationGateOutput):
        return raw
    if isinstance(raw, ConversationGateLLMOutput):
        return ConversationGateOutput.model_validate(raw.model_dump())
    data = dict(raw)
    data.pop("is_follow_up", None)
    return ConversationGateOutput.model_validate(data)


def derive_is_follow_up(relationship: ContextRelationship) -> bool:
    return relationship in {
        ContextRelationship.FOLLOW_UP,
        ContextRelationship.CLARIFICATION_ANSWER,
    }


def _normalize_missing_name(f: str) -> str:
    if f in {"intent", "analysis_type", "type", "analysis_scopes", "scopes", "focus"}:
        return CLARIFY_FIELD_ANALYSIS_SCOPES
    if f in {"user_goal", "goal"}:
        return CLARIFY_FIELD_PURPOSE
    return f


def _parse_intent(value: Any) -> Intent | None:
    if value is None or value == "":
        return None
    if isinstance(value, Intent):
        return value
    try:
        return Intent(str(_enum_val(value)))
    except ValueError:
        return ANALYSIS_TYPE_TO_INTENT.get(str(value).upper())


def _parse_purpose(value: Any) -> AnalysisPurpose | None:
    if value is None or value == "":
        return None
    if isinstance(value, AnalysisPurpose):
        return value
    try:
        return AnalysisPurpose(str(_enum_val(value)))
    except ValueError:
        return None


def _parse_horizon(value: Any) -> Horizon | None:
    if value is None or value == "":
        return None
    if isinstance(value, Horizon):
        return value
    try:
        return Horizon(str(_enum_val(value)))
    except ValueError:
        return None


def required_clarify_fields(
    intent: Intent | None,
    *,
    scopes: list[AnalysisScope],
    horizon: Horizon | None,
    timing_explicit: bool = False,
    pending_missing: list[str] | None = None,
) -> list[str]:
    """Intent-aware required fields — not a universal scopes+horizon rule."""
    if intent is None or intent == Intent.PRICE_QUERY:
        return []

    required: list[str] = []
    if intent in ANALYSIS_INTENTS and not scopes:
        required.append(CLARIFY_FIELD_ANALYSIS_SCOPES)

    needs_horizon = False
    if intent in HORIZON_REQUIRED_INTENTS:
        needs_horizon = horizon is None
    elif intent in TIMING_FLEXIBLE_INTENTS:
        needs_horizon = horizon is None and not timing_explicit
        if pending_missing is not None and CLARIFY_FIELD_HORIZON not in pending_missing:
            needs_horizon = False
    elif intent in ANALYSIS_INTENTS:
        needs_horizon = horizon is None

    if needs_horizon:
        required.append(CLARIFY_FIELD_HORIZON)

    if pending_missing and CLARIFY_FIELD_PURPOSE in pending_missing:
        required.append(CLARIFY_FIELD_PURPOSE)

    out: list[str] = []
    for f in required:
        if f not in out:
            out.append(f)
    return out


def _layer_from_top_level(decision: ConversationGateOutput) -> dict[str, Any]:
    layer: dict[str, Any] = {}
    if decision.intent is not None:
        layer["intent"] = decision.intent
    scopes = coerce_analysis_scopes(decision.analysis_scopes)
    if scopes:
        layer[CLARIFY_FIELD_ANALYSIS_SCOPES] = scopes
    if decision.purpose is not None:
        layer[CLARIFY_FIELD_PURPOSE] = decision.purpose
    if decision.horizon is not None:
        layer[CLARIFY_FIELD_HORIZON] = decision.horizon
    return layer


def _layer_from_newly_resolved(delta: NewlyResolvedFields | None) -> dict[str, Any]:
    if delta is None:
        return {}
    layer: dict[str, Any] = {}
    if delta.intent is not None:
        layer["intent"] = delta.intent
    if delta.analysis_scopes is not None and len(delta.analysis_scopes) > 0:
        layer[CLARIFY_FIELD_ANALYSIS_SCOPES] = list(delta.analysis_scopes)
    if delta.purpose is not None:
        layer[CLARIFY_FIELD_PURPOSE] = delta.purpose
    if delta.horizon is not None:
        layer[CLARIFY_FIELD_HORIZON] = delta.horizon
    return layer


def _layer_from_pending(pending: dict | None) -> dict[str, Any]:
    if not pending:
        return {}
    normalized = normalize_resolved_fields(pending.get("resolved_fields") or {})
    layer: dict[str, Any] = {}
    if "intent" in normalized:
        intent = _parse_intent(normalized["intent"])
        if intent is not None:
            layer["intent"] = intent
    scopes = coerce_analysis_scopes(normalized.get(CLARIFY_FIELD_ANALYSIS_SCOPES))
    if scopes:
        layer[CLARIFY_FIELD_ANALYSIS_SCOPES] = scopes
    purpose = _parse_purpose(normalized.get(CLARIFY_FIELD_PURPOSE))
    if purpose is not None:
        layer[CLARIFY_FIELD_PURPOSE] = purpose
    horizon = _parse_horizon(normalized.get(CLARIFY_FIELD_HORIZON))
    if horizon is not None:
        layer[CLARIFY_FIELD_HORIZON] = horizon
    if normalized.get("timing_explicit"):
        layer["timing_explicit"] = True
    if CLARIFY_FIELD_PURPOSE not in layer:
        purpose = _parse_purpose(pending.get("purpose"))
        if purpose is not None:
            layer[CLARIFY_FIELD_PURPOSE] = purpose
    return layer


def _merge_layers(*layers: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for layer in layers:
        for k, v in layer.items():
            if v is None or v == "" or v == []:
                continue
            merged[k] = v
    return merged


def _detect_delta_conflict(top: dict[str, Any], delta: dict[str, Any]) -> bool:
    for key in ("intent", CLARIFY_FIELD_ANALYSIS_SCOPES, CLARIFY_FIELD_HORIZON, CLARIFY_FIELD_PURPOSE):
        if key not in top or key not in delta:
            continue
        a, b = top[key], delta[key]
        if key == CLARIFY_FIELD_ANALYSIS_SCOPES:
            if scope_values(coerce_analysis_scopes(a)) != scope_values(coerce_analysis_scopes(b)):
                return True
        elif _enum_val(a) != _enum_val(b):
            return True
    return False


def _cumulative_to_resolved_fields(cumulative: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "intent" in cumulative:
        out["intent"] = _enum_val(cumulative["intent"])
    scopes = coerce_analysis_scopes(cumulative.get(CLARIFY_FIELD_ANALYSIS_SCOPES))
    if scopes:
        out[CLARIFY_FIELD_ANALYSIS_SCOPES] = scope_values(scopes)
    if CLARIFY_FIELD_PURPOSE in cumulative:
        out[CLARIFY_FIELD_PURPOSE] = _enum_val(cumulative[CLARIFY_FIELD_PURPOSE])
    if CLARIFY_FIELD_HORIZON in cumulative:
        out[CLARIFY_FIELD_HORIZON] = _enum_val(cumulative[CLARIFY_FIELD_HORIZON])
    if cumulative.get("timing_explicit"):
        out["timing_explicit"] = True
    return out


def _rebuild_top_level_from_cumulative(
    decision: ConversationGateOutput,
    cumulative: dict[str, Any],
    *,
    missing: list[str],
    delta_conflict: bool,
) -> ConversationGateOutput:
    intent = _parse_intent(cumulative.get("intent"))
    scopes = coerce_analysis_scopes(cumulative.get(CLARIFY_FIELD_ANALYSIS_SCOPES))
    purpose = _parse_purpose(cumulative.get(CLARIFY_FIELD_PURPOSE))
    horizon = _parse_horizon(cumulative.get(CLARIFY_FIELD_HORIZON))
    resolved = _cumulative_to_resolved_fields(cumulative)

    # Soft-fill intent from a singleton scope when pending/current left intent null
    if intent is None and len(scopes) == 1:
        intent = {
            AnalysisScope.TECHNICAL: Intent.TECHNICAL_ANALYSIS,
            AnalysisScope.FUNDAMENTAL: Intent.FUNDAMENTAL_ANALYSIS,
            AnalysisScope.NEWS: Intent.NEWS_ANALYSIS,
        }.get(scopes[0])
        if intent is not None:
            resolved["intent"] = intent.value

    action = decision.action
    if (
        action in {GateRoute.STANDARD, GateRoute.RESEARCH}
        and not scopes
        and intent in ANALYSIS_INTENTS
    ):
        scopes = scopes_from_intent(intent)
        if scopes:
            resolved[CLARIFY_FIELD_ANALYSIS_SCOPES] = scope_values(scopes)

    updates: dict[str, Any] = {
        "intent": intent,
        "analysis_scopes": scopes,
        "purpose": purpose,
        "horizon": horizon,
        "resolved_fields": resolved,
        "missing_fields": missing,
        "delta_conflict": delta_conflict,
    }
    reason = decision.reason or ""
    if delta_conflict and "delta_conflict" not in reason:
        updates["reason"] = (reason + " | delta_conflict:newly_resolved_fields_wins").strip(" |")
    return decision.model_copy(update=updates)


def _filter_missing(
    candidates: list[str],
    *,
    scopes: list[AnalysisScope],
    horizon: Horizon | None,
    purpose: Any,
) -> list[str]:
    missing: list[str] = []
    for f in candidates:
        if f == CLARIFY_FIELD_ANALYSIS_SCOPES and scopes:
            continue
        if f == CLARIFY_FIELD_HORIZON and horizon is not None:
            continue
        if f == CLARIFY_FIELD_PURPOSE and purpose is not None:
            continue
        if f not in missing:
            missing.append(f)
    return missing


def merge_clarification_state(
    pending: dict | None,
    decision: ConversationGateOutput,
    *,
    allow_pending_merge: bool,
) -> ConversationGateOutput:
    """Merge with clarification-safe precedence; rebuild top-level from cumulative state.

    Normal precedence: pending → top-level → newly_resolved_fields.
    On CLARIFICATION_ANSWER, top-level must not overwrite pending analysis_scopes/intent
    unless newly_resolved_fields explicitly sets them (preserves TECHNICAL vs comprehensive).
    """
    pending_layer = _layer_from_pending(pending) if allow_pending_merge else {}
    top_layer = _layer_from_top_level(decision)
    delta = decision.newly_resolved_fields or NewlyResolvedFields()
    delta_layer = _layer_from_newly_resolved(delta)
    delta_conflict = _detect_delta_conflict(top_layer, delta_layer)

    if allow_pending_merge:
        cumulative = dict(pending_layer)
        for k, v in top_layer.items():
            # Preserve pending scopes / intent unless newly_resolved_fields explicitly changes them
            if k == CLARIFY_FIELD_ANALYSIS_SCOPES and k in pending_layer and k not in delta_layer:
                continue
            if k == "intent" and "intent" not in delta_layer:
                if "intent" in pending_layer or CLARIFY_FIELD_ANALYSIS_SCOPES in pending_layer:
                    continue
            if v is None or v == "" or v == []:
                continue
            cumulative[k] = v
        for k, v in delta_layer.items():
            if v is None or v == "" or v == []:
                continue
            cumulative[k] = v
    else:
        cumulative = _merge_layers(top_layer, delta_layer)

    intent = _parse_intent(cumulative.get("intent"))
    scopes = coerce_analysis_scopes(cumulative.get(CLARIFY_FIELD_ANALYSIS_SCOPES))
    horizon = _parse_horizon(cumulative.get(CLARIFY_FIELD_HORIZON))
    purpose = cumulative.get(CLARIFY_FIELD_PURPOSE)
    timing_explicit = bool(cumulative.get("timing_explicit"))

    pending_missing = (
        [_normalize_missing_name(f) for f in ((pending or {}).get("missing_fields") or [])]
        if allow_pending_merge and pending
        else None
    )
    llm_missing = [_normalize_missing_name(f) for f in (decision.missing_fields or [])]

    if allow_pending_merge and pending:
        scope_list: list[str] = []
        for f in pending_missing or []:
            if f not in scope_list:
                scope_list.append(f)
        if not scope_list:
            scope_list = required_clarify_fields(
                intent,
                scopes=scopes,
                horizon=horizon,
                timing_explicit=timing_explicit,
                pending_missing=None,
            )
        needed = required_clarify_fields(
            intent,
            scopes=scopes,
            horizon=horizon,
            timing_explicit=timing_explicit,
            pending_missing=pending_missing,
        )
        for f in needed:
            if f not in scope_list:
                scope_list.append(f)
        missing = _filter_missing(scope_list, scopes=scopes, horizon=horizon, purpose=purpose)
    else:
        candidates: list[str] = []
        for f in llm_missing:
            if f not in candidates:
                candidates.append(f)
        if not candidates and decision.action in {
            GateRoute.CLARIFY,
            GateRoute.STANDARD,
            GateRoute.RESEARCH,
        }:
            candidates = required_clarify_fields(
                intent,
                scopes=scopes,
                horizon=horizon,
                timing_explicit=timing_explicit,
            )
        missing = _filter_missing(candidates, scopes=scopes, horizon=horizon, purpose=purpose)

    rebuilt = _rebuild_top_level_from_cumulative(
        decision, cumulative, missing=missing, delta_conflict=delta_conflict
    )

    if (
        allow_pending_merge
        and pending
        and rebuilt.action == GateRoute.CLARIFY
        and not rebuilt.missing_fields
    ):
        original = (
            pending.get("original_query")
            or pending.get("pending_goal")
            or ""
        )
        scopes_final = list(rebuilt.analysis_scopes or [])
        if not scopes_final and rebuilt.intent in ANALYSIS_INTENTS:
            scopes_final = scopes_from_intent(rebuilt.intent)
        rf = dict(rebuilt.resolved_fields or {})
        if scopes_final:
            rf[CLARIFY_FIELD_ANALYSIS_SCOPES] = scope_values(scopes_final)
        rebuilt = rebuilt.model_copy(
            update={
                "action": GateRoute.STANDARD,
                "complexity": ComplexityLevel.STANDARD,
                "clarification_question": None,
                "analysis_scopes": scopes_final,
                "resolved_fields": rf,
                "normalized_query": rebuilt.normalized_query
                or build_normalized_query(str(original), rf),
                "reason": rebuilt.reason or "All clarification fields resolved; proceeding",
            }
        )

    return rebuilt


def build_normalized_query(original_query: str, resolved: dict[str, Any]) -> str:
    parts = [original_query.strip()] if original_query.strip() else []
    scopes = coerce_analysis_scopes(resolved.get(CLARIFY_FIELD_ANALYSIS_SCOPES))
    if not scopes and resolved.get(CLARIFY_FIELD_ANALYSIS_TYPE):
        scopes = normalize_legacy_analysis_type(resolved.get(CLARIFY_FIELD_ANALYSIS_TYPE))
    if scopes:
        parts.append(f"Focus on {'+'.join(scope_values(scopes))} analysis.")
    if CLARIFY_FIELD_HORIZON in resolved:
        parts.append(f"Time horizon: {resolved[CLARIFY_FIELD_HORIZON]}.")
    if CLARIFY_FIELD_PURPOSE in resolved:
        parts.append(f"Purpose: {resolved[CLARIFY_FIELD_PURPOSE]}.")
    return " ".join(parts).strip() or original_query


def _original_query(pending: dict | None, query: str, context: dict | None) -> str:
    return (
        (pending or {}).get("original_query")
        or (pending or {}).get("pending_goal")
        or (context or {}).get("AUTHORITATIVE_CURRENT_USER_MESSAGE")
        or (context or {}).get("current_user_message")
        or query
    ).strip()


def repair_normalized_query(
    decision: ConversationGateOutput,
    pending: dict | None,
    query: str,
    context: dict | None = None,
    *,
    allow_pending_merge: bool = False,
) -> ConversationGateOutput:
    if decision.action not in {GateRoute.STANDARD, GateRoute.RESEARCH}:
        return decision
    if (decision.normalized_query or "").strip():
        return decision
    if allow_pending_merge and pending:
        original = _original_query(pending, query, context)
    else:
        original = (
            (context or {}).get("AUTHORITATIVE_CURRENT_USER_MESSAGE")
            or (context or {}).get("current_user_message")
            or query
        ).strip()
    if not original:
        return decision
    return decision.model_copy(
        update={
            "normalized_query": build_normalized_query(original, decision.resolved_fields or {}),
        }
    )


def infer_clarification_fragment(query: str) -> dict[str, Any]:
    """Map obvious short clarification replies (emergency fallback only)."""
    ql = (query or "").strip().lower()
    inferred: dict[str, Any] = {}
    if not ql:
        return inferred

    horizon = parse_horizon_from_text(query)
    if horizon:
        inferred[CLARIFY_FIELD_HORIZON] = horizon.value
    elif re.search(r"\b(?:for\s+)?(?:\d+\s*)?(?:year|years|yr)\b|\bone\s+year\b", ql):
        inferred[CLARIFY_FIELD_HORIZON] = Horizon.LONG_TERM.value

    if re.fullmatch(r"technical(?:\s+analysis)?", ql) or ql == "technical":
        inferred[CLARIFY_FIELD_ANALYSIS_SCOPES] = [AnalysisScope.TECHNICAL.value]
    elif "fundamental" in ql:
        inferred[CLARIFY_FIELD_ANALYSIS_SCOPES] = [AnalysisScope.FUNDAMENTAL.value]

    if "investment" in ql or ql.startswith("for investment"):
        inferred[CLARIFY_FIELD_PURPOSE] = AnalysisPurpose.INVESTMENT.value
    elif re.search(r"\btrading\b|\btrade\b", ql):
        inferred[CLARIFY_FIELD_PURPOSE] = AnalysisPurpose.TRADING.value

    return inferred


def looks_like_greeting(query: str) -> bool:
    return bool(_GREETING_RE.match(query or ""))


def _apply_inferred_to_output(
    decision: ConversationGateOutput,
    inferred: dict[str, Any],
) -> ConversationGateOutput:
    delta = decision.newly_resolved_fields or NewlyResolvedFields()
    delta_updates: dict[str, Any] = {}
    top_updates: dict[str, Any] = {}

    if CLARIFY_FIELD_ANALYSIS_SCOPES in inferred:
        scopes = coerce_analysis_scopes(inferred[CLARIFY_FIELD_ANALYSIS_SCOPES])
        delta_updates["analysis_scopes"] = scopes
        top_updates["analysis_scopes"] = scopes
        if scopes == [AnalysisScope.TECHNICAL]:
            delta_updates["intent"] = Intent.TECHNICAL_ANALYSIS
            top_updates["intent"] = Intent.TECHNICAL_ANALYSIS
        elif scopes == [AnalysisScope.FUNDAMENTAL]:
            delta_updates["intent"] = Intent.FUNDAMENTAL_ANALYSIS
            top_updates["intent"] = Intent.FUNDAMENTAL_ANALYSIS
        elif scopes == [AnalysisScope.NEWS]:
            delta_updates["intent"] = Intent.NEWS_ANALYSIS
            top_updates["intent"] = Intent.NEWS_ANALYSIS

    if CLARIFY_FIELD_PURPOSE in inferred:
        purpose = _parse_purpose(inferred[CLARIFY_FIELD_PURPOSE])
        if purpose is not None:
            delta_updates["purpose"] = purpose
            top_updates["purpose"] = purpose

    if CLARIFY_FIELD_HORIZON in inferred:
        hz = _parse_horizon(inferred[CLARIFY_FIELD_HORIZON])
        if hz is not None:
            delta_updates["horizon"] = hz
            top_updates["horizon"] = hz

    if not delta_updates:
        return decision
    top_updates["newly_resolved_fields"] = delta.model_copy(update=delta_updates)
    return decision.model_copy(update=top_updates)


def deterministic_clarify_question(missing_fields: list[str]) -> str:
    missing = [_normalize_missing_name(f) for f in missing_fields]
    missing = [f for f in missing if f in CLARIFY_CANONICAL_FIELDS] or missing
    if missing == [CLARIFY_FIELD_PURPOSE]:
        return "What is the purpose of this analysis?"
    if missing == [CLARIFY_FIELD_HORIZON]:
        return "What time horizon should I use?"
    if missing == [CLARIFY_FIELD_ANALYSIS_SCOPES]:
        return (
            "What focus should I use for this analysis "
            "(for example charts, macro drivers, or recent news)?"
        )
    if set(missing) == {CLARIFY_FIELD_HORIZON, CLARIFY_FIELD_PURPOSE}:
        return "What time horizon and purpose should I use for this analysis?"
    if set(missing) == {CLARIFY_FIELD_ANALYSIS_SCOPES, CLARIFY_FIELD_HORIZON}:
        return "What focus and time horizon should I use for this analysis?"
    if set(missing) == {CLARIFY_FIELD_ANALYSIS_SCOPES, CLARIFY_FIELD_PURPOSE}:
        return "What focus and purpose should I use for this analysis?"
    if set(missing) >= set(CLARIFY_CANONICAL_FIELDS):
        return "What focus, time horizon, and purpose should I use for this analysis?"
    labels = {
        CLARIFY_FIELD_ANALYSIS_SCOPES: "focus",
        CLARIFY_FIELD_HORIZON: "time horizon",
        CLARIFY_FIELD_PURPOSE: "purpose",
    }
    named = [labels.get(f, f) for f in missing]
    if len(named) == 1:
        return f"What {named[0]} should I use?"
    if len(named) == 2:
        return f"What {named[0]} and {named[1]} should I use for this analysis?"
    return "What " + ", ".join(named[:-1]) + f", and {named[-1]} should I use for this analysis?"


_FIELD_ASK_PATTERNS: dict[str, re.Pattern[str]] = {
    CLARIFY_FIELD_ANALYSIS_SCOPES: re.compile(
        r"\b(analysis type|type of analysis|technical|fundamental|focus|kind of analysis|"
        r"what kind of analysis)\b",
        re.I,
    ),
    CLARIFY_FIELD_PURPOSE: re.compile(
        r"\b(purpose|for investment|trading|what(?:'s| is) (?:the )?purpose)\b",
        re.I,
    ),
    CLARIFY_FIELD_HORIZON: re.compile(
        r"\b(time horizon|timeframe|horizon|how long|short[-\s]?term|medium[-\s]?term|long[-\s]?term)\b",
        re.I,
    ),
}


def question_asks_resolved_fields(question: str, resolved: dict[str, Any]) -> bool:
    q = (question or "").strip()
    if not q:
        return False
    for field in resolved:
        key = (
            CLARIFY_FIELD_ANALYSIS_SCOPES
            if field in {CLARIFY_FIELD_ANALYSIS_TYPE, CLARIFY_FIELD_ANALYSIS_SCOPES}
            else field
        )
        pat = _FIELD_ASK_PATTERNS.get(key)
        if pat and pat.search(q):
            return True
    return False


def questions_are_same(a: str | None, b: str | None) -> bool:
    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip().lower())

    na, nb = norm(a or ""), norm(b or "")
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def apply_clarify_question_guard(
    decision: ConversationGateOutput,
    pending: dict | None,
) -> ConversationGateOutput:
    if decision.action != GateRoute.CLARIFY:
        return decision
    missing = list(decision.missing_fields or [])
    if not missing:
        return decision

    question = (decision.clarification_question or "").strip()
    previous_q = (pending or {}).get("previous_clarification_question") or (
        pending or {}
    ).get("clarification")
    resolved = decision.resolved_fields or {}
    prev_resolved = normalize_resolved_fields((pending or {}).get("resolved_fields") or {})
    progress = bool(pending) and (
        bool(set(resolved.keys()) - set(prev_resolved.keys()))
        or len(resolved) > len(prev_resolved)
        or (
            scope_values(coerce_analysis_scopes(resolved.get(CLARIFY_FIELD_ANALYSIS_SCOPES)))
            != scope_values(
                coerce_analysis_scopes(prev_resolved.get(CLARIFY_FIELD_ANALYSIS_SCOPES))
            )
        )
    )

    needs_replace = (
        not question
        or question_asks_resolved_fields(question, resolved)
        or (progress and questions_are_same(question, previous_q))
    )
    if needs_replace:
        return decision.model_copy(
            update={"clarification_question": deterministic_clarify_question(missing)}
        )
    return decision


def apply_clarification_limit(
    decision: ConversationGateOutput,
    pending: dict | None,
    query: str,
) -> ConversationGateOutput:
    del pending, query
    return decision.model_copy(
        update={
            "action": GateRoute.GENERAL_CHAT,
            "complexity": ComplexityLevel.FAST,
            "missing_fields": [],
            "clarification_question": None,
            "normalized_query": None,
            "fast_kind": None,
            "context_relationship": ContextRelationship.INDEPENDENT,
            "is_follow_up": False,
            "reason": "clarification_limit_cancelled",
            "confidence": max(float(decision.confidence), 0.5),
        }
    )


CLARIFICATION_LIMIT_MESSAGE = (
    "I still need the missing analysis details to continue, but we hit the clarification limit. "
    "Please start a new request and include the analysis focus and time horizon "
    "(for example: a short-term macro outlook, or charts over the next few days)."
)


def _analysis_fields_unresolved(decision: ConversationGateOutput) -> list[str]:
    scopes = coerce_analysis_scopes(decision.analysis_scopes) or coerce_analysis_scopes(
        (decision.resolved_fields or {}).get(CLARIFY_FIELD_ANALYSIS_SCOPES)
    )
    horizon = decision.horizon or _parse_horizon(
        (decision.resolved_fields or {}).get(CLARIFY_FIELD_HORIZON)
    )
    timing_explicit = bool((decision.resolved_fields or {}).get("timing_explicit"))
    if decision.intent is None and not scopes:
        # Incomplete analysis package — no goal and no scopes yet
        missing = [CLARIFY_FIELD_ANALYSIS_SCOPES]
        if horizon is None:
            missing.append(CLARIFY_FIELD_HORIZON)
        return missing
    return required_clarify_fields(
        decision.intent,
        scopes=scopes,
        horizon=horizon,
        timing_explicit=timing_explicit,
        pending_missing=None,
    )


def _establishes_analysis_request(decision: ConversationGateOutput) -> bool:
    if decision.context_relationship == ContextRelationship.CLARIFICATION_ANSWER:
        return True
    if decision.intent in ANALYSIS_INTENTS:
        return True
    if decision.analysis_scopes:
        return True
    if decision.missing_fields and (decision.reason or "").strip():
        return True
    return False


def _is_invalid_zero_conf_package(decision: ConversationGateOutput) -> bool:
    if float(decision.confidence) != 0.0:
        return False
    if (decision.reason or "").strip():
        return False
    if decision.action == GateRoute.FAST:
        kind = (decision.fast_kind or "").lower() if decision.fast_kind else ""
        if kind not in FAST_KIND_ALLOWLIST:
            return True
        if kind == "quote" and decision.intent != Intent.PRICE_QUERY:
            return True
        return False
    if decision.action in {GateRoute.STANDARD, GateRoute.RESEARCH}:
        return bool(_analysis_fields_unresolved(decision))
    if decision.action == GateRoute.CLARIFY:
        return not decision.missing_fields or not (decision.clarification_question or "").strip()
    return False


def _pending_missing_names(pending: dict | None) -> list[str]:
    if not pending:
        return []
    names = [_normalize_missing_name(f) for f in (pending.get("missing_fields") or [])]
    if names:
        out: list[str] = []
        for f in names:
            if f not in out:
                out.append(f)
        return out
    rf = normalize_resolved_fields(pending.get("resolved_fields") or {})
    return [
        f
        for f in (CLARIFY_FIELD_ANALYSIS_SCOPES, CLARIFY_FIELD_HORIZON)
        if f not in rf
    ]


def _fills_pending_missing_field(
    decision: ConversationGateOutput,
    pending: dict | None,
) -> bool:
    """True if current-turn delta or top-level newly fills a still-missing pending field."""
    pending_missing = _pending_missing_names(pending)
    if not pending_missing:
        return False
    delta = decision.newly_resolved_fields or NewlyResolvedFields()
    if delta.horizon is not None and CLARIFY_FIELD_HORIZON in pending_missing:
        return True
    if (
        delta.analysis_scopes is not None
        and len(delta.analysis_scopes) > 0
        and CLARIFY_FIELD_ANALYSIS_SCOPES in pending_missing
    ):
        return True
    if delta.purpose is not None and CLARIFY_FIELD_PURPOSE in pending_missing:
        return True
    if delta.intent is not None and CLARIFY_FIELD_ANALYSIS_SCOPES in pending_missing:
        return True
    if decision.horizon is not None and CLARIFY_FIELD_HORIZON in pending_missing:
        return True
    if (
        coerce_analysis_scopes(decision.analysis_scopes)
        and CLARIFY_FIELD_ANALYSIS_SCOPES in pending_missing
    ):
        return True
    if decision.purpose is not None and CLARIFY_FIELD_PURPOSE in pending_missing:
        return True
    return False


def _no_progress_clarification_invalid(
    decision: ConversationGateOutput,
    pending: dict | None,
) -> bool:
    """Invalid no-progress / contradictory clarify package while pending exists.

    Must catch model errors that wrongly set relationship=INDEPENDENT (or FOLLOW_UP)
    with an empty delta — do NOT require allow_merge / CLARIFICATION_ANSWER.
    """
    if not pending:
        return False
    if decision.action != GateRoute.CLARIFY:
        return False

    delta = decision.newly_resolved_fields or NewlyResolvedFields()
    if delta.has_any():
        return False
    if _fills_pending_missing_field(decision, pending):
        return False

    previous_q = pending.get("previous_clarification_question") or pending.get("clarification")
    same_question = questions_are_same(decision.clarification_question, previous_q)
    zero_blank = float(decision.confidence) == 0.0 and not (decision.reason or "").strip()

    # Classic no-progress: same question, zero conf, blank reason — any relationship
    if same_question and zero_blank:
        return True

    # Contradictory: pending clarify continued as INDEPENDENT with no useful delta
    if (
        decision.context_relationship == ContextRelationship.INDEPENDENT
        and not _establishes_independent_goal(decision)
        and (same_question or zero_blank or bool(_pending_missing_names(pending)))
    ):
        return True

    # FOLLOW_UP that only re-asks the same clarify with no delta
    if (
        decision.context_relationship == ContextRelationship.FOLLOW_UP
        and same_question
        and zero_blank
    ):
        return True

    return False


def _establishes_independent_goal(decision: ConversationGateOutput) -> bool:
    """True when the message looks like a new self-contained request (not pending absorb)."""
    if decision.action in {GateRoute.FAST, GateRoute.GENERAL_CHAT, GateRoute.OFF_TOPIC}:
        return True
    if decision.action in {GateRoute.STANDARD, GateRoute.RESEARCH}:
        if decision.intent in ANALYSIS_INTENTS and (
            coerce_analysis_scopes(decision.analysis_scopes) or decision.horizon is not None
        ):
            return True
    return False


def enforce_gate_consistency(
    decision: ConversationGateOutput,
    pending: dict | None = None,
) -> ConversationGateOutput:
    del pending
    kind = (decision.fast_kind or "").lower() if decision.fast_kind else ""

    if _is_invalid_zero_conf_package(decision):
        raise GateValidationError(
            "invalid Gate package: confidence=0 with blank reason and contradictory/missing fields"
        )

    if decision.action == GateRoute.FAST:
        if kind not in FAST_KIND_ALLOWLIST:
            raise GateValidationError(f"FAST requires valid fast_kind, got {decision.fast_kind!r}")
        if kind == "quote" and decision.intent != Intent.PRICE_QUERY:
            raise GateValidationError("FAST quote requires intent=price_query")
        return decision.model_copy(
            update={
                "fast_kind": kind,
                "complexity": ComplexityLevel.FAST,
                "missing_fields": [],
                "clarification_question": None,
            }
        )

    if decision.action in {GateRoute.STANDARD, GateRoute.RESEARCH}:
        unresolved = _analysis_fields_unresolved(decision)
        if unresolved:
            if not _establishes_analysis_request(decision):
                raise GateValidationError(
                    f"{decision.action.value} incomplete without established analysis request"
                )
            if not (decision.reason or "").strip() and float(decision.confidence) == 0.0:
                raise GateValidationError(
                    f"{decision.action.value} incomplete with zero confidence and blank reason"
                )
            return decision.model_copy(
                update={
                    "action": GateRoute.CLARIFY,
                    "complexity": ComplexityLevel.STANDARD,
                    "missing_fields": unresolved,
                    "clarification_question": deterministic_clarify_question(unresolved),
                    "normalized_query": None,
                    "reason": (
                        f"consistency: {decision.action.value} with unresolved "
                        f"{unresolved} → CLARIFY ({decision.reason})"
                    ),
                }
            )

    return decision


def postprocess_gate_output(
    decision: ConversationGateOutput,
    pending: dict | None,
    query: str,
    context: dict | None = None,
) -> ConversationGateOutput:
    """Relationship-aware merge — no deterministic fragment extraction on the normal path."""
    rel = decision.context_relationship or ContextRelationship.INDEPENDENT
    decision = decision.model_copy(
        update={
            "context_relationship": rel,
            "is_follow_up": derive_is_follow_up(rel),
        }
    )

    # Detect invalid no-progress / contradictory packages BEFORE merge/routing
    # so wrongly labeled INDEPENDENT still triggers compact repair.
    if _no_progress_clarification_invalid(decision, pending):
        raise GateValidationError(
            "no-progress clarification: empty newly_resolved_fields, confidence=0, "
            "blank reason, unchanged question (or contradictory INDEPENDENT clarify)"
        )

    allow_merge = rel == ContextRelationship.CLARIFICATION_ANSWER and bool(pending)
    merged = merge_clarification_state(pending, decision, allow_pending_merge=allow_merge)

    merged = enforce_gate_consistency(merged, pending)
    if merged.action == GateRoute.CLARIFY:
        guard_pending = pending if allow_merge else None
        merged = apply_clarify_question_guard(merged, guard_pending)
        if not (merged.clarification_question or "").strip() and merged.missing_fields:
            merged = merged.model_copy(
                update={
                    "clarification_question": deterministic_clarify_question(merged.missing_fields)
                }
            )
    merged = repair_normalized_query(
        merged, pending, query, context, allow_pending_merge=allow_merge
    )
    return merged


def validate_gate_output(raw: ConversationGateOutput) -> ConversationGateOutput:
    if raw.action not in GateRoute:
        raise GateValidationError(f"Invalid action: {raw.action}")

    conf = float(raw.confidence)
    if conf < 0.0 or conf > 1.0:
        raise GateValidationError("confidence out of range")

    out = raw.model_copy(deep=True)
    out = out.model_copy(
        update={"is_follow_up": derive_is_follow_up(out.context_relationship)}
    )

    if out.action == GateRoute.FAST:
        kind = (out.fast_kind or "").lower() if out.fast_kind else ""
        if kind not in FAST_KIND_ALLOWLIST:
            raise GateValidationError(f"FAST requires valid fast_kind, got {out.fast_kind!r}")
        if kind == "quote" and out.intent != Intent.PRICE_QUERY:
            raise GateValidationError("FAST quote requires intent=price_query")
        return out.model_copy(
            update={
                "fast_kind": kind,
                "complexity": ComplexityLevel.FAST,
                "missing_fields": [],
                "clarification_question": None,
            }
        )

    if out.action == GateRoute.CLARIFY:
        if not (out.clarification_question or "").strip():
            raise GateValidationError("CLARIFY requires clarification_question")
        if not out.missing_fields:
            raise GateValidationError("CLARIFY requires missing_fields")

    if out.action in {GateRoute.STANDARD, GateRoute.RESEARCH}:
        nq = (out.normalized_query or "").strip()
        if not nq:
            raise GateValidationError(f"{out.action.value} requires normalized_query")
        if _analysis_fields_unresolved(out):
            raise GateValidationError(f"{out.action.value} requires resolved analysis fields")
        complexity = (
            ComplexityLevel.RESEARCH if out.action == GateRoute.RESEARCH else ComplexityLevel.STANDARD
        )
        out = out.model_copy(update={"normalized_query": nq, "complexity": complexity})

    return out


def gate_diagnostics(decision: ConversationGateOutput) -> dict[str, Any]:
    delta = decision.newly_resolved_fields or NewlyResolvedFields()
    return {
        "action": decision.action.value if decision.action else None,
        "intent": decision.intent.value if decision.intent else None,
        "analysis_scopes": scope_values(decision.analysis_scopes),
        "context_relationship": (
            decision.context_relationship.value if decision.context_relationship else None
        ),
        "is_follow_up": decision.is_follow_up,
        "fast_kind": decision.fast_kind,
        "horizon": decision.horizon.value if decision.horizon else None,
        "resolved_fields": decision.resolved_fields,
        "missing_fields": decision.missing_fields,
        "newly_resolved_fields": {
            "intent": delta.intent.value if delta.intent else None,
            "analysis_scopes": (
                scope_values(delta.analysis_scopes) if delta.analysis_scopes else None
            ),
            "horizon": delta.horizon.value if delta.horizon else None,
            "purpose": delta.purpose.value if delta.purpose else None,
        },
        "delta_conflict": decision.delta_conflict,
        "confidence": decision.confidence,
        "reason": decision.reason,
        "repair_used": decision.repair_used,
        "emergency_fallback": decision.emergency_fallback
        or (decision.reason or "").startswith("emergency_fallback"),
    }


def _is_retryable_llm_error(exc: Exception) -> bool:
    name = type(exc).__name__
    if "ModelBehaviorError" in name or "Invalid JSON" in str(exc):
        return True
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    return False


def gate_decision_to_output(decision: GateDecision, query: str) -> ConversationGateOutput:
    if decision.route == GateRoute.RESEARCH:
        action = (
            GateRoute.RESEARCH
            if decision.complexity == ComplexityLevel.RESEARCH
            else GateRoute.STANDARD
        )
    else:
        action = decision.route

    fast_kind = decision.fast_kind if decision.fast_kind in FAST_KIND_ALLOWLIST else None
    fast_interval = None
    if decision.fast_params:
        fast_interval = decision.fast_params.get("interval")

    intent = Intent.PRICE_QUERY if fast_kind == "quote" else None
    return ConversationGateOutput(
        action=action,
        intent=intent,
        purpose=None,
        horizon=None,
        analysis_scopes=[],
        context_relationship=ContextRelationship.INDEPENDENT,
        is_follow_up=False,
        resolved_fields={},
        missing_fields=(
            [CLARIFY_FIELD_ANALYSIS_SCOPES, CLARIFY_FIELD_HORIZON]
            if action == GateRoute.CLARIFY
            else []
        ),
        clarification_question=decision.clarification_question,
        fast_kind=fast_kind,
        fast_interval=fast_interval,
        normalized_query=query if action in {GateRoute.STANDARD, GateRoute.RESEARCH} else None,
        complexity=decision.complexity,
        confidence=0.4,
        reason=f"emergency_fallback:{decision.reason}",
        emergency_fallback=True,
    )


def build_emergency_fallback(
    query: str,
    *,
    pending: dict | None,
    trade_mode: bool,
    context: dict | None,
) -> ConversationGateOutput:
    if looks_like_greeting(query):
        return ConversationGateOutput(
            action=GateRoute.GENERAL_CHAT,
            context_relationship=ContextRelationship.INDEPENDENT,
            complexity=ComplexityLevel.FAST,
            confidence=0.5,
            reason="emergency_fallback:greeting",
            emergency_fallback=True,
        )

    standalone = classify_gate(
        query, trade_mode=trade_mode, has_prior_thesis=False, pending_clarification=False
    )
    if standalone.route == GateRoute.FAST and standalone.fast_kind == "quote":
        out = gate_decision_to_output(standalone, query)
        return out.model_copy(
            update={
                "intent": Intent.PRICE_QUERY,
                "context_relationship": ContextRelationship.INDEPENDENT,
                "reason": "emergency_fallback:independent_price",
                "emergency_fallback": True,
            }
        )
    if standalone.route == GateRoute.FAST and standalone.fast_kind in FAST_KIND_ALLOWLIST:
        return gate_decision_to_output(standalone, query)

    if pending:
        pending_norm = dict(pending)
        pending_norm["resolved_fields"] = normalize_resolved_fields(
            pending.get("resolved_fields") or {}
        )
        pending_norm["missing_fields"] = [
            _normalize_missing_name(f) for f in (pending.get("missing_fields") or [])
        ]
        inferred = infer_clarification_fragment(query)
        pending_missing = list(pending_norm["missing_fields"] or [])
        if not pending_missing:
            rf = pending_norm["resolved_fields"]
            pending_missing = [
                f
                for f in (CLARIFY_FIELD_ANALYSIS_SCOPES, CLARIFY_FIELD_HORIZON)
                if f not in rf
            ]
        useful = {k: v for k, v in inferred.items() if k in pending_missing}
        if useful:
            partial = ConversationGateOutput(
                action=GateRoute.CLARIFY,
                context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
                missing_fields=pending_missing,
                clarification_question=deterministic_clarify_question(pending_missing),
                confidence=0.4,
                reason="emergency_fallback:clarification_answer",
                emergency_fallback=True,
            )
            partial = _apply_inferred_to_output(partial, useful)
            result = postprocess_gate_output(partial, pending_norm, query, context)
            try:
                return validate_gate_output(result).model_copy(
                    update={"emergency_fallback": True}
                )
            except GateValidationError:
                return ConversationGateOutput(
                    action=GateRoute.GENERAL_CHAT,
                    context_relationship=ContextRelationship.INDEPENDENT,
                    complexity=ComplexityLevel.FAST,
                    confidence=0.35,
                    reason="emergency_fallback:pending_unrecognized",
                    emergency_fallback=True,
                )

        return ConversationGateOutput(
            action=GateRoute.GENERAL_CHAT,
            context_relationship=ContextRelationship.INDEPENDENT,
            complexity=ComplexityLevel.FAST,
            confidence=0.35,
            reason="emergency_fallback:pending_cancelled",
            emergency_fallback=True,
        )

    fallback = gate_decision_to_output(standalone, query)
    if fallback.action == GateRoute.CLARIFY:
        fallback = fallback.model_copy(
            update={
                "missing_fields": [CLARIFY_FIELD_ANALYSIS_SCOPES, CLARIFY_FIELD_HORIZON],
                "clarification_question": deterministic_clarify_question(
                    [CLARIFY_FIELD_ANALYSIS_SCOPES, CLARIFY_FIELD_HORIZON]
                ),
            }
        )
    try:
        return validate_gate_output(
            postprocess_gate_output(fallback, None, query, context)
        ).model_copy(update={"emergency_fallback": True})
    except GateValidationError:
        return ConversationGateOutput(
            action=GateRoute.GENERAL_CHAT,
            context_relationship=ContextRelationship.INDEPENDENT,
            complexity=ComplexityLevel.FAST,
            confidence=0.3,
            reason=f"emergency_fallback_invalid:{standalone.reason}",
            emergency_fallback=True,
        )


async def run_conversation_gate(
    context: dict[str, Any],
    *,
    query: str,
    trade_mode: bool,
    pending: dict | None,
) -> ConversationGateOutput:
    last_exc: Exception | None = None
    repair_used = False

    pending_norm = None
    if pending:
        pending_norm = dict(pending)
        pending_norm["resolved_fields"] = normalize_resolved_fields(
            pending.get("resolved_fields") or {}
        )
        pending_norm["missing_fields"] = [
            _normalize_missing_name(f) for f in (pending.get("missing_fields") or [])
        ]

    async def _once(payload: dict[str, Any], *, as_repair: bool) -> ConversationGateOutput:
        nonlocal repair_used
        if not settings.openai_api_key:
            raise RuntimeError("OpenAI API key is not configured.")
        raw = await asyncio.wait_for(
            Runner.run(conversation_gate_agent, json.dumps(payload, default=str)),
            timeout=settings.llm_timeout,
        )
        out = _llm_to_output(raw.final_output)
        processed = postprocess_gate_output(out, pending_norm, query, payload)
        validated = validate_gate_output(processed)
        if as_repair:
            repair_used = True
            validated = validated.model_copy(update={"repair_used": True})
        return validated

    try:
        return await _once(context, as_repair=False)
    except GateValidationError as exc:
        last_exc = exc
        logger.warning("Gate validation failed — attempting compact repair: %s", exc)
    except Exception as exc:
        last_exc = exc
        if not _is_retryable_llm_error(exc):
            logger.error("Conversation Gate LLM failed: %s", exc)
            fb = build_emergency_fallback(
                query, pending=pending_norm, trade_mode=trade_mode, context=context
            )
            return fb.model_copy(update={"emergency_fallback": True})
        logger.warning("Conversation Gate LLM error — attempting compact repair: %s", exc)

    try:
        compact = build_compact_repair_context(context, query)
        return await _once(compact, as_repair=True)
    except Exception as exc:
        last_exc = exc
        logger.warning("Gate repair failed: %s", exc)

    logger.error(
        "Conversation Gate unavailable — using emergency fallback: %s",
        last_exc,
    )
    fb = build_emergency_fallback(
        query, pending=pending_norm, trade_mode=trade_mode, context=context
    )
    return fb.model_copy(
        update={"emergency_fallback": True, "repair_used": repair_used}
    )
