from agents import Agent, AgentOutputSchema, function_tool
from agents.model_settings import ModelSettings

from app.config import settings
from app.schemas.fundamental import FundamentalAgentOutput
from app.schemas.fundamental_lite import FundamentalAgentResponse
from app.schemas.news import NewsAgentOutput
from app.schemas.news_lite import NewsAgentResponse
from app.schemas.synthesis import SynthesisOutput
from app.schemas.technical import LongTermTechnicalOutput, ShortTermTechnicalOutput
from app.schemas.technical_lite import TechnicalAgentResponse
from app.tools import fred, tavily, technical, twelve_data

# --- Twelve Data tools ---

@function_tool
async def get_xau_quote() -> dict:
    """Get live XAU/USD quote."""
    return await twelve_data.get_xau_quote()


@function_tool
async def get_xau_time_series(interval: str = "1h", outputsize: int = 100) -> dict:
    """Get XAU/USD OHLC time series. Intervals: 1min,5min,15min,1h,4h,1day,1week,1month."""
    return await twelve_data.get_xau_time_series(interval, outputsize)


@function_tool
async def get_xau_rsi(interval: str = "1h", time_period: int = 14) -> dict:
    return await twelve_data.get_xau_rsi(interval, time_period)


@function_tool
async def get_xau_sma(interval: str = "1h", time_period: int = 20) -> dict:
    return await twelve_data.get_xau_sma(interval, time_period)


@function_tool
async def get_xau_ema(interval: str = "1h", time_period: int = 20) -> dict:
    return await twelve_data.get_xau_ema(interval, time_period)


@function_tool
async def get_xau_macd(interval: str = "1h") -> dict:
    return await twelve_data.get_xau_macd(interval)


@function_tool
async def get_xau_atr(interval: str = "1h", time_period: int = 14) -> dict:
    return await twelve_data.get_xau_atr(interval, time_period)


@function_tool
async def calculate_support_resistance(interval: str = "1h", lookback: int = 20) -> dict:
    ts = await twelve_data.get_xau_time_series(interval, lookback + 5)
    values = ts.get("values", [])
    return technical.calculate_support_resistance(values, lookback)


@function_tool
async def calculate_volatility(interval: str = "1h", lookback: int = 20) -> dict:
    ts = await twelve_data.get_xau_time_series(interval, lookback + 5)
    values = ts.get("values", [])
    return technical.calculate_volatility(values, lookback)


# --- FRED tools ---

@function_tool
async def get_fred_series(series_id: str, limit: int = 30) -> dict:
    """Get FRED macro series. Allowed: DFF,DGS2,DGS10,DFII5,DFII10,CPIAUCSL,CPILFESL,PCEPI,PCEPILFE,UNRATE,PAYEMS."""
    return await fred.get_fred_series(series_id, limit=limit)


@function_tool
async def get_macro_snapshot() -> dict:
    """Get snapshot of key macro indicators from FRED."""
    return await fred.get_macro_snapshot()


# --- Tavily ---

@function_tool
async def search_economic_releases(query: str, depth_level: str = "STANDARD") -> dict:
    """Search economic release headlines for actual vs forecast data (CPI, NFP, Fed, GDP)."""
    return await tavily.search_economic_releases(query, depth_level)


@function_tool
async def search_news_with_tavily(query: str, depth_level: str = "STANDARD") -> dict:
    """Search gold/XAU news. Use sparingly. depth_level: LIGHT/STANDARD/DEEP."""
    return await tavily.search_news_with_tavily(query, depth_level)


TECH_TOOLS = [
    get_xau_quote, get_xau_time_series, get_xau_rsi, get_xau_sma,
    get_xau_ema, get_xau_macd, get_xau_atr,
    calculate_support_resistance, calculate_volatility,
]

FUND_TOOLS = [get_fred_series, get_macro_snapshot]
NEWS_TOOLS = [search_news_with_tavily, search_economic_releases]

_tool_settings = ModelSettings(tool_choice="auto")
_tech_settings = ModelSettings(tool_choice="auto", parallel_tool_calls=False)
_fund_settings = ModelSettings(tool_choice="auto", parallel_tool_calls=False)
_news_settings = ModelSettings(tool_choice="required", parallel_tool_calls=False)


def _out(model):
    return AgentOutputSchema(model, strict_json_schema=False)


