# V2 Regression Contracts (Freeze)

Do not break these contracts during the Gold Manager V2 refactor.

## SSE events the frontend depends on

| Event | Purpose |
|---|---|
| `chat_response` | Hide research status UI (direct chat / fast path) |
| `check_completed.data.agents` | `{ news, fundamental, technical }` enable flags |
| `synthesis_completed` | Full `SynthesisOutput` JSON for ResultCard / chart / conflicts |
| `answer_delta` / `answer_completed` | Streamed answer text |
| `news_agent_*` / `fundamental_agent_*` / `technical_agent_*` | Specialist status pills |
| `error` | Surface failures without hanging UI |

New V2 events (additive): `memory_check_*`, `review_*`, `replan_*`, `fast_path`.

## SynthesisOutput UI fields

Required for ResultCard / AgentConflictMatrix / TraderChart:

- `overall_direction`, `confidence`, `horizon`
- `key_drivers`, `key_risks`, `agreements`, `contradictions`
- `base_case` / `bull_case` / `bear_case`
- `agent_conflicts` (relations, confidence_adjustment, dominant_conflict)
- `trade_setup` (bias LONG/SHORT/NO_TRADE, entry_zone, stop_loss, take_profit, risk_reward, invalidation)
- `chart_annotations` (levels, trade_setup, default_interval)

## API request shape

`POST /api/analyze` body: `{ query, conversation_id, trade_mode }`

## Persistence

- `conversations` / `messages` tables remain source of truth for chat UI
- Assistant research messages may include `synthesis` + `specialist_outputs` in metadata
