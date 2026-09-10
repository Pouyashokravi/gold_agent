"""Conversation context loading for the Conversation Gate (not a separate agent layer)."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.db import repositories
from app.schemas.conversation_gate import (
    CLARIFY_FIELD_ANALYSIS_SCOPES,
    normalize_resolved_fields,
)
from app.schemas.conversation_memory import ConversationSummary

_GATE_ASSISTANT_CONTENT_MAX = 320


def _truncate(text: str, limit: int = _GATE_ASSISTANT_CONTENT_MAX) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 3].rstrip() + "..."


def _normalize_missing_fields(fields: list[Any] | None) -> list[str]:
    out: list[str] = []
    for f in fields or []:
        name = str(f)
        if name in {"intent", "analysis_type", "type", "analysis_scopes", "scopes", "focus"}:
            name = CLARIFY_FIELD_ANALYSIS_SCOPES
        if name not in out:
            out.append(name)
    return out


def _normalize_pending_dict(pending: dict[str, Any] | None) -> dict[str, Any] | None:
    if not pending:
        return None
    normalized = dict(pending)
    normalized["resolved_fields"] = normalize_resolved_fields(pending.get("resolved_fields") or {})
    normalized["missing_fields"] = _normalize_missing_fields(
        pending.get("missing_fields") or pending.get("missing") or []
    )
    return normalized


async def load_conversation_context(
    conversation_id: str,
    current_user_message: str,
    *,
    trade_mode: bool = False,
) -> dict[str, Any]:
    """Assemble shaped Gate context: secondary history + final authoritative message block."""
    limit = settings.recent_messages_limit
    recent = await repositories.get_messages(conversation_id, limit=limit)
    memory = await repositories.get_conversation_memory(conversation_id)
    summary = memory.summary if memory else ConversationSummary()
    pending = _normalize_pending_dict(get_pending_clarification_from_messages(recent))
    clarify_turns = _count_consecutive_clarifications(recent)

    recent_payload = []
    for m in recent:
        role = m["role"]
        content = m["content"] or ""
        if role == "assistant":
            content = _truncate(content)
        item: dict[str, Any] = {"role": role, "content": content}
        meta = m.get("metadata") or {}
        route = meta.get("route") or meta.get("action")
        if route:
            item["route"] = route
        if meta.get("action") == "clarify" or meta.get("route") == "clarify":
            item["metadata"] = {
                "action": meta.get("action") or "clarify",
                "original_query": meta.get("original_query") or meta.get("pending_goal"),
                "resolved_fields": normalize_resolved_fields(meta.get("resolved_fields") or {}),
                "missing_fields": _normalize_missing_fields(meta.get("missing_fields")),
                "clarification_turn": meta.get("clarification_turn"),
                "previous_clarification_question": meta.get("previous_clarification_question"),
            }
        recent_payload.append(item)

    return {
        "authoritative_current_user_message": current_user_message,
        "current_user_message": current_user_message,
        "secondary_context_only": True,
        "rolling_summary": summary.model_dump(mode="json"),
        "recent_messages": recent_payload,
        "pending_clarification": pending,
        "trade_mode": trade_mode,
        "clarification_turn_count": clarify_turns,
        "AUTHORITATIVE_CURRENT_USER_MESSAGE": current_user_message,
        "route_only_on_this_message": current_user_message,
    }


def build_compact_repair_context(
    context: dict[str, Any],
    query: str,
) -> dict[str, Any]:
    """Compact Gate input for one repair retry — pending clarify snapshot, no long history."""
    pending = context.get("pending_clarification")
    if pending:
        resolved = normalize_resolved_fields(pending.get("resolved_fields") or {})
        missing = _normalize_missing_fields(pending.get("missing_fields"))
        prev_q = pending.get("previous_clarification_question") or pending.get("clarification")
        return {
            "authoritative_current_user_message": query,
            "current_user_message": query,
            "AUTHORITATIVE_CURRENT_USER_MESSAGE": query,
            "route_only_on_this_message": query,
            "repair_mode": True,
            "pending_original_query": pending.get("original_query") or pending.get("pending_goal"),
            "pending_resolved_fields": resolved,
            "pending_missing_fields": missing,
            "previous_clarification_question": prev_q,
            "pending_clarification": {
                "original_query": pending.get("original_query") or pending.get("pending_goal"),
                "resolved_fields": resolved,
                "missing_fields": missing,
                "previous_clarification_question": prev_q,
            },
            "trade_mode": context.get("trade_mode", False),
            "instruction": (
                "Previous Gate output was invalid or contradictory (often wrongly labeled "
                "INDEPENDENT with an empty newly_resolved_fields while pending clarification exists). "
                "Determine whether AUTHORITATIVE_CURRENT_USER_MESSAGE answers the pending "
                "clarification question. If it does: set context_relationship=CLARIFICATION_ANSWER "
                "and put ONLY newly established fields in newly_resolved_fields "
                "(e.g. horizon when the pending question asks for horizon). "
                "Preserve pending analysis_scopes and intent unless the current message clearly "
                "changes them — never replace a pending TECHNICAL (or other specific) scope with "
                "comprehensive FUNDAMENTAL+TECHNICAL+NEWS. "
                "Do not rely on unrelated conversation history."
            ),
        }

    # No pending: keep a tiny recent window
    recent = list(context.get("recent_messages") or [])[-2:]
    truncated = []
    for m in recent:
        truncated.append(
            {
                "role": m.get("role"),
                "content": _truncate(str(m.get("content") or ""), 120),
                "route": m.get("route"),
            }
        )
    return {
        "authoritative_current_user_message": query,
        "current_user_message": query,
        "secondary_context_only": True,
        "repair_mode": True,
        "pending_clarification": None,
        "recent_messages": truncated,
        "trade_mode": context.get("trade_mode", False),
        "AUTHORITATIVE_CURRENT_USER_MESSAGE": query,
        "route_only_on_this_message": query,
        "instruction": (
            "Previous Gate output was invalid or contradictory. "
            "Route ONLY on AUTHORITATIVE_CURRENT_USER_MESSAGE."
        ),
    }


async def history_text(conversation_id: str, limit: int | None = None) -> str:
    rows = await repositories.get_messages(
        conversation_id,
        limit=limit or settings.recent_messages_limit,
    )
    return "\n".join(f"{m['role']}: {m['content']}" for m in rows)


async def history_for_manager(conversation_id: str, limit: int | None = None) -> list[dict[str, str]]:
    rows = await repositories.get_messages(
        conversation_id,
        limit=limit or settings.recent_messages_limit,
    )
    return [{"role": m["role"], "content": m["content"]} for m in rows]


def get_pending_clarification_from_messages(rows: list[dict]) -> dict | None:
    if not rows:
        return None

    last_assistant_idx: int | None = None
    for i in range(len(rows) - 1, -1, -1):
        if rows[i]["role"] == "assistant":
            last_assistant_idx = i
            break
    if last_assistant_idx is None:
        return None

    assistant = rows[last_assistant_idx]
    meta = assistant.get("metadata") or {}
    if meta.get("route") != "clarify" and meta.get("action") != "clarify":
        return None

    original_query = meta.get("original_query") or meta.get("pending_goal")
    if not original_query:
        for j in range(last_assistant_idx - 1, -1, -1):
            if rows[j]["role"] == "user":
                original_query = rows[j]["content"]
                break
    if not original_query:
        return None

    return {
        "original_query": str(original_query),
        "pending_goal": str(original_query),
        "resolved_fields": normalize_resolved_fields(meta.get("resolved_fields") or {}),
        "missing_fields": _normalize_missing_fields(
            meta.get("missing_fields") or meta.get("missing") or []
        ),
        "previous_clarification_question": assistant.get("content") or "",
        "clarification": assistant.get("content") or "",
        "clarification_turn": int(meta.get("clarification_turn") or 1),
        "purpose": meta.get("purpose"),
        "user_goal": meta.get("user_goal"),
        "gate": meta.get("gate"),
    }


async def get_pending_clarification(conversation_id: str, limit: int | None = None) -> dict | None:
    rows = await repositories.get_messages(
        conversation_id,
        limit=limit or settings.recent_messages_limit,
    )
    return get_pending_clarification_from_messages(rows)


def _count_consecutive_clarifications(rows: list[dict]) -> int:
    """Count trailing assistant clarify turns (interrupted by non-clarify assistant)."""
    count = 0
    for m in reversed(rows):
        if m["role"] != "assistant":
            continue
        meta = m.get("metadata") or {}
        if meta.get("route") == "clarify" or meta.get("action") == "clarify":
            count += 1
        else:
            break
    return count
