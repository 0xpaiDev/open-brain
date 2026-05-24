# Chat Tools Library — Design Spec

**Date:** 2026-05-23  
**Status:** approved-design / pending-implementation-plan  
**Source brief:** `docs/backlog/2026-05-23-chat-tools-brief.md`

---

## Context

The web chat at 0xpai.com is RAG + synthesis only (`src/api/routes/chat.py`). No tool-use loop, no multi-step agent behavior. The user wants the chat to manipulate data via natural language: mark todos done, create tasks, defer memories, query by structured filters, etc.

This spec defines the v1 implementation: 7 tools (full todo domain + memory reads), a hybrid intent classifier, an agentic tool-use loop powered by Sonnet, full transcript logging, and a frontend toggle.

---

## Decisions locked in brainstorm

| Axis | Decision |
|---|---|
| Tool surface | Narrow typed tools (one tool per action) |
| v1 scope | Full todo domain (5 tools) + memory reads (2 tools) |
| Memory writes | Deferred to v2 |
| Intent routing | Hybrid: regex fast path → Haiku fallback |
| Tool-use model | Always Sonnet (`claude-sonnet-4-6`), regardless of user's selected model |
| Regular chat model | User's selected model (unchanged) |
| SQL access | Constrained DSL only (filter objects, not raw SQL) |
| Auth | `user_id` from request session, never from model args |
| Tool discovery | All tools every turn (v1); revisit at 10+ tools |
| Confirmation gates | None needed in v1 (all writes are reversible by another tool call) |
| Module structure | Domain split: `memory_tools.py` + `todo_tools.py` + thin `chat_tools.py` aggregator |
| Observability | `chat_logs` DB table per turn (full JSONB transcript) |
| Frontend toggle | `tools_enabled` request param; frontend toggle near model select; persisted in localStorage |
| Toggle test | Backend unit test only (no Vitest frontend test) |

---

## V1 Tool List (7 tools)

### Memory reads

**`search_memory_filtered`**
```
Input:  query: str (required)
        type?: str           # learning | decision | todo | daily_pulse | ...
        date_from?: str      # ISO date
        date_to?: str        # ISO date
        project?: str
        importance_min?: float
Output: list[{id, content, type, created_at, importance_score}]
Wraps:  new memory_service.search_memory_filtered() → src/retrieval/search.py
```

**`expand_memory`**
```
Input:  memory_id: str (UUID)
Output: {content, raw_text, neighbors[], metadata}
Wraps:  existing memory_service.expand_memory()
Note:   plain DB lookup by ID — no vector search. Intended as follow-up to search_memory_filtered.
```

### Todo reads

**`list_todos`**
```
Input:  status?: str         # open | done | cancelled
        due_before?: str     # ISO date
        project?: str
Output: list[{id, description, status, priority, due_date, project}]
Wraps:  new todo_service.list_todos()
```

### Todo writes (all reversible by another tool call)

**`create_todo`**
```
Input:  description: str (required)
        priority?: str       # high | normal | low (default: normal)
        due_date?: str       # ISO date
        project?: str
Output: {id, description}
Wraps:  todo_service.create_todo()
```

**`complete_todo`**
```
Input:  todo_id: str (UUID)
        reason?: str
Output: confirmation text with todo description
Wraps:  todo_service.update_todo(todo, status="done", reason=reason)
```

**`defer_todo`**
```
Input:  todo_id: str (UUID)
        until_date: str (ISO date, required)
        reason?: str
Output: confirmation text
Wraps:  todo_service.update_todo(todo, due_date=until_date, reason=reason)
```

**`edit_todo`**
```
Input:  todo_id: str (UUID)
        description?: str
        priority?: str
        project?: str
Output: confirmation with changed fields
Wraps:  todo_service.update_todo(todo, ...)
```

---

## Architecture

Three PRs in sequence:

### PR 1 — Foundation + Logging (no tools yet)

