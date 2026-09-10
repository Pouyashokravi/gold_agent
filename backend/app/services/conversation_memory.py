"""Rolling conversation summary maintenance (post-response, non-blocking)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agents import Runner

from app.agents.conversation_summarizer import conversation_summarizer_agent
from app.config import settings
from app.db import repositories
from app.schemas.conversation_memory import ConversationSummary

logger = logging.getLogger(__name__)

_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _lock_for(conversation_id: str) -> asyncio.Lock:
    async with _locks_guard:
        lock = _locks.get(conversation_id)
        if lock is None:
            lock = asyncio.Lock()
            _locks[conversation_id] = lock
        return lock


def schedule_summary_update(conversation_id: str) -> None:
    """Fire-and-forget after messages are persisted. Never blocks the user response."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("No running loop; skip summary schedule for %s", conversation_id)
        return
    loop.create_task(_safe_maybe_update(conversation_id))


async def _safe_maybe_update(conversation_id: str) -> None:
    try:
        await maybe_update_rolling_summary(conversation_id)
    except Exception:
        logger.exception("Conversation summary maintenance failed for %s", conversation_id)


async def maybe_update_rolling_summary(conversation_id: str) -> None:
    """Process 20-message batches while unsummarized_count >= batch size."""
    lock = await _lock_for(conversation_id)
    async with lock:
        batch_size = settings.conversation_summary_batch_size
        # Bound retries for stale CAS within one maintenance pass
        for _ in range(8):
            memory = await repositories.get_conversation_memory(conversation_id)
            cursor = memory.last_summarized_message_id if memory else None
            unsummarized = await repositories.count_messages_after(conversation_id, cursor)
            if unsummarized < batch_size:
                return

            batch = await repositories.get_messages_after(conversation_id, cursor, batch_size)
            if len(batch) < batch_size:
                return

            previous = memory.summary if memory else ConversationSummary()
            expected_cursor = cursor
            prev_count = memory.summarized_message_count if memory else 0

            try:
                updated = await _run_summarizer(previous, batch)
            except Exception:
                logger.exception(
                    "Summarizer LLM failed for %s; cursor left at %s",
                    conversation_id,
                    expected_cursor,
                )
                return

            new_last_id = int(batch[-1]["id"])
            new_count = prev_count + len(batch)
            ok = await repositories.cas_save_conversation_memory(
                conversation_id,
                updated,
                new_last_id,
                new_count,
                expected_cursor,
            )
            if not ok:
                logger.warning(
                    "Stale summary cursor for %s (expected=%s); discarding and retrying",
                    conversation_id,
                    expected_cursor,
                )
                continue
            # Successfully advanced; loop to process further batches if waiting ≥ 20
            continue


async def _run_summarizer(
    previous: ConversationSummary,
    messages: list[dict[str, Any]],
) -> ConversationSummary:
    if not settings.openai_api_key:
        raise RuntimeError("OpenAI API key is not configured.")
    payload = {
        "previous_summary": previous.model_dump(mode="json"),
        "new_messages": [
            {"id": m.get("id"), "role": m.get("role"), "content": m.get("content")}
            for m in messages
        ],
    }
    import json

    result = await asyncio.wait_for(
        Runner.run(conversation_summarizer_agent, json.dumps(payload, default=str)),
        timeout=settings.llm_timeout,
    )
    out = result.final_output
    if isinstance(out, ConversationSummary):
        return out
    if isinstance(out, dict):
        return ConversationSummary.model_validate(out)
    return ConversationSummary.model_validate(out)
