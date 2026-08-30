from agents import Agent, AgentOutputSchema

from app.config import settings
from app.schemas.routing import IntentRouterOutput

INTENT_ROUTER_INSTRUCTIONS = """You classify user messages for Gold Agent — an XAU/USD gold research assistant.

Assign exactly ONE route:

RESEARCH — the user wants gold/XAU/USD market analysis or data, including:
- Gold price, outlook, direction, technical/fundamental/news analysis
- Trade setups, entries, stops, targets for gold
- Macro drivers affecting gold: Fed, rates, USD/DXY, inflation, CPI, yields, geopolitics AS THEY RELATE TO GOLD
- Questions mixing greeting + gold topic (e.g. "hi, what's gold doing today?") → RESEARCH

GENERAL_CHAT — simple conversation that does NOT need live market data or specialist agents:
- Greetings, thanks, goodbye, small talk ("how are you", "what's your name")
- Questions about what Gold Agent is or what it can do
- Meta/help about using this assistant (not market analysis)

OFF_TOPIC — clearly unrelated to gold, finance, or this assistant's scope:
- Sports, cooking, entertainment, unrelated trivia, homework, coding, etc.
- General knowledge with no connection to gold or financial markets

Rules:
- If ANY part asks for gold/market analysis → RESEARCH (even with a greeting prefix)
- When unsure between GENERAL_CHAT and OFF_TOPIC, prefer GENERAL_CHAT if it's about the assistant itself
- When unsure between RESEARCH and GENERAL_CHAT, prefer RESEARCH if macro/gold terms appear

Output JSON only. Do not answer the user."""

intent_router_agent = Agent(
    name="IntentRouter",
    instructions=INTENT_ROUTER_INSTRUCTIONS,
    model=settings.query_model,
    output_type=AgentOutputSchema(IntentRouterOutput, strict_json_schema=False),
)
