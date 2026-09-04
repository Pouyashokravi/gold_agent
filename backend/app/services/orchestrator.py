"""Pipeline entrypoint — V2 Gold Manager runtime."""

from collections.abc import AsyncGenerator

from app.services.manager_runtime import run_v2_pipeline


async def run_pipeline(
    query: str,
    conversation_id: str,
    trade_mode: bool = False,
) -> AsyncGenerator[str, None]:
    async for event in run_v2_pipeline(query, conversation_id, trade_mode):
        yield event
