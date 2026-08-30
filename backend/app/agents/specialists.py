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
    instructions="""Analyze XAU/USD news. You MUST call search_news_with_tavily once with a query about gold/XAU news today.
For economic data queries (CPI, NFP, Fed, GDP, PCE, unemployment, retail sales, jobless claims), also call
search_economic_releases to find actual vs forecast figures in headlines.
Summarize top headlines and their gold impact.
Return ONLY: direction, confidence (0-1), drivers, risks, events list.
Each event: title, summary, direction, importance, event_type (cpi/nfp/fed_rate/gdp/etc),
actual, forecast, previous, unit — ONLY populate actual/forecast/previous if explicitly stated in headlines.
If forecast is not mentioned in the headline, set forecast=null (do NOT guess).
Max 5 events. No evidence or sources arrays.""",
    model=settings.specialist_model,
    tools=NEWS_TOOLS,
    output_type=_out(NewsAgentResponse),
    model_settings=_news_settings,
)

fundamental_agent = Agent(
    name="FundamentalAgent",
    instructions="""Analyze XAU/USD macro fundamentals. Call get_macro_snapshot first (required).
Focus on rates, real yields, inflation impact on gold.
If the query or context mentions economic surprises (actual vs forecast for CPI, NFP, Fed, GDP),
reference them in fundamental_drivers with appropriate importance.
Return ONLY: direction, confidence (0-1), drivers (short strings), risks (short strings),
fundamental_drivers list with name, current_state, direction_for_gold, importance (LOW/MEDIUM/HIGH/CRITICAL), confidence.
Do NOT include evidence or sources arrays. Max 5 fundamental_drivers.""",
    model=settings.specialist_model,
    tools=FUND_TOOLS,
    output_type=_out(FundamentalAgentResponse),
    model_settings=_fund_settings,
)

short_term_agent = Agent(
    name="ShortTermTechnical",
    instructions="""Short-term XAU/USD technical analysis. Call get_xau_quote and get_xau_time_series first.
Return JSON with: direction (BULLISH/BEARISH/NEUTRAL/MIXED), confidence 0-1, trend, momentum, volatility strings,
support_levels and resistance_levels as number arrays, drivers, risks. Keep evidence empty list [].
Use ISO timestamp string for timestamp field. freshness: FRESH.""",
    model=settings.specialist_model,
    tools=TECH_TOOLS,
    output_type=_out(ShortTermTechnicalOutput),
    model_settings=_tech_settings,
)

long_term_agent = Agent(
    name="LongTermTechnical",
    instructions="""Long-term XAU/USD technical analysis. Call get_xau_time_series with 1day interval first.
Return JSON with direction, confidence, primary_trend, market_structure, major_support, major_resistance arrays,
drivers, risks. Keep evidence empty []. timestamp as ISO string. freshness: FRESH.""",
    model=settings.specialist_model,
    tools=TECH_TOOLS,
    output_type=_out(LongTermTechnicalOutput),
    model_settings=_tech_settings,
)

technical_agent = Agent(
    name="TechnicalAgent",
    instructions="""XAU/USD technical analysis. Call get_xau_quote first, then calculate_support_resistance.
Return ONLY valid JSON matching the schema — no markdown, no prose outside JSON.
Required fields: direction (BULLISH/BEARISH/NEUTRAL/MIXED), confidence (0-1), drivers (string list), risks (string list).
When trade_mode is true you MUST return:
- trade_setup: bias (LONG/SHORT/NO_TRADE), entry_zone [low,high], stop_loss, take_profit [tp1,tp2],
  risk_reward, invalidation (text), invalidation_level (numeric), confidence.
- chart_levels: trend (Bullish/Bearish/Neutral), support_levels[], resistance_levels[], invalidation_level.
Chart levels MUST match trade_setup levels exactly. Use NO_TRADE when no high-quality setup exists.
Keep drivers and risks to short strings (max 5 each).""",
    model=settings.specialist_model,
    tools=TECH_TOOLS,
    output_type=_out(TechnicalAgentResponse),
    model_settings=_tech_settings,
)

synthesis_agent = Agent(
    name="GoldSynthesis",
    instructions="""Synthesize specialist outputs for XAU/USD. No external research.
Use agent_conflicts input for structured agreement/contradiction analysis — do NOT hide conflicts.
Use economic_surprises input to weight evidence: larger surprises = higher importance.
Find agreements/contradictions. Weight by horizon. Build base/bull/bear scenarios (weights sum to 1.0).
Classify conflicts: DIRECTION_CONFLICT, HORIZON_CONFLICT, DATA_CONFLICT.
Explain important conflicts in contradictions and key_risks (e.g. bullish overall but bearish technical).
Passthrough trade_setup from technical only — do not invent entries.
IMPORTANT: The synthesis MUST explicitly address the user's question topic (e.g. Fed/rates for rate-cut queries,
CPI/inflation for inflation queries, specific years for historical queries).
For historical_analysis intent, include the requested time period in main_thesis even if live data is limited.""",
    model=settings.synthesis_model,
    output_type=_out(SynthesisOutput),
)

answer_generator_agent = Agent(
    name="FinalAnswerGenerator",
    instructions="""Format synthesis into a clear answer for the user.
You MUST write in the language specified by response_language in the input: "en" = English, "fa" = Persian/Farsi.
Never switch languages unless response_language says "fa".
Do NOT contradict the synthesis thesis, but DO explicitly mention key terms from the user's question
(e.g. Fed/Federal Reserve/rates, CPI/inflation, specific years like 2020, gold/XAU/USD).
For historical_analysis queries, briefly describe the requested historical period using well-known market context
when live specialist data is insufficient — do not refuse or ignore the historical timeframe.
Do NOT add unrelated new research beyond addressing the query context.
Structure: XAU/USD View, Direction, Confidence, Horizon, Main Thesis, Key Drivers,
context sections if data exists, Base/Bull/Bear, Risks, Invalidation.
When trade_mode is true you MUST include a **Trade Setup** section with:
Bias (LONG/SHORT), Entry Zone, Stop Loss, Take Profit targets, Risk/Reward, Invalidation.
Then add disclaimer: 'This output is market analysis only and is not financial or investment advice.'
Skip sections without data.""",
    model=settings.answer_model,
)
