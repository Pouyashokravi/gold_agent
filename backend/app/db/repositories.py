import json
import uuid
from datetime import UTC, datetime

from app.db.sqlite import get_connection


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _month_key() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


async def create_conversation() -> str:
    cid = str(uuid.uuid4())
    async with get_connection() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, created_at) VALUES (?, ?)",
            (cid, _now()),
        )
        await conn.commit()
    return cid


async def add_message(conversation_id: str, role: str, content: str, metadata: dict | None = None) -> None:
    async with get_connection() as conn:
        await conn.execute(
            "INSERT INTO messages (conversation_id, role, content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (conversation_id, role, content, json.dumps(metadata or {}, default=str), _now()),
        )
        await conn.commit()


async def get_messages(conversation_id: str, limit: int = 10) -> list[dict]:
    async with get_connection() as conn:
        cursor = await conn.execute(
            "SELECT role, content, metadata_json, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        )
        rows = await cursor.fetchall()
    out: list[dict] = []
    for r in reversed(rows):
        meta: dict = {}
        raw = r["metadata_json"]
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    meta = parsed
            except (TypeError, json.JSONDecodeError):
                meta = {}
        out.append({
            "role": r["role"],
            "content": r["content"],
            "created_at": r["created_at"],
            "metadata": meta,
        })
    return out


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
