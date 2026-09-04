# Gold Research Agent — V2 Deliverables

## 1. Old architecture (summary)

Fixed sequential LLM pipeline:

`IntentRouter → QueryUnderstanding → GoldPlanner → Policy → parallel specialists → GoldSynthesis → FinalAnswer`

Many hops before any data fetch; weak multi-turn (last 8 messages as text); no true fast path; no replan; no cross-domain working memory.

## 2. New architecture (summary)

Adaptive hybrid Gold Manager:

`Gate (fast/clarify/chat) → Manager Plan → parallel Agents+Tools → Evidence Pool → Deterministic engines (Surprise, News Weight, Conflict) → Manager Review → bounded Replan → Manager Answer → STM update`

Conversation session (messages) is separate from short-term working memory (fresh data/evidence).

## 3. Files changed / added

**Added**

- `backend/app/schemas/manager.py`
- `backend/app/agents/gold_manager.py`
- `backend/app/services/manager_runtime.py`
- `backend/app/services/working_memory.py`
- `backend/app/services/gate.py`
- `backend/app/services/session.py`
- `backend/tests/test_v2_gate_and_memory.py`
- `backend/tests/test_v2_conflict_contract.py`
- `docs/V2_REGRESSION_CONTRACTS.md`
- `docs/V2_ARCHITECTURE.md` (this file)

**Updated**

- `backend/app/services/orchestrator.py` (thin V2 entry)
- `backend/app/services/policy.py` (ManagerPlan constraints)
- `backend/app/config.py` (MANAGER/FAST models, STM TTLs, replan)
- `backend/app/agents/specialists.py`, `direct_chat.py`
- `frontend/components/AgentStatus.tsx`, `frontend/app/page.tsx`
- `.env.example`, `render.yaml`

## 4. Components removed from the live path

Not invoked by `run_pipeline` anymore (files kept as legacy stubs):

- Intent Router agent
- Query Understanding agent
- Gold Planner agent
- Gold Synthesis agent
- Final Answer Generator agent
- Short/Long-term technical refresh agents (runtime)

## 5. Components added

- Gold Manager (Plan / Review / Answer agents)
- Deterministic gate (FAST / CLARIFY / CHAT / RESEARCH)
- Short-term working memory (freshness-aware)
- Conversation session adapter
- Evidence pool + parallel task executor with replan

## 6. Fast Path

Deterministic patterns (price, today’s high/low, simple RSI/SMA/EMA/MACD/ATR) → check STM → direct Twelve Data call → concise answer. Emits `fast_path` + `chat_response` so the UI does not show a full research pipeline. No Manager / specialists. Non-LLM answers are emitted as a single immediate `answer_delta` (no fake typewriter).

### Token streaming (answers)

User-facing LLM answers (DirectChat + Gold Manager Answer) use `Runner.run_streamed` and forward `ResponseTextDeltaEvent` tokens as SSE `answer_delta` events in real time. Structured synthesis still runs non-streaming first so `synthesis_completed` can update the ResultCard / chart before prose streams.

## 7. Clarification

Gate (and Manager plan) ask only when missing info would change scope (e.g. bare “Analyze gold”). Trade Mode supplies intraday defaults — no nag. Clarification is stored as a normal assistant turn; the next user message continues the conversation.

## 8. Multi-turn context

Messages remain in SQLite. Manager receives recent conversation turns plus optional `last_thesis` from STM so follow-ups (“biggest downside risks?”) reuse prior analysis without restarting from zero unless data is stale.

## 9. Short-term memory

`working_memory.py`: in-process TTL cache + SQLite `api_cache` persistence. Stores quotes, indicators, specialist outputs, thesis. Separate from chat history.

## 10. Freshness / TTL policy

