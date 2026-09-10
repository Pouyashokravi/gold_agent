# Gold Research Agent — V2 Architecture

## 1. Old architecture (summary)

Fixed sequential LLM pipeline:

`IntentRouter → QueryUnderstanding → GoldPlanner → Policy → parallel specialists → GoldSynthesis → FinalAnswer`

## 2. Current architecture (summary)

```text
POST /api/analyze
  → run_pipeline()
  → run_v2_pipeline()
  → Conversation Gate LLM (context: rolling summary + recent messages + pending clarify + current message)
       ├─ GENERAL_CHAT / OFF_TOPIC → DirectChat
       ├─ CLARIFY → clarification question (persisted with rich metadata)
       ├─ FAST → direct provider tools (Twelve Data / API cache) — no Manager
       └─ STANDARD / RESEARCH → Gold Manager Plan → parallel Agents+Tools
            → Evidence Pool → Surprise / Conflict engines → Review → bounded Replan
            → Synthesis → Answer
  → Persist user + assistant messages
  → Schedule rolling-summary maintenance (non-blocking)
```

Conversation memory is scoped exclusively by `conversation_id` (no user profiles).

## 3. Conversation Memory

Three layers, all per conversation:

1. **Full Message History** — SQLite `messages` table (never truncated by summarization); message IDs returned from `add_message`.
2. **Recent Messages** — up to 20 verbatim turns for the Gate / Manager.
3. **Rolling Summary** — `conversation_memories` table with structured JSON (`main_topic`, goals, decisions, constraints, open/resolved questions, `current_state`).

### Summary schedule

- Trigger: `unsummarized_message_count >= 20`
- Incremental: previous summary + oldest ≤20 new messages → updated summary
- Ordering: persist messages and complete the user response first; summarization is fire-and-forget maintenance
- Concurrency: per-conversation `asyncio.Lock` + SQLite optimistic CAS on `last_summarized_message_id` (stale writes discarded and retried)
- Failures: log only; cursor unchanged; retry later

## 4. Conversation Gate

LLM agent with structured `ConversationGateOutput`. Owns routing, clarification, FAST tool selection, and `normalized_query` for the Manager.

- Primary path: LLM Gate (not keyword/regex)
- Emergency fallback only: deterministic `classify_gate` (explicitly logged as `emergency_fallback:…`)
- Clarification metadata: `action`, goal, resolved/missing fields, turn count, gate decision snippet
- Max consecutive clarifications: `MAX_CLARIFICATION_TURNS` (default 3)
- Does not ask by default about entry / stop-loss / take-profit / account or position size

FAST kinds allowlist: `quote`, `high_low`, `rsi`, `sma`, `ema`, `macd`, `atr`.

## 5. Gold Manager

Runs only for `STANDARD` and `RESEARCH` after Gate validation.

- STANDARD: usually one specialist or a small focused tool set
- RESEARCH: multiple domains / broader evidence / replanning
- No primary clarification, FAST detection, or prior-thesis STM reuse
- Deterministic safety / event-impact policies retained

## 6. Removed: Short-Term Working Memory

Deleted `working_memory.py` and all STM reuse (quotes, indicators, specialists, thesis, `memory_hits`, `use_prior_thesis`, `EvidenceCategory.MEMORY`, `memory_check_*` SSE).

**Kept:** in-process provider API cache (`app/tools/cache.py`, `CACHE_*_TTL`). New DB installs no longer create `api_cache` (legacy tables on old DBs are left alone; not dropped).

## 7. Files (key)

**Added**

- `backend/app/schemas/conversation_gate.py`
- `backend/app/schemas/conversation_memory.py`
- `backend/app/agents/conversation_gate.py`
- `backend/app/agents/conversation_summarizer.py`
- `backend/app/services/conversation_gate.py`
- `backend/app/services/conversation_memory.py`

**Updated**

- `manager_runtime.py`, `session.py`, `gate.py` (emergency only), `gold_manager.py`, `policy.py`, `config.py`, `repositories.py`, `sqlite.py`
- `docs/V2_ARCHITECTURE.md`, `.env.example`, tests

**Removed**

- `backend/app/services/working_memory.py`

## 8. Components intentionally retained (legacy)

- `classify_gate` in `gate.py` — emergency fallback only when Gate LLM fails
- Intent Router / Query Understanding stubs — outside hot path
- Existing `api_cache` rows on old databases — unused; not auto-dropped

## 9. Model strategy

| Role | Env | Default |
|---|---|---|
| Fast / chat / Gate / Summarizer default | `FAST_MODEL` | `gpt-5.4-nano` |
| Conversation Gate override | `CONVERSATION_GATE_MODEL` | → `FAST_MODEL` |
| Conversation Summarizer override | `CONVERSATION_SUMMARY_MODEL` | → `FAST_MODEL` |
| Gold Manager | `MANAGER_MODEL` | `gpt-5.4` |
| Specialists | `NEWS_MODEL` / `FUNDAMENTAL_MODEL` / `TECHNICAL_MODEL` | `gpt-5.4-mini` |

## 10. SSE / API contract

- Endpoint: `POST /api/analyze` with `query`, `conversation_id`, `trade_mode`
- SSE streaming preserved (`understanding_*`, `fast_path`, `planning_*`, `answer_*`, …)
- `memory_check_*` events are no longer emitted (frontend mapping may remain inert)

## 11. How to test

```bash
cd backend
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

Coverage includes Gate routing (mocked LLM), FAST vs Manager, clarification multi-turn, summarizer CAS/batches, conversation isolation, provider cache without STM, SSE contract.
