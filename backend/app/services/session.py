"""Conversation session adapter for OpenAI Agents SDK Session protocol."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.db import repositories


class ConversationSession:
    """Wraps the app messages table so Runner.run(session=...) keeps multi-turn context.

    Separate from short-term working memory (data/evidence cache).
    """

    def __init__(self, conversation_id: str, limit: int | None = None) -> None:
        self.session_id = conversation_id
        self.conversation_id = conversation_id
        self.limit = limit or settings.session_history_limit

    async def get_items(self, limit: int | None = None) -> list[dict[str, Any]]:
        n = limit if limit is not None else self.limit
        rows = await repositories.get_messages(self.conversation_id, limit=n)
        items: list[dict[str, Any]] = []
        for row in rows:
            role = row["role"]
            if role not in {"user", "assistant", "system", "developer"}:
                role = "user"
            items.append({"role": role, "content": row["content"]})
        return items

    async def add_items(self, items: list[dict[str, Any]]) -> None:
        # UI persistence is handled explicitly by the runtime to attach metadata.
        # Avoid double-writing every SDK tool/message item into the chat transcript.
        return

    async def pop_item(self) -> dict[str, Any] | None:
        return None

    async def clear_session(self) -> None:
        return


async def history_text(conversation_id: str, limit: int | None = None) -> str:
    rows = await repositories.get_messages(
        conversation_id,
        limit=limit or settings.session_history_limit,
    )
    return "\n".join(f"{m['role']}: {m['content']}" for m in rows)


async def history_for_manager(conversation_id: str, limit: int | None = None) -> list[dict[str, str]]:
    rows = await repositories.get_messages(
        conversation_id,
        limit=limit or settings.session_history_limit,
    )
    return [{"role": m["role"], "content": m["content"]} for m in rows]


async def get_pending_clarification(conversation_id: str, limit: int = 12) -> dict | None:
    """If the last assistant turn asked for clarification, return context for resume.

    Returns ``{"pending_goal": str, "clarification": str}`` or None.
    """
    rows = await repositories.get_messages(conversation_id, limit=limit)
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
    if meta.get("route") != "clarify":
        return None

    pending_goal = meta.get("pending_goal")
    if not pending_goal:
        for j in range(last_assistant_idx - 1, -1, -1):
            if rows[j]["role"] == "user":
                pending_goal = rows[j]["content"]
                break
    if not pending_goal:
        return None

    return {
        "pending_goal": str(pending_goal),
        "clarification": assistant.get("content") or "",
        "missing": meta.get("missing") or ["horizon"],
    }