| Kind | Default TTL |
|---|---|
| Quote | 15s |
| Intraday OHLC | 60s |
| Daily OHLC | 1800s |
| Indicators | 300s |
| FRED / macro | 3600s |
| News research | 1200s |
| Economic release | 6h |
| Specialist analysis | 15m (5m in trade mode for technical) |
| Thesis | 30m |

Configurable via `STM_*` settings in `config.py`.

## 11. Parallel execution

Independent Manager tasks run in waves via `asyncio.gather`. `depends_on` keeps true dependencies sequential. Timing logs (`timing …`, `parallel wave size=…`) support verifying overlap.

## 12. Replanning

After deterministic engines, Manager Review may request missing work. Bounded by `MAX_REPLAN_ROUNDS` (default 2).

## 13. Model strategy

| Role | Env | Default |
|---|---|---|
| Fast / chat / legacy router | `FAST_MODEL` | `gpt-5.4-nano` |
| Gold Manager | `MANAGER_MODEL` | `gpt-5.4` |
| News specialist | `NEWS_MODEL` | `gpt-5.4-mini` |
| Fundamental specialist | `FUNDAMENTAL_MODEL` | `gpt-5.4-mini` |
| Technical specialist | `TECHNICAL_MODEL` | `gpt-5.4-mini` |
| Shared specialist fallback | `SPECIALIST_MODEL` | `gpt-5.4-mini` |

Legacy `QUERY_MODEL` / `PLANNER_MODEL` / `SYNTHESIS_MODEL` / `ANSWER_MODEL` still accepted as aliases.
When `NEWS_MODEL` / `FUNDAMENTAL_MODEL` / `TECHNICAL_MODEL` are unset, they inherit `SPECIALIST_MODEL`.

## 14. New environment variables

- `FAST_MODEL`, `MANAGER_MODEL`, `NEWS_MODEL`, `FUNDAMENTAL_MODEL`, `TECHNICAL_MODEL`, `MAX_REPLAN_ROUNDS`
- STM TTLs available in code settings (`stm_quote_ttl`, etc.)

## 15. Migration notes

1. Deploy backend with new env vars (Render template updated).
2. No DB migration required (`api_cache` table already existed).
3. Frontend status pills changed; old SSE names still partially mapped.
4. `SynthesisOutput` on `synthesis_completed` remains the UI contract.

## 16. Run locally

```bash
# backend
cd backend
.\.venv\Scripts\activate   # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# frontend
cd frontend
npm install
npm run dev
```

Copy `.env.example` → `.env` and fill API keys.

## 17. How to test

```bash
cd backend
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

Behavioral unit coverage: fast path, clarification, research complexity, STM reuse/stale, conflict contract, ManagerPlan policy, replan bound.

Manual E2E: Tests 1–10 from the V2 spec (price, follow-up, clarify, complex research, memory, stale, conflict, trader mode, provider failure, parallelism logs).

## 18. Render deployment

Update service env vars to include `MANAGER_MODEL`, `FAST_MODEL`, `NEWS_MODEL`, `FUNDAMENTAL_MODEL`, `TECHNICAL_MODEL`, `MAX_REPLAN_ROUNDS` (see `render.yaml`). No new services. SQLite on free disk remains ephemeral across redeploys (same as before).

## 19. Known limitations

- Manager Answer is a single structured LLM call; very large evidence blobs may truncate context.
- STM specialist reuse may skip fresh news within TTL — intentional for cost; force refresh by waiting out TTL or new conversation.
- Clarification is heuristic; edge-case ambiguous queries may still proceed or over-ask.
- Legacy agent modules still exist as stubs (not on hot path).
- Long-term / vector memory intentionally not implemented.

## 20. Recommended future improvements

- Native OpenAI Agents SDK Session compaction for very long chats
- Long-term user memory (separate project)
- Stronger provider failover / alternate data sources on replan
- Streaming token deltas from Manager Answer — implemented via `Runner.run_streamed`
- Remove legacy agent stub files once confident
- Optional bump to newer OpenAI model IDs after SDK compatibility check
