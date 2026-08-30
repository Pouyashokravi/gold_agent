from enum import Enum

from pydantic import BaseModel, Field


class MessageRoute(str, Enum):
    RESEARCH = "research"
    GENERAL_CHAT = "general_chat"
    OFF_TOPIC = "off_topic"


class IntentRouterOutput(BaseModel):
    route: MessageRoute
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