**New files:**
- `src/llm/intent_classifier.py` — hybrid classifier (regex → Haiku fallback)
- `src/llm/tool_agent.py` — Sonnet tool-use loop
- `src/api/services/chat_tools.py` — thin aggregator: `ALL_TOOLS` list + dispatch table
- `alembic/versions/<next>_chat_logs.py` — migration for `chat_logs` table (check `ls alembic/versions/` for latest number before creating)

**Modified files:**
- `src/llm/client.py` — add `_messages_create(messages, tools, model, max_tokens)` raw method used by the loop (does not modify `complete_with_history`)
- `src/api/routes/chat.py` — insert intent classification + tool routing; add `tools_enabled` param

### PR 2 — Domain tools

**New files:**
- `src/api/services/memory_tools.py` — tool handlers + Anthropic tool schemas for memory tools
- `src/api/services/todo_tools.py` — tool handlers + schemas for todo tools

**Modified files:**
- `src/api/services/memory_service.py` — add `search_memory_filtered(session, *, query, type?, date_from?, date_to?, project?, importance_min?)`
- `src/api/services/todo_service.py` — add `list_todos(session, *, status?, due_before?, project?)`
- `src/api/services/chat_tools.py` — wire domain tool modules in; complete dispatch table

### PR 3 — Frontend toggle

**Modified files:**
- `web/` — tools on/off toggle near model select in chat UI; persists in localStorage; sends `tools_enabled` param on every chat request

---

## Data Flow

```
Request arrives
  ↓
tools_enabled check (from request param)
  │
  NO → complete_with_history, user's selected model (unchanged RAG path)
  │
  YES
  ↓
[Regex classifier]
  Pattern examples:
    complete_todo:  /mark.*(done|complete)|finish|check\s*off/i
    list_todos:     /show.*(todos|tasks)|what.*(on my list|open tasks)/i
    create_todo:    /create|add.*(task|todo)|remind me to/i
    defer_todo:     /defer|snooze|push back|postpone/i
    edit_todo:      /rename|change.*todo|update.*task/i
    search_memory:  /search.*mem|find.*learn|look up.*decision/i
    expand_memory:  /expand|show full|more detail.*memory/i
  │
  MATCH → intent = tool_name
  │
  NO MATCH
    ↓
  [Haiku classifier]
    System prompt: intent→tool table (full list)
    Output: {"tool": "complete_todo"} | {"tool": null}
  │
  MATCH → intent = tool_name
  │
  null → no tool detected → RAG path with user's selected model
  │
TOOL PATH: intent != null
  ↓
run_tool_loop(
  model="claude-sonnet-4-6",
  system_prompt=<existing RAG system prompt>,
  messages=messages_for_llm,
  tools=ALL_TOOLS,
  max_tokens=2048,
  session=db,
  user_id=current_user.id,
)
  Loop (max 10 iterations):
    client._messages_create(tools=ALL_TOOLS, ...)
    if stop_reason == "end_turn": break
    dispatch each tool_use block:
      handler(session, user_id, **model_args) → result | ToolError
    append assistant(tool_use blocks) + user(tool_result blocks) to local messages
  if iteration_cap reached: return "I wasn't able to complete that in one turn"
  ↓
Write chat_logs row (full transcript)
  ↓
Return final text
```

---

## Error Handling

| Scenario | Behavior |
|---|---|
| Tool handler raises (invalid UUID, not found, validation error) | Caught at dispatch, returned as `tool_result {is_error: true, content: "..."}`. Model surfaces to user naturally. |
| LLM call fails (timeout, APIError) | Propagates as `ExtractionFailed`, same as today. Route returns 500. |
| Iteration cap (10) reached | Graceful text response: "I wasn't able to complete that in one turn." |
| Tool A succeeds, tool B fails (parallel tool calls) | Both results returned; model decides response. No rollback — each handler commits its own transaction. |
| Intent classifier Haiku call fails | Log warning, fall back to RAG path (no tool-use). |

---

## Auth / Scoping Checklist

Every tool handler receives `user_id: uuid.UUID` from the request session — never from the model's tool call args. Handlers for mutating tools (`complete_todo`, `defer_todo`, `edit_todo`) fetch the target record with a `WHERE id = :id` check; if not found, raise `ToolError("not found")`.