news_agent = Agent(
    name="NewsAgent",
    instructions="""You are the News domain specialist for XAU/USD. Execute the Manager's task — do NOT create an architecture-level research plan.

You MUST call search_news_with_tavily once with a query aligned to the provided task/focus.
For economic data queries (CPI, NFP, Fed, GDP, PCE, unemployment, retail sales, jobless claims), also call
search_economic_releases to find actual vs forecast figures in headlines.
Prioritize evidence relevant to the user's horizon and the Manager task.
Summarize top headlines and their gold impact.
Return ONLY: direction, confidence (0-1), drivers, risks, events list.
Each event: title, summary, direction, importance, event_type (cpi/nfp/fed_rate/gdp/etc),
actual, forecast, previous, unit — ONLY populate actual/forecast/previous if explicitly stated in headlines.
If forecast is not mentioned in the headline, set forecast=null (do NOT guess).
Max 5 events. No evidence or sources arrays.""",
    model=settings.news_model,
    tools=NEWS_TOOLS,
    output_type=_out(NewsAgentResponse),
    model_settings=_news_settings,
)

fundamental_agent = Agent(
    name="FundamentalAgent",
    instructions="""You are the Fundamental/macro domain specialist for XAU/USD. Execute the Manager's task — do NOT re-plan the overall research architecture.

Call get_macro_snapshot first (required).
Focus on rates, real yields, inflation, USD impact on gold as required by the task.
If the query or context mentions economic surprises (actual vs forecast for CPI, NFP, Fed, GDP),
reference them in fundamental_drivers with appropriate importance.
Return ONLY: direction, confidence (0-1), drivers (short strings), risks (short strings),
fundamental_drivers list with name, current_state, direction_for_gold, importance (LOW/MEDIUM/HIGH/CRITICAL), confidence.
Do NOT include evidence or sources arrays. Max 5 fundamental_drivers.""",
    model=settings.fundamental_model,
    tools=FUND_TOOLS,
    output_type=_out(FundamentalAgentResponse),
    model_settings=_fund_settings,
)

short_term_agent = Agent(
    name="ShortTermTechnical",
    instructions="""LEGACY short-term refresh agent — V2 uses TechnicalAgent + STM.
Short-term XAU/USD technical analysis. Call get_xau_quote and get_xau_time_series first.
Return JSON with: direction (BULLISH/BEARISH/NEUTRAL/MIXED), confidence 0-1, trend, momentum, volatility strings,
support_levels and resistance_levels as number arrays, drivers, risks. Keep evidence empty list [].
Use ISO timestamp string for timestamp field. freshness: FRESH.""",
    model=settings.technical_model,
    tools=TECH_TOOLS,
    output_type=_out(ShortTermTechnicalOutput),
    model_settings=_tech_settings,
)

long_term_agent = Agent(
    name="LongTermTechnical",
    instructions="""LEGACY long-term refresh agent — V2 uses TechnicalAgent + STM.
Long-term XAU/USD technical analysis. Call get_xau_time_series with 1day interval first.
Return JSON with direction, confidence, primary_trend, market_structure, major_support, major_resistance arrays,
drivers, risks. Keep evidence empty []. timestamp as ISO string. freshness: FRESH.""",
    model=settings.technical_model,
    tools=TECH_TOOLS,
    output_type=_out(LongTermTechnicalOutput),
    model_settings=_tech_settings,
)

technical_agent = Agent(
    name="TechnicalAgent",
    instructions="""You are the Technical domain specialist for XAU/USD. Execute the Manager's task — do NOT create an architecture-level plan.

Call get_xau_quote first, then calculate_support_resistance (and other indicators as needed for the task).
Return ONLY valid JSON matching the schema — no markdown, no prose outside JSON.
Required fields: direction (BULLISH/BEARISH/NEUTRAL/MIXED), confidence (0-1), drivers (string list), risks (string list).
When trade_mode is true you MUST return:
- trade_setup: bias (LONG/SHORT/NO_TRADE), entry_zone [low,high], stop_loss, take_profit [tp1,tp2],
  risk_reward, invalidation (text), invalidation_level (numeric), confidence.
- chart_levels: trend (Bullish/Bearish/Neutral), support_levels[], resistance_levels[], invalidation_level.
Chart levels MUST match trade_setup levels exactly. Use NO_TRADE when no high-quality setup exists.
Keep drivers and risks to short strings (max 5 each).""",
    model=settings.technical_model,
    tools=TECH_TOOLS,
    output_type=_out(TechnicalAgentResponse),
    model_settings=_tech_settings,
)

# Legacy agents retained for import compatibility / gradual cleanup.
# V2 Gold Manager absorbs synthesis + final answer generation.
synthesis_agent = Agent(
    name="GoldSynthesis",
    instructions="Legacy synthesis agent — prefer Gold Manager Answer in V2.",
    model=settings.manager_model,
    output_type=_out(SynthesisOutput),
)

answer_generator_agent = Agent(
    name="FinalAnswerGenerator",
    instructions="Legacy answer agent — prefer Gold Manager Answer in V2.",
    model=settings.fast_model,
)
