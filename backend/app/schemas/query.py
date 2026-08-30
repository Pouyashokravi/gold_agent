from pydantic import BaseModel, Field

from app.schemas.common import Horizon, Intent, ResearchDepth


class QueryUnderstandingOutput(BaseModel):
    intents: list[Intent] = Field(min_length=1)
    horizon: Horizon
    requested_depth: ResearchDepth
