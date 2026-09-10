import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.db.sqlite import get_connection
from app.schemas.conversation_memory import ConversationMemoryRecord, ConversationSummary


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _month_key() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def _parse_metadata(raw: Any) -> dict:
    meta: dict = {}
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                meta = parsed
        except (TypeError, json.JSONDecodeError):
            meta = {}
    return meta


def _row_to_message(r) -> dict:
    return {
        "id": int(r["id"]),
        "role": r["role"],
        "content": r["content"],
        "created_at": r["created_at"],
        "metadata": _parse_metadata(r["metadata_json"]),
    }


async def create_conversation() -> str:
    cid = str(uuid.uuid4())
    async with get_connection() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, created_at) VALUES (?, ?)",
            (cid, _now()),
        )
        await conn.commit()
    return cid


async def add_message(
    conversation_id: str,
    role: str,
    content: str,
    metadata: dict | None = None,
) -> int:
    async with get_connection() as conn:
        cursor = await conn.execute(
            "INSERT INTO messages (conversation_id, role, content, metadata_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (conversation_id, role, content, json.dumps(metadata or {}, default=str), _now()),
        )
        await conn.commit()
        return int(cursor.lastrowid)


async def get_messages(conversation_id: str, limit: int = 10) -> list[dict]:
    async with get_connection() as conn:
        cursor = await conn.execute(
            "SELECT id, role, content, metadata_json, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        )
        rows = await cursor.fetchall()
    return [_row_to_message(r) for r in reversed(rows)]


async def get_messages_after(
    conversation_id: str,
    after_id: int | None,
    limit: int,
) -> list[dict]:
    """Return messages with id > after_id (or all if after_id is None), ascending, capped."""
    async with get_connection() as conn:
        if after_id is None:
            cursor = await conn.execute(
                "SELECT id, role, content, metadata_json, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY id ASC LIMIT ?",
                (conversation_id, limit),
            )
        else:
            cursor = await conn.execute(
                "SELECT id, role, content, metadata_json, created_at FROM messages "
                "WHERE conversation_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
                (conversation_id, after_id, limit),
            )
        rows = await cursor.fetchall()
    return [_row_to_message(r) for r in rows]


async def count_messages_after(conversation_id: str, after_id: int | None) -> int:
    async with get_connection() as conn:
        if after_id is None:
            cursor = await conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )
        else:
            cursor = await conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE conversation_id = ? AND id > ?",
                (conversation_id, after_id),
            )
        row = await cursor.fetchone()
    return int(row["c"]) if row else 0


async def get_conversation_memory(conversation_id: str) -> ConversationMemoryRecord | None:
    async with get_connection() as conn:
        cursor = await conn.execute(
            "SELECT conversation_id, summary_json, last_summarized_message_id, "
            "summarized_message_count, updated_at FROM conversation_memories "
            "WHERE conversation_id = ?",
            (conversation_id,),
        )
        row = await cursor.fetchone()
    if not row:
        return None
    try:
        summary = ConversationSummary.model_validate(json.loads(row["summary_json"]))
    except Exception:
        summary = ConversationSummary()
    return ConversationMemoryRecord(
        conversation_id=row["conversation_id"],
        summary=summary,
        last_summarized_message_id=row["last_summarized_message_id"],
        summarized_message_count=int(row["summarized_message_count"] or 0),
        updated_at=row["updated_at"],
    )


async def cas_save_conversation_memory(
    conversation_id: str,
    summary: ConversationSummary,
    new_last_message_id: int,
    new_summarized_count: int,
    expected_last_summarized_message_id: int | None,
) -> bool:
    """Optimistic cursor update. Returns True if exactly one row was written."""
    summary_json = json.dumps(summary.model_dump(mode="json"), default=str)
    updated_at = _now()
    async with get_connection() as conn:
        cursor = await conn.execute(
            "SELECT conversation_id, last_summarized_message_id FROM conversation_memories "
            "WHERE conversation_id = ?",
            (conversation_id,),
        )
        existing = await cursor.fetchone()

        if existing is None:
            if expected_last_summarized_message_id is not None:
                await conn.commit()
                return False
            await conn.execute(
                "INSERT INTO conversation_memories "
                "(conversation_id, summary_json, last_summarized_message_id, "
                "summarized_message_count, updated_at) VALUES (?, ?, ?, ?, ?)",
                (
                    conversation_id,
                    summary_json,
                    new_last_message_id,
                    new_summarized_count,
                    updated_at,
                ),
            )
            await conn.commit()
            return True

        current_cursor = existing["last_summarized_message_id"]
        if current_cursor != expected_last_summarized_message_id:
            await conn.commit()
            return False

        if expected_last_summarized_message_id is None:
            result = await conn.execute(
                "UPDATE conversation_memories SET summary_json=?, last_summarized_message_id=?, "
                "summarized_message_count=?, updated_at=? "
                "WHERE conversation_id=? AND last_summarized_message_id IS NULL",
                (
                    summary_json,
                    new_last_message_id,
                    new_summarized_count,
                    updated_at,
                    conversation_id,
                ),
            )
        else:
            result = await conn.execute(
                "UPDATE conversation_memories SET summary_json=?, last_summarized_message_id=?, "
                "summarized_message_count=?, updated_at=? "
                "WHERE conversation_id=? AND last_summarized_message_id=?",
                (
                    summary_json,
                    new_last_message_id,
                    new_summarized_count,
                    updated_at,
                    conversation_id,
                    expected_last_summarized_message_id,
                ),
            )
        await conn.commit()
        return int(result.rowcount or 0) == 1


async def save_technical_output(kind: str, output: dict) -> None:
    table = "short_term_technical_outputs" if kind == "short" else "long_term_technical_outputs"
    async with get_connection() as conn:
        await conn.execute(
            f"INSERT INTO {table} (output_json, created_at) VALUES (?, ?)",
            (json.dumps(output, default=str), _now()),
        )
        await conn.commit()


async def get_latest_technical_output(kind: str) -> dict | None:
    table = "short_term_technical_outputs" if kind == "short" else "long_term_technical_outputs"
    async with get_connection() as conn:
        cursor = await conn.execute(
            f"SELECT output_json, created_at FROM {table} ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
    if not row:
        return None
    data = json.loads(row["output_json"])
    data["_stored_at"] = row["created_at"]
    return data


async def get_tavily_usage() -> int:
    key = _month_key()
    async with get_connection() as conn:
        cursor = await conn.execute("SELECT count FROM tavily_usage WHERE month_key = ?", (key,))
        row = await cursor.fetchone()
    return int(row["count"]) if row else 0


async def increment_tavily_usage() -> None:
    key = _month_key()
    async with get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO tavily_usage (month_key, count) VALUES (?, 1)
            ON CONFLICT(month_key) DO UPDATE SET count = count + 1
            """,
            (key,),
        )
        await conn.commit()
