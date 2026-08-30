from fastapi import APIRouter, HTTPException

from app.db import repositories

router = APIRouter()


@router.post("/conversations")
async def create_conversation():
    cid = await repositories.create_conversation()
    return {"conversation_id": cid}


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    messages = await repositories.get_messages(conversation_id, limit=50)
    return {"conversation_id": conversation_id, "messages": messages}