(The app is currently single-user; `user_id` is passed for future-proofing. The service layer is the security boundary, not the LLM.)

---

## chat_logs Table

```sql
CREATE TABLE chat_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMPTZ DEFAULT now(),
  user_message TEXT NOT NULL,
  tools_enabled BOOLEAN NOT NULL,
  intent_tool VARCHAR(64),          -- null if no tool intent detected
  intent_method VARCHAR(16),        -- "regex" | "haiku" | "none"
  llm_calls JSONB,                  -- [{model, turn_index, input_messages, response, stop_reason, duration_ms}]
  tool_calls JSONB,                 -- [{tool_name, args, result, duration_ms, is_error}]
  response_text TEXT,
  model_used VARCHAR(64),
  duration_ms INTEGER
);
ALTER TABLE chat_logs ENABLE ROW LEVEL SECURITY;
```

Future log page: `GET /v1/chat/logs?limit=50&offset=0` — rows ordered by `created_at DESC`.

---

## New Service Methods

**`memory_service.search_memory_filtered`**
```python
async def search_memory_filtered(
    session: AsyncSession,
    *,
    query: str,
    type: str | None = None,
    date_from: str | None = None,   # ISO date string
    date_to: str | None = None,
    project: str | None = None,
    importance_min: float | None = None,
    limit: int = 10,
) -> list[MemoryItem]: ...
```
Calls `src/retrieval/search.py` hybrid search, then applies post-filters for type/date/project/importance_min.

**`todo_service.list_todos`**
```python
async def list_todos(
    session: AsyncSession,
    *,
    status: str | None = None,
    due_before: str | None = None,  # ISO date string
    project: str | None = None,
) -> list[TodoItem]: ...
```

---

## Testing Plan

| Area | Approach |
|---|---|
| Intent classifier — regex | Unit tests: sample phrases per tool, assert correct tool name (or None) |
| Intent classifier — Haiku | Unit tests with mocked Haiku response; real-API integration test marked `@pytest.mark.slow` |
| Tool handlers (memory + todo) | Integration tests against real Postgres (per CLAUDE.md footgun rules); call handler directly with real session; assert DB state |
| Tool dispatch loop | Unit tests: mock `_messages_create` to return canned tool_use → tool_result sequences; assert final text and iteration count |
| Chat route | Integration test: POST `/v1/chat` with `tools_enabled=true`; mock Anthropic; assert handler invoked with correct args and `chat_logs` row written |
| `tools_enabled` param | Backend unit test: route with `tools_enabled=false` never calls intent classifier |

Frontend toggle: covered by the backend param unit test above; no Vitest test.

All DB-touching tests use real Postgres (not SQLite) per project policy.

---

## Files Reference

| File | Role |
|---|---|
| `src/api/routes/chat.py` | Route: add `tools_enabled` param, intent routing, model guard |
| `src/llm/client.py` | Add `_messages_create` raw method |
| `src/llm/intent_classifier.py` | NEW: regex + Haiku hybrid classifier |
| `src/llm/tool_agent.py` | NEW: Sonnet tool-use loop |
| `src/api/services/chat_tools.py` | NEW: aggregator + dispatch table |
| `src/api/services/memory_tools.py` | NEW: memory tool handlers + schemas |
| `src/api/services/todo_tools.py` | NEW: todo tool handlers + schemas |
| `src/api/services/memory_service.py` | Add `search_memory_filtered` |
| `src/api/services/todo_service.py` | Add `list_todos` |
| `alembic/versions/<next>_chat_logs.py` | NEW: migration for chat_logs table (verify latest revision first) |
| `src/llm/prompts.py` | Add intent classifier system prompt (intent→tool table) |
| `web/` | PR 3: frontend tools toggle |

---

## Out of Scope (v1)

- Memory writes (defer_memory, adjust_importance, supersede_memory) — v2
- Pulse tools (get_morning_pulse, mark_pulse_item_done) — v2
- Log page UI in the dashboard — future PR after logging is in prod
- Server-side agent runtime (Hermes-style) — separate workstream
- Undo system — separate workstream
