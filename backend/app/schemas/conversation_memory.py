"""Rolling conversation summary models (per conversation_id, not a user profile)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConversationSummary(BaseModel):
    main_topic: str = ""
    user_goals: list[str] = Field(default_factory=list)
    important_context: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    resolved_questions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    current_state: str = ""


class ConversationMemoryRecord(BaseModel):
    conversation_id: str
    summary: ConversationSummary = Field(default_factory=ConversationSummary)
    last_summarized_message_id: int | None = None
    summarized_message_count: int = 0
    updated_at: str | None = None
