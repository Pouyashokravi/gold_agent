"""Legacy Intent Router.

V2 uses the deterministic gate in `app.services.gate` plus DirectChat for
GENERAL_CHAT / OFF_TOPIC. This agent is unused by `run_pipeline`.
"""

from agents import Agent, AgentOutputSchema

from app.config import settings
from app.schemas.routing import IntentRouterOutput

intent_router_agent = Agent(
    name="IntentRouter",
    instructions="LEGACY — unused in V2. Prefer app.services.gate.classify_gate.",
    model=settings.fast_model,
    output_type=AgentOutputSchema(IntentRouterOutput, strict_json_schema=False),
)
