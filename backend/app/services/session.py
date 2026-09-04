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
