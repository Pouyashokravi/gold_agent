from pydantic import BaseModel, Field

from app.schemas.common import AgentDepth, ExecutionMode


class AgentTask(BaseModel):
    enabled: bool
    depth: AgentDepth
    task: str = ""
    focus: list[str] = Field(default_factory=list)


class GoldPlannerOutput(BaseModel):
    news_agent: AgentTask
    fundamental_agent: AgentTask
    technical_agent: AgentTask
    execution_mode: ExecutionMode = "PARALLEL"
