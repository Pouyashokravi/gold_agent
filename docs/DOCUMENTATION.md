# Gold Research Agent — Comprehensive Documentation

> **XAU/USD Multi-Agent Research System**  
> A full-stack AI assistant that combines news, macro fundamentals, and technical analysis to produce synthesized gold market insights — with an optional **Trader Mode** for live trade setups and interactive charts.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [High-Level Architecture](#2-high-level-architecture)
3. [End-to-End Query Flow](#3-end-to-end-query-flow)
4. [Intent Router (First Gate)](#4-intent-router-first-gate)
5. [Agents Reference](#5-agents-reference)
6. [Horizon & Depth Model](#6-horizon--depth-model)
7. [Policy & Routing Rules](#7-policy--routing-rules)
8. [User Jobs (Test Scenarios)](#8-user-jobs-test-scenarios)
9. [Key Features (Deep Dive)](#9-key-features-deep-dive)
10. [News Weighting & Impact Scoring](#10-news-weighting--impact-scoring)
11. [Agent Conflict Analysis](#11-agent-conflict-analysis)
12. [Frontend & User Experience](#12-frontend--user-experience)
13. [API Reference](#13-api-reference)
14. [Data Layer & Persistence](#14-data-layer--persistence)
15. [External Integrations](#15-external-integrations)
16. [Technology Stack](#16-technology-stack)
17. [Configuration & Deployment](#17-configuration--deployment)
18. [Project Directory Map](#18-project-directory-map)

---

## 1. Project Overview

**Gold Research Agent** is a conversational research platform focused exclusively on **XAU/USD (gold)**. Users ask questions in natural language (English or Persian), and the system:

- Classifies intent and routes the query appropriately
- Understands time horizon and research depth
- Plans which specialist agents to activate
- Fetches live data from external APIs (Twelve Data, FRED, Tavily)
- Synthesizes multi-source evidence into a coherent market view
- Streams the final answer back to the user in real time

### Core Capabilities

| Capability | Description |
|---|---|
| **Price queries** | Live XAU/USD quote and intraday levels |
| **News analysis** | Today's gold-relevant headlines via Tavily |
| **Fundamental analysis** | Macro drivers (rates, real yields, USD, inflation) via FRED |
| **Technical analysis** | RSI, SMA, EMA, MACD, ATR, support/resistance via Twelve Data |
| **Event impact** | Fed rate scenarios, CPI surprises, macro shock analysis |
| **Trade setups** | Entry zone, stop loss, take profit, risk/reward |
| **Trader Mode** | Live candlestick chart with annotated levels |
| **Economic surprise** | Actual vs forecast parsing with gold bias interpretation |
| **Multi-language input** | English and Persian queries supported |
| **Conversation memory** | Full history + recent messages + rolling summary (per conversation) |
| **Off-topic handling** | Polite redirect for non-gold questions |

---

## 2. High-Level Architecture

> **V2 (current):** Adaptive Gold Manager. See [`docs/V2_ARCHITECTURE.md`](V2_ARCHITECTURE.md) for the full migration deliverable.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (Next.js 15)                           │
│  Chat UI │ Agent Status (V2) │ Result Card │ Trader Desk │ Live Chart   │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │ SSE (Server-Sent Events)
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         BACKEND (FastAPI)                               │
│                                                                         │
│  Conversation Gate LLM: GENERAL_CHAT / OFF_TOPIC / CLARIFY / FAST /     │
│    STANDARD / RESEARCH                                                  │
│    ├─ FAST → direct provider tools (API cache) → answer                 │
│    └─ STANDARD/RESEARCH → Gold Manager (plan → parallel agents+tools →  │
│         evidence → surprise/conflict → review/replan → answer)          │
│                                                                         │
│  Specialists: News │ Fundamental │ Technical (domain experts)           │
│  Data: Twelve Data │ FRED │ Tavily                                      │
│  Memory: Full history + recent messages + rolling summary (per chat)    │
└─────────────────────────────────────────────────────────────────────────┘
```

### Architectural Layers

| Layer | Location | Responsibility |
|---|---|---|
| **Presentation** | `frontend/` | Chat UI, trader desk, chart rendering, SSE consumption |
| **API** | `backend/app/api/` | HTTP endpoints, SSE streaming |
| **Orchestration** | `backend/app/services/manager_runtime.py` | V2 Gold Manager runtime |
| **Conversation Gate** | `backend/app/services/conversation_gate.py` | LLM routing before Manager (`gate.py` = emergency fallback) |
| **Agents** | `backend/app/agents/` | Gate, Summarizer, Gold Manager + domain specialists |
| **Policy** | `backend/app/services/policy.py` | Deterministic hard constraints on plans |
| **Conversation memory** | `backend/app/services/conversation_memory.py` | Rolling summary maintenance |
| **Scoring** | `backend/app/services/` | Economic surprise, news impact, conflict |
| **Tools** | `backend/app/tools/` | External API wrappers with caching |
| **Schemas** | `backend/app/schemas/` | Pydantic data models |
| **Persistence** | `backend/app/db/` | SQLite repositories |

---

## 3. End-to-End Query Flow

This section traces a user query from the moment it is submitted until the final answer is delivered.

### 3.1 Frontend Entry

```
User types query → ChatInput
       │
       ├─ Trade Mode toggle (Sidebar) → trade_mode: true/false
       │
       ├─ POST /api/conversations  → conversation_id (stored in localStorage)
       │
       └─ POST /api/analyze  → SSE stream
              Body: { query, conversation_id, trade_mode }
```

**Key files:** `frontend/app/page.tsx`, `frontend/lib/api.ts`

### 3.P Pipeline Stages (Research Route)

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. QUERY RECEIVED                                               │
│    Emit: query_received                                         │
│    Load last 8 messages from SQLite for conversation context    │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. INTENT ROUTING  (IntentRouter agent)                         │
│    Emit: routing_started → routing_completed                    │
│    Routes: RESEARCH | GENERAL_CHAT | OFF_TOPIC                  │
│    Fallback: keyword-based if router LLM fails                  │
└────────────┬───────────────────────────────┬────────────────────┘
             │ GENERAL_CHAT / OFF_TOPIC       │ RESEARCH
             ▼                                ▼
┌────────────────────────┐    ┌─────────────────────────────────────┐
│ 3a. DIRECT CHAT        │    │ 3b. QUERY UNDERSTANDING             │
│ DirectChat agent       │    │ QueryUnderstanding agent            │
│ Emit: chat_response    │    │ Extract: intents, horizon, depth    │
│ Stream answer → DONE   │    │ + policy horizon/intent overrides   │
└────────────────────────┘    │ Emit: understanding_completed       │
                              └────────────────┬────────────────────┘
                                               ▼
                              ┌─────────────────────────────────────┐
                              │ 4. PLANNING (GoldPlanner agent)     │
                              │ Decide which specialists run + depth  │
                              │ + apply_routing_overrides           │
                              │ + apply_trade_mode_overrides        │
                              │ Emit: planning_completed            │
                              └────────────────┬────────────────────┘
                                               ▼
                              ┌─────────────────────────────────────┐
                              │ 5. POLICY CHECK                     │
                              │ validate_plan (warn if no agents)   │
                              │ Emit: check_completed               │
                              └────────────────┬────────────────────┘
                                               ▼
                              ┌─────────────────────────────────────┐
                              │ 6. SPECIALIST EXECUTION             │
                              │ PARALLEL (default) or SEQUENTIAL    │
                              │                                     │
                              │  news_agent      → Tavily           │
                              │  fundamental_agent → FRED           │
                              │  technical_agent  → Twelve Data     │
                              │                                     │
                              │  + short_term_agent refresh (cache) │
                              │  + long_term_agent refresh (cache)  │
                              │                                     │
                              │  Each: *_started → *_completed      │
                              │  On failure: agent_fallback         │
                              └────────────────┬────────────────────┘
                                               ▼
                              ┌─────────────────────────────────────┐
                              │ 7. POST-PROCESSING                  │
                              │  • Economic surprise enrichment     │
                              │  • Agent conflict analysis          │
                              └────────────────┬────────────────────┘
                                               ▼
                              ┌─────────────────────────────────────┐
                              │ 8. SYNTHESIS (GoldSynthesis agent)  │
                              │ Merge specialist outputs            │
                              │ Apply conflict confidence adjust.   │
                              │ Attach trade_setup + chart_levels   │
                              │ Emit: synthesis_completed           │
                              └────────────────┬────────────────────┘
                                               ▼
                              ┌─────────────────────────────────────┐
                              │ 9. FINAL ANSWER                     │
                              │ FinalAnswerGenerator agent          │
                              │ Emit: answer_started                │
                              │       answer_delta (chunked)        │
                              │       answer_completed              │
                              │ Persist user + assistant messages   │
                              └─────────────────────────────────────┘
```

**Orchestrator:** `backend/app/services/orchestrator.py`

### 3.3 SSE Event Types

| Event | Phase | Description |
|---|---|---|
| `query_received` | Start | Request accepted |
| `routing_started` / `routing_completed` | Routing | Intent classification result |
| `chat_response` | Direct chat | Non-research route taken |
| `understanding_started` / `understanding_completed` | Understanding | Intents, horizon, depth |
| `planning_started` / `planning_completed` | Planning | Agent plan with enabled/depth |
| `check_started` / `check_completed` | Policy | Validation warnings |
| `news_agent_started` / `completed` | Specialists | News analysis |
| `fundamental_agent_started` / `completed` | Specialists | Macro analysis |
| `technical_agent_started` / `completed` | Specialists | Technical analysis |
| `short_term_agent_started` / `completed` | Cache refresh | Short-term TA cache |
| `long_term_agent_started` / `completed` | Cache refresh | Long-term TA cache |
| `agent_fallback` | Fallback | LLM failed; live data used |
| `synthesis_started` / `completed` | Synthesis | Merged research output |
| `answer_started` | Answer | Final response generation |
| `answer_delta` | Answer | Streaming text chunk |
| `answer_completed` | Answer | Full answer + synthesis metadata |
| `error` | Any | Failure notification |

### 3.4 Fallback Strategy

When a specialist LLM call fails, the system falls back to deterministic live-data builders:

| Specialist | Fallback Module | Data Source |
|---|---|---|
| News | `services/news_fallback.py` | Tavily direct search |
| Fundamental | `services/fundamental_fallback.py` | FRED macro snapshot |
| Technical | `services/technical_fallback.py` | Twelve Data quote + S/R |

---

## 4. Intent Router (First Gate)

The **Intent Router** sits at the very beginning of the pipeline — before any market data is fetched or specialist agents run. This saves API costs and latency for simple conversational or off-topic messages.

### 4.1 Routes

| Route | When | Handler |
|---|---|---|
| `RESEARCH` | Gold/XAU/USD analysis, price, news, trade setups, macro drivers | Full research pipeline |
| `GENERAL_CHAT` | Greetings, thanks, "what can you do?", meta questions | `DirectChat` agent (mode: `general_chat`) |
| `OFF_TOPIC` | Sports, cooking, homework, unrelated trivia | `DirectChat` agent (mode: `off_topic`) |

### 4.2 Classification Rules

- If **any part** of the message asks for gold/market analysis → `RESEARCH` (even with a greeting prefix, e.g. "Hi, what's gold doing today?")
- Macro/geopolitics **as they relate to gold** → `RESEARCH`
- When unsure between `GENERAL_CHAT` and `OFF_TOPIC` → prefer `GENERAL_CHAT` if about the assistant itself
- When unsure between `RESEARCH` and `GENERAL_CHAT` → prefer `RESEARCH` if gold/macro terms appear

### 4.3 Fallback Behavior

If the Intent Router LLM call fails:
- Query contains gold keywords → `RESEARCH`
- Otherwise → `GENERAL_CHAT`

**Files:** `backend/app/agents/intent_router.py`, `backend/app/schemas/routing.py`

### 4.4 Direct Chat Behavior

| Mode | Behavior |
|---|---|
| `general_chat` | Friendly response; mentions XAU/USD specialization; no live data |
| `off_topic` | Polite scope explanation; suggests gold-related questions; does not answer the off-topic question |

**File:** `backend/app/agents/direct_chat.py`

---

## 5. Agents Reference

All agents use the **OpenAI Agents SDK** (`Runner.run()`). Model assignments are configurable via environment variables.

### 5.1 Agent Inventory

| Agent | File | Default Model | Role |
|---|---|---|---|
| **IntentRouter** | `agents/intent_router.py` | `FAST_MODEL` | Classify message route (legacy) |
| **DirectChat** | `agents/direct_chat.py` | `FAST_MODEL` | Handle non-research messages |
| **QueryUnderstanding** | `agents/query_understanding.py` | `FAST_MODEL` | Legacy — unused in V2 |
| **GoldPlanner** | `agents/query_understanding.py` | `MANAGER_MODEL` | Legacy — unused in V2 |
| **Gold Manager** | `agents/gold_manager.py` | `MANAGER_MODEL` | Plan / review / synthesis / answer |
| **NewsAgent** | `agents/specialists.py` | `NEWS_MODEL` | News + economic releases (Tavily) |
| **FundamentalAgent** | `agents/specialists.py` | `FUNDAMENTAL_MODEL` | Macro fundamentals (FRED) |
| **TechnicalAgent** | `agents/specialists.py` | `TECHNICAL_MODEL` | Technical analysis + trade setup (Twelve Data) |
| **ShortTermTechnical** | `agents/specialists.py` | `TECHNICAL_MODEL` | Legacy short-term TA refresh |
| **LongTermTechnical** | `agents/specialists.py` | `TECHNICAL_MODEL` | Legacy long-term TA refresh |
| **GoldSynthesis** | `agents/specialists.py` | `MANAGER_MODEL` | Legacy synthesis stub |
| **FinalAnswerGenerator** | `agents/specialists.py` | `FAST_MODEL` | Legacy answer stub |

### 5.2 Specialist Tools

| Agent | Tools | External API |
|---|---|---|
| **NewsAgent** | `search_news_with_tavily`, `search_economic_releases` | Tavily |
| **FundamentalAgent** | `get_macro_snapshot`, `get_fred_series` | FRED |
| **TechnicalAgent** | `get_xau_quote`, `get_xau_time_series`, RSI, SMA, EMA, MACD, ATR, S/R, volatility | Twelve Data |
| **ShortTermTechnical** | Same as TechnicalAgent | Twelve Data |
| **LongTermTechnical** | Same as TechnicalAgent (1day interval) | Twelve Data |

### 5.3 Agent Activation Matrix (Typical)

| Query Type | News | Fundamental | Technical | Notes |
|---|---|---|---|---|
| Price only ("XAU/USD price?") | OFF | OFF | LIGHT | Minimal pipeline |
| News today | STANDARD/DEEP | OFF | STANDARD | News-focused |
| Trade setup | OFF | OFF | DEEP | Technical only |
| Event impact (Fed, CPI) | STANDARD/DEEP | STANDARD/DEEP | STANDARD | All three enabled |
| Medium/long outlook | STANDARD | STANDARD/DEEP | STANDARD | Fundamental-heavy |
| Trade Mode ON | LIGHT/OFF | LIGHT/OFF | DEEP | Forced intraday |

---

## 6. Horizon & Depth Model

### 6.1 Time Horizons

Defined in `backend/app/schemas/common.py`:

| Horizon | Time Scope | Example Queries |
|---|---|---|
| `intraday` | Today, now, current | "What is gold doing right now?" |
| `few_days` | This week, recent days | "What should I expect this week?" |
| `short_term` | 1–4 weeks | "Technical analysis for next 2-3 weeks" |
| `medium_term` | 1–6 months | "Medium-term outlook for next 3 months" |
| `long_term` | 6 months – 2 years | "Long-term structural view" |
| `ages` | 2+ years, structural | "How did gold perform during 2020?" |

**Persian equivalents:** امروز/الان → intraday, هفته → few_days, etc.

### 6.2 Research Depth (Query Level)

| Level | Description |
|---|---|
| `LIGHT` | Quick, minimal research |
| `STANDARD` | Normal depth |
| `DEEP` | Thorough analysis |

### 6.3 Agent Depth (Per Specialist)

| Level | Description | Tavily Budget |
|---|---|---|
| `OFF` | Agent disabled | 0 |
| `LIGHT` | Minimal data fetch | 1 search |
| `STANDARD` | Normal analysis | 2 searches |
| `DEEP` | Full analysis + trade setup | 2 searches |

### 6.4 Horizon-Based Agent Weighting

At synthesis time, evidence from each specialist is weighted by horizon (`backend/app/services/evidence.py`):

| Horizon | Technical | News | Fundamental |
|---|---|---|---|
| `intraday` | 0.90 | 0.85 | 0.20 |
| `few_days` | 0.80 | 0.75 | 0.40 |
| `short_term` | 0.75 | 0.60 | 0.50 |
| `medium_term` | 0.70 | 0.45 | 0.80 |
| `long_term` | 0.55 | 0.30 | 0.90 |
| `ages` | 0.45 | 0.15 | 0.95 |

**Formula:** `effective_weight = agent_weight × freshness × relevance × confidence`

---

## 7. Policy & Routing Rules

The **policy layer** (`backend/app/services/policy.py`) applies deterministic overrides on top of LLM planner output to ensure consistent routing.

### 7.1 Horizon Overrides

| Trigger | Override |
|---|---|
| "today", "now", "current", "امروز", "الان" | → `intraday` |
| "this week", "هفته" | → `few_days` |
| Trade query (no event impact) | → `intraday` |
| News query (no long-term markers) | Cap at `few_days` |
| Multi-horizon event query | → `medium_term` |
| Price-only query | → `intraday` |
| Trade Mode ON | → `intraday` (forced) |

### 7.2 Intent Overrides

| Trigger | Added Intents |
|---|---|
| Event impact keywords (Fed, CPI, NFP, "how would", "what if") | `event_impact`, `fundamental_analysis`, `market_move_explanation` |
| Fundamental keywords (real yields, DXY, macro) | `fundamental_analysis` |

### 7.3 Routing Overrides (Agent Enable/Disable)

| Query Pattern | News | Fundamental | Technical |
|---|---|---|---|
| Price only (≤8 words) | OFF | OFF | LIGHT |
| Event impact | STANDARD/DEEP | STANDARD/DEEP | STANDARD |
| Trade setup | OFF | OFF | DEEP |
| News needed | STANDARD/DEEP | — | — |
| Fundamental needed | — | STANDARD/DEEP | — |
| Technical intent | — | — | STANDARD |

**Default news focus areas:** Federal Reserve, US dollar, US yields, **geopolitical risk**, gold market.

### 7.4 Trade Mode Overrides

When `trade_mode=true`:

| Setting | Value |
|---|---|
| Horizon | Forced `intraday` |
| Intent | `trade_analysis` added |
| Technical agent | DEEP — trade setup with entry/SL/TP |
| News agent | LIGHT or OFF |
| Fundamental agent | LIGHT or OFF |

---

## 8. User Jobs (Test Scenarios)

The project includes **20 predefined user-job scenarios** for integration testing (`backend/scripts/userjob_test_runner.py`). Each job validates horizon, agent routing, and answer quality.

| # | Name | Query (summary) | Expected Horizon | Agents | Trade Mode |
|---|---|---|---|---|---|
| 1 | Intraday price (EN) | Current XAU/USD price | intraday | tech only | — |
| 2 | Intraday price (FA) | قیمت فعلی طلا | intraday | tech only | — |
| 3 | News today (EN) | Important gold headlines today | intraday/few_days | news + tech | — |
| 4 | News today (FA) | مهم‌ترین اخبار طلا امروز | intraday/few_days | news + tech | — |
| 5 | Fed multi-horizon | Unexpected 50bp Fed rate cut impact | multi | all three | — |
| 6 | Trade setup | Buy setup with entry/SL/TP | intraday | tech only | — |
| 7 | Trade mode toggle | Scalp trade analysis | intraday | tech only | ✓ |
| 8 | Short-term technical | TA for next 2-3 weeks | short_term | tech | — |
| 9 | Medium-term outlook | 3-month outlook | medium_term | fund + tech | — |
| 10 | Long-term structural | 2-year structural view | long_term/ages | fund + tech | — |
| 11 | Fundamental macro | Real yields and USD impact | any | fund + tech | — |
| 12 | Market move explanation | Why did gold move today? | intraday/few_days | news + tech | — |
| 13 | Historical analysis | Gold during 2020 pandemic | ages/long_term | — | — |
| 14 | Market outlook combined | Full outlook with news + fundamentals | any | all three | — |
| 15 | Few days / this week | Gold this week | few_days | tech | — |
| 16 | Multi-intent news+tech | Today's news + S/R levels | intraday/few_days | news + tech | — |
| 17 | Persian trade query | پوزیشن خرید با استاپ و تارگت | intraday | tech only | — |
| 18 | Price only minimal | "XAU/USD price?" | intraday | tech only | — |
| 19 | CPI event impact | Hot CPI scenario | any | all three | — |
| 20 | Follow-up context | "What about downside risk?" (after prior turn) | any | tech | context-aware |

**Run tests:** Start backend, then `python backend/scripts/userjob_test_runner.py`  
**Output:** `backend/test_report.json`

---

## 9. Key Features (Deep Dive)

### 9.1 Trader Mode

Trader Mode transforms the chat interface into a **trading desk** optimized for actionable intraday setups.

#### Activation
- **Frontend:** "Trade analysis" toggle in the Sidebar (`frontend/components/Sidebar.tsx`)
- **API:** `trade_mode: true` in the `/api/analyze` request body

#### Backend Behavior

1. **Horizon** forced to `intraday`
2. **Intent** `trade_analysis` injected
3. **Technical agent** runs at `DEEP` depth with explicit trade-setup task:
   - Entry zone (low–high)
   - Stop loss
   - Take profit levels
   - Risk/reward ratio
   - Bias: `LONG` / `SHORT` / `NO_TRADE`
   - Invalidation level
4. **News/Fundamental** agents run at `LIGHT` or are disabled
5. **Synthesis** attaches `chart_annotations` with default interval `1h`
6. **Answer** must include a Trade Setup section (auto-appended if missing)
7. **Conflict override:** severe direction conflict → reduce confidence or force `NO_TRADE`

#### Frontend Trader Desk

When Trade Mode is active, the UI shows:

| Component | Purpose |
|---|---|
| `TraderTicker` | Live XAU/USD quote (polling) |
| `TraderChart` | Candlestick chart with annotated price lines |
| `TraderAnalysisPanel` | Compact trade setup card |

**Chart intervals:** 5m, 15m, 1H, 4H, 1D

#### Chart Level Annotations

The chart displays horizontal price lines for:
- Support levels
- Resistance levels
- Entry zone
- Stop loss
- Take profit targets
- Invalidation level

**Data flow:**
```
TechnicalAgent → chart_levels + trade_setup
       │
       ▼
Synthesis → chart_annotations
       │
       ▼
Frontend TraderChart ← OHLC from GET /api/market/xau/ohlc
```

**Key files:**
- `frontend/components/TraderChart.tsx` (TradingView lightweight-charts)
- `frontend/lib/chart.ts`
- `backend/app/api/market.py`
- `backend/app/services/chart_levels.py`
- `backend/app/services/trade_setup.py`

---

### 9.2 Economic Surprise Analysis

The economic surprise module quantifies how much an economic release deviated from expectations and what that means for gold.

#### Pipeline

```
News headlines (Tavily)
       │
       ▼
NewsAgent extracts: actual, forecast, previous, event_type
       │
       ▼
enrich_news_event()  →  assess_release()
       │
       ├─ surprise_delta (actual − forecast)
       ├─ surprise_direction (ABOVE / BELOW / INLINE)
       ├─ surprise_magnitude (LOW / MEDIUM / LARGE / EXTREME)
       ├─ surprise_gold_bias (BULLISH / BEARISH / NEUTRAL)
       ├─ mechanism chain (e.g. hot CPI → higher yields → bearish gold)
       └─ importance boost (LARGE → HIGH, EXTREME → CRITICAL)
       │
       ▼
Passed to synthesis as economic_surprises[]
```

#### Event-Type Thresholds

| Event Type | Medium | Large | Extreme |
|---|---|---|---|
| CPI / Core CPI / PCE | 0.1 | 0.2 | 0.3 |
| NFP | 30K | 75K | 150K |
| Fed Rate | 0.25% | 0.50% | 0.75% |
| GDP | 0.3% | 0.6% | 1.0% |
| Unemployment | 0.1% | 0.2% | 0.4% |
| Jobless Claims | 10K | 25K | 50K |

#### Gold Bias Interpretation Examples

| Surprise | Typical Gold Bias | Mechanism |
|---|---|---|
| Hot CPI (above forecast) | BEARISH | Higher inflation expectations → higher real yields → stronger USD → gold pressure |
| Weak NFP (below forecast) | BULLISH | Weaker labor → dovish Fed expectations → lower yields → gold support |
| Surprise rate cut | BULLISH | Lower opportunity cost of holding gold → USD weakness |

**File:** `backend/app/services/economic_surprise.py`  
**Tests:** `backend/tests/test_economic_surprise.py`

---

### 9.3 Chart in Trader Mode

The interactive chart is a core Trader Mode feature powered by **TradingView Lightweight Charts**.

#### Features
- Real-time OHLC candlestick data from Twelve Data
- Horizontal price lines for all trade levels
- Interval switching (5m → 1D)
- Color-coded levels (support=green, resistance=red, entry=blue, SL=orange, TP=purple)

#### Level Resolution

`chart_levels.py` ensures consistency between:
- Technical agent output
- Trade setup levels
- Chart annotation payload

If the technical agent omits levels, `build_trade_setup()` generates them from live price data.

---

### 9.4 News Weighting (Geopolitical & High-Impact Events)

News importance is determined through a **multi-factor scoring system**, not a single "war news" rule. However, geopolitical risk is explicitly included in the news agent's default focus areas.

#### Weighting Mechanisms

**1. Impact Score Formula** (`news_impact.py`):

```
impact = 0.25 × gold_relevance
       + 0.20 × event_importance
       + 0.20 × surprise_factor
       + 0.15 × magnitude
       + 0.10 × persistence
       + 0.10 × source_confidence
```

**2. Horizon Decay** — news impact diminishes over longer horizons:

| Horizon | Impact Multiplier |
|---|---|
| intraday | 0.90 |
| few_days | 0.75 |
| short_term | 0.60 |
| medium_term | 0.40 |
| long_term | 0.25 |
| ages | 0.10 |

**3. Surprise Magnitude Boost:**

| Magnitude | Surprise Factor | Importance Boost |
|---|---|---|
| LOW | 0.25 | → MEDIUM |
| MEDIUM | 0.50 | → HIGH |
| LARGE | 0.75 | → HIGH |
| EXTREME | 0.95 | → CRITICAL |

**4. Geopolitical Risk Handling:**
- News agent default focus includes `"geopolitical risk"`
- Intent router classifies geopolitics **as they relate to gold** as `RESEARCH`
- War/conflict headlines are processed through Tavily search + LLM classification
- High gold-relevance geopolitical events receive elevated `gold_relevance` scores
- Critical surprises (LARGE/EXTREME) trigger heightened conflict analysis sensitivity

**5. Agent Horizon Weights** — at intraday, news weight is 0.85 (second only to technical at 0.90), ensuring breaking headlines dominate short-term synthesis.

---

## 10. News Weighting & Impact Scoring

See Section 9.4 above for the full scoring model. Additional details:

### Importance Classification

| Score Range | Label |
|---|---|
| ≥ 0.85 | CRITICAL |
| ≥ 0.65 | HIGH |
| ≥ 0.35 | MEDIUM |
| < 0.35 | LOW |

### Tavily Budget Management

| Agent Depth | Max Tavily Searches |
|---|---|
| LIGHT | 1 |
| STANDARD | 2 |
| DEEP | 2 |

Monthly budget tracked in SQLite (`tavily_usage` table). Configurable via `TAVILY_MONTHLY_BUDGET` (default: 900).

---

## 11. Agent Conflict Analysis

Before synthesis, the system compares specialist outputs pairwise to detect agreement or contradiction.

### Conflict Types

| Type | Description |
|---|---|
| `AGREEMENT` | Same direction, similar horizon |
| `PARTIAL_AGREEMENT` | Same direction family, different confidence |
| `DIRECTION_CONFLICT` | Bullish vs bearish signals |
| `HORIZON_CONFLICT` | Same direction but different time scopes |
| `DATA_CONFLICT` | Contradictory driver narratives |

### Agent Pairs Analyzed

- News ↔ Fundamental
- News ↔ Technical
- Fundamental ↔ Technical

### Impact on Output

- **Confidence adjustment:** conflicts reduce synthesis confidence
- **Trade Mode:** severe direction conflict (>0.8 severity) → force `NO_TRADE` bias
- **Critical surprise:** LARGE/EXTREME surprises increase conflict sensitivity

**File:** `backend/app/services/agent_conflict.py`  
**Frontend:** `frontend/components/AgentConflictMatrix.tsx`

---

## 12. Frontend & User Experience

### Components

| Component | Purpose |
|---|---|
| `WelcomeScreen` | Initial landing with example queries |
| `ChatInput` | Message input with send button |
| `ChatMessage` | Rendered user/assistant messages |
| `AgentStatus` | Real-time pipeline step indicators |
| `ResultCard` | Synthesis summary with direction, confidence, drivers |
| `Sidebar` | Trade Mode toggle, new conversation |
| `TraderTicker` | Live price ticker (Trade Mode) |
| `TraderChart` | Interactive candlestick chart (Trade Mode) |
| `TraderAnalysisPanel` | Trade setup summary card (Trade Mode) |
| `AgentConflictMatrix` | Visual conflict matrix |

### User Flow

1. User opens app → conversation created (or restored from localStorage)
2. User types query (optionally enables Trade Mode)
3. Agent status panel shows live pipeline progress
4. Answer streams in real time (chunked via `answer_delta`)
5. Result card displays synthesis metadata
6. In Trade Mode: trader desk panel appears with chart and setup

---

## 13. API Reference

### Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/conversations` | Create new conversation → `{ id }` |
| `GET` | `/api/conversations/{id}` | Get conversation with message history |
| `POST` | `/api/analyze` | SSE stream — main analysis pipeline |
| `GET` | `/api/market/xau/quote` | Live XAU/USD quote |
| `GET` | `/api/market/xau/ohlc` | OHLC candlestick data |
| `GET` | `/health` | Service health + API key status |
| `GET` | `/health/openai` | OpenAI connectivity check |

### Analyze Request Body

```json
{
  "query": "What is gold doing today?",
  "conversation_id": "uuid-string",
  "trade_mode": false
}
```

### Analyze Response

Server-Sent Events stream. Each event:

```
data: {"type": "event_name", "agent": "agent_name", "message": "...", "data": {...}}
```

Final `answer_completed` event includes full answer text and synthesis metadata.

---

## 14. Data Layer & Persistence

### SQLite Database

**File:** `gold_agent.db` (configurable via `DATABASE_URL`)

### Tables

| Table | Purpose |
|---|---|
| `conversations` | Conversation metadata |
| `messages` | User/assistant message history with metadata |
| `short_term_technical_outputs` | Cached short-term TA results |
| `long_term_technical_outputs` | Cached long-term TA results |
| `tavily_usage` | Monthly Tavily API usage tracking |

### Caching Strategy

| Data | TTL | Config Key |
|---|---|---|
| XAU quote | 15s | `cache_quote_ttl` |
| OHLC 1min | 60s | `cache_ohlc_1m_ttl` |
| OHLC 15min | 300s | `cache_ohlc_15m_ttl` |
| OHLC daily | 1800s | `cache_ohlc_daily_ttl` |
| FRED series | 3600s | `cache_fred_ttl` |
| Tavily results | 1200s | `cache_tavily_ttl` |

Technical cache outputs are refreshed when classified as `STALE` by `services/freshness.py`.

---

## 15. External Integrations

### Twelve Data (Market Data)

| Data | Used By |
|---|---|
| XAU/USD live quote | Technical agents, market API, trader ticker |
| OHLC time series | Technical agents, trader chart |
| RSI, SMA, EMA, MACD, ATR | Technical analysis |
| Support/resistance calculation | Technical agents, trade setup |

### FRED (Macro Data)

| Series | Indicator |
|---|---|
| DFF | Fed Funds Rate |
| DGS2, DGS10 | Treasury yields |
| DFII5, DFII10 | Real yields (TIPS) |
| CPIAUCSL, CPILFESL | CPI |
| PCEPI, PCEPILFE | PCE |
| UNRATE | Unemployment |
| PAYEMS | Nonfarm payrolls |

### Tavily (News Search)

| Function | Purpose |
|---|---|
| `search_news_with_tavily` | Gold/XAU news headlines |
| `search_economic_releases` | Economic data with actual vs forecast |

### OpenAI (LLM)

All agents powered by GPT-4.1 family (nano for routing/answers, mini for planning/specialists/synthesis).

---

## 16. Technology Stack

### Backend

| Technology | Version / Detail | Purpose |
|---|---|---|
| Python 3 | — | Runtime |
| FastAPI | — | HTTP API + SSE |
| Uvicorn | — | ASGI server |
| Pydantic v2 | — | Schema validation |
| OpenAI Agents SDK | `openai-agents` | Multi-agent orchestration |
| aiosqlite | — | Async SQLite |
| httpx | — | HTTP client |
| tavily-python | — | News search SDK |
| pytest | — | Testing |

### Frontend

| Technology | Version / Detail | Purpose |
|---|---|---|
| Next.js | 15 | React framework (App Router) |
| React | 19 | UI library |
| TypeScript | — | Type safety |
| Tailwind CSS | — | Styling |
| lightweight-charts | TradingView | Trader mode candlestick chart |

### Infrastructure

| Tool | Purpose |
|---|---|
| SQLite | Local persistence |
| Render.com | Production deployment (`render.yaml`) |
| In-memory cache | API response TTL caching |

---

## 17. Configuration & Deployment

### Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | — | Required for all LLM agents |
| `TWELVE_DATA_API_KEY` | — | Market data |
| `FRED_API_KEY` | — | Macro data |
| `TAVILY_API_KEY` | — | News search |
| `FAST_MODEL` | `gpt-5.4-nano` | Fast path / DirectChat / legacy router |
| `MANAGER_MODEL` | `gpt-5.4` | Gold Manager (plan, review, synthesis, answer) |
| `NEWS_MODEL` | `gpt-5.4-mini` | News specialist |
| `FUNDAMENTAL_MODEL` | `gpt-5.4-mini` | Fundamental specialist |
| `TECHNICAL_MODEL` | `gpt-5.4-mini` | Technical specialist |
| `SPECIALIST_MODEL` | `gpt-5.4-mini` | Fallback when NEWS/FUNDAMENTAL/TECHNICAL unset |
| `QUERY_MODEL` | (alias) | Legacy → `FAST_MODEL` |
| `PLANNER_MODEL` | (alias) | Legacy → `MANAGER_MODEL` |
| `SYNTHESIS_MODEL` | (alias) | Legacy → `MANAGER_MODEL` |
| `ANSWER_MODEL` | (alias) | Legacy → `FAST_MODEL` |
| `MOCK_EXTERNAL_APIS` | `false` | Dev mode without API credits |
| `CORS_ORIGINS` | localhost:3000 | Allowed frontend origins |
| `NEXT_PUBLIC_API_URL` | — | Frontend → backend URL |

### Local Development

```bash
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --app-dir .

# Frontend
cd frontend
npm install
npm run dev
```

Open http://localhost:3000

### Production (Render)

Two services defined in `render.yaml`:
- **gold-agent-api** — FastAPI backend
- **gold-agent-web** — Next.js frontend

See `README.md` for deployment steps.

---

## 18. Project Directory Map

```
gold_agent/
├── README.md                          # Setup & deploy guide
├── .env.example                       # Environment template
├── render.yaml                        # Render.com blueprint
├── docs/
│   └── DOCUMENTATION.md               # This file
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI entry point
│   │   ├── config.py                  # Settings & model config
│   │   ├── api/
│   │   │   ├── analyze.py             # SSE analysis endpoint
│   │   │   ├── conversations.py       # Conversation CRUD
│   │   │   └── market.py              # XAU quote & OHLC endpoints
│   │   ├── agents/
│   │   │   ├── intent_router.py       # Intent Router agent
│   │   │   ├── direct_chat.py         # DirectChat agent
│   │   │   ├── query_understanding.py # QueryUnderstanding + GoldPlanner
│   │   │   └── specialists.py         # All specialist + synthesis + answer agents
│   │   ├── services/
│   │   │   ├── orchestrator.py        # Main pipeline orchestrator
│   │   │   ├── policy.py              # Routing & horizon overrides
│   │   │   ├── economic_surprise.py   # Economic surprise analysis
│   │   │   ├── news_impact.py         # News impact scoring
│   │   │   ├── evidence.py            # Horizon-based evidence weights
│   │   │   ├── agent_conflict.py      # Agent conflict detection
│   │   │   ├── chart_levels.py        # Chart level resolution
│   │   │   ├── trade_setup.py         # Trade setup builder
│   │   │   ├── freshness.py           # Data freshness classification
│   │   │   ├── news_fallback.py       # Tavily fallback
│   │   │   ├── fundamental_fallback.py# FRED fallback
│   │   │   └── technical_fallback.py  # Twelve Data fallback
│   │   ├── schemas/
│   │   │   ├── common.py              # Horizon, Intent, Depth enums
│   │   │   ├── routing.py             # Intent router schemas
│   │   │   ├── query.py               # Query understanding schemas
│   │   │   ├── planner.py             # Planner output schemas
│   │   │   ├── news.py / news_lite.py # News agent schemas
│   │   │   ├── fundamental.py / fundamental_lite.py
│   │   │   ├── technical.py / technical_lite.py
│   │   │   └── synthesis.py           # Synthesis output schemas
│   │   ├── tools/
│   │   │   ├── twelve_data.py         # Twelve Data API wrapper
│   │   │   ├── fred.py                # FRED API wrapper
│   │   │   ├── tavily.py              # Tavily search wrapper
│   │   │   ├── technical.py           # Local TA calculations
│   │   │   └── cache.py               # In-memory TTL cache
│   │   └── db/
│   │       ├── sqlite.py              # Database initialization
│   │       └── repositories.py        # Data access layer
│   ├── scripts/
│   │   └── userjob_test_runner.py     # 20-scenario integration tests
│   └── tests/                         # Unit & integration tests
└── frontend/
    ├── app/
    │   └── page.tsx                   # Main application page
    ├── components/
    │   ├── ChatInput.tsx              # Message input
    │   ├── ChatMessage.tsx            # Message rendering
    │   ├── AgentStatus.tsx            # Pipeline progress
    │   ├── ResultCard.tsx             # Synthesis result card
    │   ├── Sidebar.tsx                # Trade Mode toggle
    │   ├── TraderChart.tsx            # Candlestick chart
    │   ├── TraderTicker.tsx           # Live price ticker
    │   ├── TraderAnalysisPanel.tsx    # Trade setup panel
    │   ├── AgentConflictMatrix.tsx    # Conflict visualization
    │   └── WelcomeScreen.tsx          # Landing screen
    ├── lib/
    │   ├── api.ts                     # Backend SSE client
    │   └── chart.ts                   # Chart data fetching
    └── types/
        └── index.ts                   # TypeScript type definitions
```

---

## Disclaimer

This system provides **market analysis only** and is **not financial or investment advice**. Trade setups include an explicit disclaimer in the output. Users should conduct their own due diligence before making trading decisions.
