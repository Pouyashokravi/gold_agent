from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.orchestrator import run_pipeline

router = APIRouter()

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
    "Content-Type": "text/event-stream; charset=utf-8",
}


class AnalyzeRequest(BaseModel):
    query: str
    conversation_id: str
    trade_mode: bool = False


@router.post("/analyze")
async def analyze(req: AnalyzeRequest):
    async def stream():
        async for event in run_pipeline(req.query, req.conversation_id, req.trade_mode):
            yield event

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)