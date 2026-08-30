from agents import Agent, AgentOutputSchema

from app.config import settings
from app.schemas.planner import GoldPlannerOutput
from app.schemas.query import QueryUnderstandingOutput

QUERY_UNDERSTANDING_INSTRUCTIONS = """You classify XAU/USD gold research queries.
Extract ALL intents present in the query from: market_outlook, technical_analysis, fundamental_analysis, news_analysis, event_impact, market_move_explanation, trade_analysis, price_query, historical_analysis.
Classify horizon: intraday, few_days, short_term, medium_term, long_term, ages.
Classify requested_depth: LIGHT, STANDARD, DEEP.

Horizon rules (IMPORTANT):
- today / now / امروز / الان / current price -> intraday
- this week / recent days / هفته / چند روز -> few_days
- 1-4 weeks -> short_term
- 1-6 months -> medium_term
- 6 months - 2 years -> long_term
- 2+ years / structural -> ages
- News about TODAY must be intraday or few_days, NEVER ages or long_term
- Multi-horizon impact questions (intraday + short-term + medium-term) -> medium_term

Persian queries: classify the same way using Persian time words (امروز=intraday, هفته=few_days, etc.).

Do NOT plan research, select tools, or answer the query."""

GOLD_PLANNER_INSTRUCTIONS = """You plan XAU/USD gold research. Decide which specialist agents run and at what depth.
Agents: news_agent, fundamental_agent, technical_agent.
Depths: OFF, LIGHT, STANDARD, DEEP.
Rules:
- news_analysis / event_impact / Fed / rate cut / rate hike / macro shock / "how would X affect gold" -> news_agent + fundamental_agent ENABLED (STANDARD or DEEP), technical STANDARD
- news_analysis / event_impact / "news today" / headlines -> news_agent ENABLED (STANDARD or DEEP)
- price_query/intraday only -> technical only, news OFF
- medium/long outlook -> fundamental + technical, news STANDARD if events relevant
- multi-horizon impact questions (intraday + short-term + medium-term) -> enable ALL three agents
- trade_mode=true -> technical may need trade setup focus
- Run minimum required agents but NEVER skip news when user asks for news or macro event impact
- Default execution_mode: PARALLEL
Do NOT call external APIs or perform analysis."""


def _out(model):
    return AgentOutputSchema(model, strict_json_schema=False)


query_understanding_agent = Agent(
    name="QueryUnderstanding",
    instructions=QUERY_UNDERSTANDING_INSTRUCTIONS,
    model=settings.query_model,
    output_type=_out(QueryUnderstandingOutput),
)

gold_planner_agent = Agent(
    name="GoldPlanner",
    instructions=GOLD_PLANNER_INSTRUCTIONS,
    model=settings.planner_model,
    output_type=_out(GoldPlannerOutput),
)
