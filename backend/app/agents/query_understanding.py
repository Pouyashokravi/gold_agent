"""Legacy Query Understanding + Gold Planner agents.

V2 replaces these with the Gold Manager plan step
(`app.agents.gold_manager.gold_manager_plan_agent`).

Kept for reference and any external imports; not used by `run_pipeline`.
"""

from agents import Agent, AgentOutputSchema

from app.config import settings
from app.schemas.planner import GoldPlannerOutput
from app.schemas.query import QueryUnderstandingOutput

query_understanding_agent = Agent(
    name="QueryUnderstanding",
    instructions="LEGACY — unused in V2. Prefer Gold Manager Plan.",
    model=settings.fast_model,
    output_type=AgentOutputSchema(QueryUnderstandingOutput, strict_json_schema=False),
)

gold_planner_agent = Agent(
    name="GoldPlanner",
    instructions="LEGACY — unused in V2. Prefer Gold Manager Plan.",
    model=settings.manager_model,
    output_type=AgentOutputSchema(GoldPlannerOutput, strict_json_schema=False),
)
