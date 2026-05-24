---
status: ready
created: 2026-05-23
---

# Chat Tools Library

## Context

The web chat at 0xpai.com is RAG + synthesis only (`src/api/routes/chat.py`). No tool-use loop, no multi-step agent behavior. The user wants the chat to manipulate data via natural language: mark todos done, create tasks, defer memories, query by structured filters, etc.

This spec defines the v1 implementation: 7 tools (full todo domain + memory reads), a hybrid intent classifier, an agentic tool-use loop powered by Sonnet, full transcript logging, and a frontend toggle.

---

## Decisions

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

---

## Plan

### File Map

**PR 1 — Foundation + Logging**
| File | Action | Purpose |
|---|---|---|
| `src/core/models.py` | Modify | Add `ChatLog` ORM model |
| `alembic/versions/0023_chat_logs.py` | Create | Migration for `chat_logs` table |
| `src/llm/client.py` | Modify | Add `_messages_create()` raw method |
| `src/llm/intent_classifier.py` | Create | Regex + Haiku hybrid classifier |
| `src/llm/tool_agent.py` | Create | Sonnet tool-use loop + log writer |
| `src/api/services/chat_tools.py` | Create | Tool aggregator + dispatch table (empty in PR1) |
| `src/api/routes/chat.py` | Modify | Add `tools_enabled` param + intent routing |
| `tests/test_intent_classifier.py` | Create | Unit tests for intent classifier |
| `tests/test_tool_agent.py` | Create | Unit tests for tool-use loop |
| `tests/test_chat.py` | Modify | Add tests for tools_enabled routing |

**PR 2 — Domain Tools**
| File | Action | Purpose |
|---|---|---|
| `src/api/services/memory_service.py` | Modify | Add `search_memory_filtered()` |
| `src/api/services/todo_service.py` | Modify | Add `list_todos()` |
| `src/api/services/memory_tools.py` | Create | Memory tool schemas + handlers |
| `src/api/services/todo_tools.py` | Create | Todo tool schemas + handlers |
| `src/api/services/chat_tools.py` | Modify | Wire domain tools into dispatch table |
| `tests/test_memory_tools.py` | Create | Integration tests for memory tool handlers |
| `tests/test_todo_tools.py` | Create | Integration tests for todo tool handlers |

**PR 3 — Frontend Toggle**
| File | Action | Purpose |
|---|---|---|
| `web/components/chat/ToolsToggle.tsx` | Create | Toggle component |
| `web/app/chat/page.tsx` | Modify | Wire toggle + send `tools_enabled` param |

---

### Task 1: ChatLog model + migration

**Files:** `src/core/models.py`, `alembic/versions/0023_chat_logs.py`

- [ ] **Step 1.1: Verify the latest migration number**

```bash
ls alembic/versions/ | sort | tail -3
```

Expected: `0022_drop_pulse_notes.py` is the latest. Use `0023` for the new migration. If there are newer ones, adjust.

- [ ] **Step 1.2: Add `ChatLog` model to `src/core/models.py`**

Find the end of the models file (before or after `TodoHistory`). Add:

```python
class ChatLog(Base):
    __tablename__ = "chat_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    tools_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    intent_tool: Mapped[str | None] = mapped_column(String(64), nullable=True)
    intent_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    llm_calls: Mapped[dict | None] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), nullable=True
    )
    tool_calls: Mapped[dict | None] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), nullable=True
    )
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

Check what's already imported at the top of `models.py`. You need: `JSONB, JSON, Boolean, Integer, String, Text, DateTime, func, UUID, Mapped, mapped_column, Base`. Add any missing imports. `JSONB` comes from `sqlalchemy.dialects.postgresql`. `JSON` comes from `sqlalchemy`.

- [ ] **Step 1.3: Create and apply the Alembic migration**

```bash
alembic revision --autogenerate -m "add_chat_logs_table"
```

Then rename the generated file to `0023_chat_logs.py`. Open it and verify the `upgrade()` function includes:
- `CREATE TABLE chat_logs` with all columns
- `ALTER TABLE chat_logs ENABLE ROW LEVEL SECURITY` — add this manually

The final `upgrade()` should end with:
```python
op.execute("ALTER TABLE chat_logs ENABLE ROW LEVEL SECURITY")
```

And `downgrade()`:
```python
op.drop_table("chat_logs")
```

Then apply:
```bash
alembic upgrade head
```

Expected: `Running upgrade ... -> 0023...`

- [ ] **Step 1.4: Write a test that verifies ChatLog can be written and queried**

In `tests/test_chat_logs_model.py`:

```python
import pytest
from sqlalchemy import select
from src.core.models import ChatLog

@pytest.mark.asyncio
async def test_chat_log_can_be_created(async_session):
    log = ChatLog(
        user_message="show my todos",
        tools_enabled=True,
        intent_tool="list_todos",
        intent_method="regex",
        llm_calls=[{"turn_index": 0, "model": "claude-sonnet-4-6", "stop_reason": "end_turn"}],
        tool_calls=[{"tool_name": "list_todos", "args": {}, "result": "[]", "duration_ms": 5, "is_error": False}],
        response_text="You have no open todos.",
        model_used="claude-sonnet-4-6",
        duration_ms=250,
    )
    async_session.add(log)
    await async_session.commit()
    await async_session.refresh(log)

    result = await async_session.execute(select(ChatLog).where(ChatLog.id == log.id))
    fetched = result.scalar_one()
    assert fetched.intent_tool == "list_todos"
    assert fetched.llm_calls[0]["stop_reason"] == "end_turn"
```

- [ ] **Step 1.5: Run the test** — Expected: PASS

```bash
pytest tests/test_chat_logs_model.py -v
```

- [ ] **Step 1.6: Commit**

```bash
git add src/core/models.py alembic/versions/0023_chat_logs.py tests/test_chat_logs_model.py
git commit -m "feat(chat): add ChatLog model and migration for transcript logging"
```

---

### Task 2: `client._messages_create()` raw method

**Files:** `src/llm/client.py`

- [ ] **Step 2.1: Write a failing test** — In `tests/test_tool_agent.py`:

```python
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

@pytest.mark.asyncio
async def test_messages_create_returns_message_object(set_test_env):
    from src.llm.client import AnthropicClient

    fake_response = MagicMock()
    fake_response.stop_reason = "end_turn"
    fake_response.content = [MagicMock(type="text", text="Hello")]

    with patch("anthropic.Anthropic") as MockAnthropic:
        instance = MockAnthropic.return_value
        instance.messages.create.return_value = fake_response

        client = AnthropicClient(api_key="test-key", model="claude-haiku-4-5-20251001")
        result = await client._messages_create(
            messages=[{"role": "user", "content": "hello"}],
            system="You are helpful.",
            tools=[],
            model="claude-sonnet-4-6",
            max_tokens=100,
        )

    assert result.stop_reason == "end_turn"
    assert result.content[0].text == "Hello"
```

- [ ] **Step 2.2: Run to verify it fails** — Expected: `AnthropicClient has no attribute '_messages_create'`

- [ ] **Step 2.3: Add `_messages_create` to `src/llm/client.py`** — After `complete_with_history()`:

```python
async def _messages_create(
    self,
    *,
    messages: list[dict],
    system: str,
    tools: list[dict],
    model: str,
    max_tokens: int = 2048,
):
    import anthropic as _anthropic

    def _call():
        return self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_call),
            timeout=_LLM_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        logger.error("_messages_create_timeout", model=model)
        raise ExtractionFailed("LLM tool-use call timed out") from exc
    except _anthropic.APIError as exc:
        logger.error("_messages_create_api_error", status=exc.status_code)
        raise ExtractionFailed(f"Anthropic API error: {exc.status_code}") from exc
    except Exception as exc:
        logger.error("_messages_create_error", error=str(exc))
        raise ExtractionFailed(f"Unexpected LLM error: {exc}") from exc
```

`_LLM_TIMEOUT_SECONDS`, `asyncio`, `logger`, `ExtractionFailed` are already available in the file.

- [ ] **Step 2.4: Run the test again** — Expected: PASS

- [ ] **Step 2.5: Commit**

```bash
git add src/llm/client.py tests/test_tool_agent.py
git commit -m "feat(llm): add _messages_create raw method for tool-use loop"
```

---

### Task 3: Intent classifier — regex fast path

**Files:** `src/llm/intent_classifier.py`, `tests/test_intent_classifier.py`

- [ ] **Step 3.1: Write failing tests** — Create `tests/test_intent_classifier.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.parametrize("message,expected_tool", [
    ("mark that task as done", "complete_todo"),
    ("check off the gym todo", "complete_todo"),
    ("I finished the report", "complete_todo"),
    ("show my todos", "list_todos"),
    ("what's on my list", "list_todos"),
    ("list open tasks", "list_todos"),
    ("create a task: buy milk", "create_todo"),
    ("add a todo for the meeting", "create_todo"),
    ("remind me to call Alice", "create_todo"),
    ("defer that task", "defer_todo"),
    ("snooze the report until Friday", "defer_todo"),
    ("postpone the gym todo", "defer_todo"),
    ("rename the task to 'buy groceries'", "edit_todo"),
    ("change the todo description", "edit_todo"),
    ("search my memories about auth", "search_memory_filtered"),
    ("find learnings from last week", "search_memory_filtered"),
    ("expand that memory item", "expand_memory"),
    ("show full content of the memory", "expand_memory"),
    ("what is the meaning of life?", None),
    ("summarize my week", None),
    ("how are you?", None),
])
@pytest.mark.asyncio
async def test_classify_intent_regex(message, expected_tool):
    from src.llm.intent_classifier import classify_intent
    with patch("src.llm.intent_classifier._haiku_classify") as mock_haiku:
        result, method = await classify_intent(message)
    assert result == expected_tool
    if expected_tool is not None:
        assert method == "regex"
        mock_haiku.assert_not_called()
```

- [ ] **Step 3.2: Run to verify it fails** — Expected: `ModuleNotFoundError: No module named 'src.llm.intent_classifier'`

- [ ] **Step 3.3: Create `src/llm/intent_classifier.py`**

```python
"""Hybrid intent classifier for chat tool routing.

Fast path: regex patterns. Slow path: Haiku LLM call if no regex match.
Returns (tool_name | None, method: "regex" | "haiku" | "none").
"""
from __future__ import annotations

import json
import re

import structlog

logger = structlog.get_logger(__name__)

_TOOL_PATTERNS: dict[str, re.Pattern] = {
    "complete_todo": re.compile(
        r"mark.*(done|complete|finished)|check\s*off|finish(ed)?.*(task|todo|it)|i finished",
        re.IGNORECASE,
    ),
    "list_todos": re.compile(
        r"show.*(todos|tasks|my list|open)|what.*(on my list|open tasks|my todos)|list.*(tasks|todos)",
        re.IGNORECASE,
    ),
    "create_todo": re.compile(
        r"(create|add|new).*(task|todo|reminder)|remind me to|add.*reminder",
        re.IGNORECASE,
    ),
    "defer_todo": re.compile(
        r"\bdefer\b|\bsnooze\b|push\s*back|postpone|reschedule",
        re.IGNORECASE,
    ),
    "edit_todo": re.compile(
        r"rename.*(task|todo)|change.*(task|todo|description)|update.*(task|todo)|edit.*(task|todo)",
        re.IGNORECASE,
    ),
    "search_memory_filtered": re.compile(
        r"search.*(mem|learn|decision|note)|find.*(learn|mem|decision)|look up.*(mem|decision|learn)",
        re.IGNORECASE,
    ),
    "expand_memory": re.compile(
        r"expand.*(memory|mem)|show full|more detail.*(memory|mem)|full content",
        re.IGNORECASE,
    ),
}

_INTENT_SYSTEM_PROMPT = """\
You are an intent classifier. Given a user message, identify which tool (if any) the user needs.

Tools and their intents:
- complete_todo: mark a todo/task as done or complete
- list_todos: show, list, or view todos/tasks
- create_todo: create, add, or set a new todo/task/reminder
- defer_todo: defer, snooze, postpone, or push back a todo
- edit_todo: rename, update, or change a todo description/priority/project
- search_memory_filtered: search, find, or look up memories/learnings/decisions
- expand_memory: get the full content of a specific memory item

Respond with JSON only. Examples:
{"tool": "complete_todo"}
{"tool": null}"""


async def _haiku_classify(message: str) -> str | None:
    from src.llm.client import anthropic_client

    if anthropic_client is None:
        return None

    try:
        raw = await anthropic_client.complete_with_history(
            system_prompt=_INTENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": message}],
            model="claude-haiku-4-5-20251001",
            max_tokens=30,
        )
        data = json.loads(raw.strip())
        return data.get("tool") or None
    except Exception:
        logger.warning("intent_classifier_haiku_failed", message=message[:80])
        return None


async def classify_intent(message: str) -> tuple[str | None, str]:
    for tool_name, pattern in _TOOL_PATTERNS.items():
        if pattern.search(message):
            return tool_name, "regex"

    tool = await _haiku_classify(message)
    if tool is not None:
        return tool, "haiku"

    return None, "none"
```

- [ ] **Step 3.4: Run the tests** — Expected: All parametrized tests PASS

```bash
pytest tests/test_intent_classifier.py -v
```

- [ ] **Step 3.5: Commit**

```bash
git add src/llm/intent_classifier.py tests/test_intent_classifier.py
git commit -m "feat(llm): add hybrid intent classifier (regex + Haiku fallback)"
```

---

### Task 4: Intent classifier — Haiku fallback tests

**Files:** `tests/test_intent_classifier.py`

- [ ] **Step 4.1: Append Haiku fallback tests to `tests/test_intent_classifier.py`**

```python
@pytest.mark.asyncio
async def test_classify_intent_haiku_fallback_detects_tool():
    from src.llm.intent_classifier import classify_intent

    with patch("src.llm.intent_classifier._haiku_classify", new=AsyncMock(return_value="list_todos")) as mock:
        result, method = await classify_intent("could you pull up what I've got going on?")

    assert result == "list_todos"
    assert method == "haiku"
    mock.assert_called_once_with("could you pull up what I've got going on?")


@pytest.mark.asyncio
async def test_classify_intent_haiku_fallback_returns_none():
    from src.llm.intent_classifier import classify_intent

    with patch("src.llm.intent_classifier._haiku_classify", new=AsyncMock(return_value=None)):
        result, method = await classify_intent("tell me about my week")

    assert result is None
    assert method == "none"


@pytest.mark.asyncio
async def test_classify_intent_haiku_failure_falls_through():
    from src.llm.intent_classifier import classify_intent

    with patch("src.llm.intent_classifier._haiku_classify", new=AsyncMock(side_effect=Exception("API error"))):
        result, method = await classify_intent("do the thing")

    assert result is None
```

- [ ] **Step 4.2: Run** — Expected: All PASS

- [ ] **Step 4.3: Commit**

```bash
git add tests/test_intent_classifier.py
git commit -m "test(llm): add Haiku fallback tests for intent classifier"
```

---

### Task 5: Tool-use loop (`tool_agent.py`) + stub `chat_tools.py`

**Files:** `src/llm/tool_agent.py`, `src/api/services/chat_tools.py`

- [ ] **Step 5.1: Write failing tests for the tool loop** — Append to `tests/test_tool_agent.py`:

```python
import uuid
from unittest.mock import MagicMock, AsyncMock, patch

@pytest.mark.asyncio
async def test_tool_loop_end_turn_on_first_call(async_session, set_test_env):
    from src.llm.tool_agent import run_tool_loop, ToolError

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "I can help with that."

    fake_response = MagicMock()
    fake_response.stop_reason = "end_turn"
    fake_response.content = [text_block]

    async def fake_dispatch(tool_name, args, session, user_id):
        raise ToolError("should not be called")

    with patch("src.llm.tool_agent.anthropic_client") as mock_client:
        mock_client._messages_create = AsyncMock(return_value=fake_response)
        result = await run_tool_loop(
            system_prompt="You are helpful.",
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
            model="claude-sonnet-4-6",
            max_tokens=100,
            session=async_session,
            user_id=uuid.UUID(int=0),
            dispatch=fake_dispatch,
            user_message="hello",
            tools_enabled=True,
            intent_tool=None,
            intent_method="none",
        )

    assert result == "I can help with that."


@pytest.mark.asyncio
async def test_tool_loop_dispatches_tool_call(async_session, set_test_env):
    from src.llm.tool_agent import run_tool_loop

    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.id = "tu_123"
    tool_use_block.name = "list_todos"
    tool_use_block.input = {}

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "You have 3 todos."

    resp1 = MagicMock()
    resp1.stop_reason = "tool_use"
    resp1.content = [tool_use_block]

    resp2 = MagicMock()
    resp2.stop_reason = "end_turn"
    resp2.content = [text_block]

    dispatch_calls = []

    async def fake_dispatch(tool_name, args, session, user_id):
        dispatch_calls.append(tool_name)
        return '[{"id": "abc", "description": "Buy milk"}]'

    with patch("src.llm.tool_agent.anthropic_client") as mock_client:
        mock_client._messages_create = AsyncMock(side_effect=[resp1, resp2])
        result = await run_tool_loop(
            system_prompt="You are helpful.",
            messages=[{"role": "user", "content": "list my todos"}],
            tools=[],
            model="claude-sonnet-4-6",
            max_tokens=100,
            session=async_session,
            user_id=uuid.UUID(int=0),
            dispatch=fake_dispatch,
            user_message="list my todos",
            tools_enabled=True,
            intent_tool="list_todos",
            intent_method="regex",
        )

    assert result == "You have 3 todos."
    assert dispatch_calls == ["list_todos"]


@pytest.mark.asyncio
async def test_tool_loop_cap(async_session, set_test_env):
    from src.llm.tool_agent import run_tool_loop, MAX_ITERATIONS

    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.id = "tu_loop"
    tool_use_block.name = "list_todos"
    tool_use_block.input = {}

    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.content = [tool_use_block]

    async def fake_dispatch(tool_name, args, session, user_id):
        return "[]"

    with patch("src.llm.tool_agent.anthropic_client") as mock_client:
        mock_client._messages_create = AsyncMock(return_value=resp)
        result = await run_tool_loop(
            system_prompt="",
            messages=[{"role": "user", "content": "loop forever"}],
            tools=[],
            model="claude-sonnet-4-6",
            max_tokens=100,
            session=async_session,
            user_id=uuid.UUID(int=0),
            dispatch=fake_dispatch,
            user_message="loop forever",
            tools_enabled=True,
            intent_tool=None,
            intent_method="none",
        )

    assert "one turn" in result.lower()
    assert mock_client._messages_create.call_count == MAX_ITERATIONS
```

- [ ] **Step 5.2: Run to verify they fail** — Expected: `ModuleNotFoundError: No module named 'src.llm.tool_agent'`

- [ ] **Step 5.3: Create `src/llm/tool_agent.py`**

```python
"""Agentic tool-use loop for chat."""
from __future__ import annotations

import time
import uuid
from collections.abc import Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.llm.client import ExtractionFailed, anthropic_client

logger = structlog.get_logger(__name__)

MAX_ITERATIONS = 10


class ToolError(Exception):
    """Raised by tool handlers to surface a user-visible error to the model."""


async def run_tool_loop(
    *,
    system_prompt: str,
    messages: list[dict],
    tools: list[dict],
    model: str,
    max_tokens: int,
    session: AsyncSession,
    user_id: uuid.UUID,
    dispatch: Callable,
    user_message: str,
    tools_enabled: bool,
    intent_tool: str | None,
    intent_method: str | None,
) -> str:
    start_ms = int(time.time() * 1000)
    loop_messages = list(messages)
    llm_calls: list[dict] = []
    tool_calls_log: list[dict] = []

    for iteration in range(MAX_ITERATIONS):
        raw = await anthropic_client._messages_create(
            messages=loop_messages,
            system=system_prompt,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
        )

        llm_calls.append({
            "turn_index": iteration,
            "model": model,
            "stop_reason": raw.stop_reason,
            "input_message_count": len(loop_messages),
        })

        if raw.stop_reason == "end_turn":
            text = next((b.text for b in raw.content if b.type == "text"), "")
            await _write_log(
                session=session,
                user_message=user_message,
                tools_enabled=tools_enabled,
                intent_tool=intent_tool,
                intent_method=intent_method,
                llm_calls=llm_calls,
                tool_calls=tool_calls_log,
                response_text=text,
                model_used=model,
                duration_ms=int(time.time() * 1000) - start_ms,
            )
            return text

        tool_use_blocks = [b for b in raw.content if b.type == "tool_use"]
        tool_result_content: list[dict] = []

        for block in tool_use_blocks:
            t_start = int(time.time() * 1000)
            try:
                result_text = await dispatch(block.name, block.input, session, user_id)
                is_error = False
            except ToolError as exc:
                result_text = str(exc)
                is_error = True
            except Exception as exc:
                logger.warning("tool_dispatch_unexpected_error", tool=block.name, error=str(exc))
                result_text = f"Tool error: {exc}"
                is_error = True

            tool_calls_log.append({
                "tool_name": block.name,
                "args": block.input,
                "result": result_text,
                "duration_ms": int(time.time() * 1000) - t_start,
                "is_error": is_error,
            })
            tool_result_content.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_text,
                "is_error": is_error,
            })

        loop_messages.append({"role": "assistant", "content": raw.content})
        loop_messages.append({"role": "user", "content": tool_result_content})

    cap_msg = "I wasn't able to complete that in one turn."
    await _write_log(
        session=session,
        user_message=user_message,
        tools_enabled=tools_enabled,
        intent_tool=intent_tool,
        intent_method=intent_method,
        llm_calls=llm_calls,
        tool_calls=tool_calls_log,
        response_text=cap_msg,
        model_used=model,
        duration_ms=int(time.time() * 1000) - start_ms,
    )
    return cap_msg


async def _write_log(
    *,
    session: AsyncSession,
    user_message: str,
    tools_enabled: bool,
    intent_tool: str | None,
    intent_method: str | None,
    llm_calls: list[dict],
    tool_calls: list[dict],
    response_text: str,
    model_used: str,
    duration_ms: int,
) -> None:
    try:
        from src.core.models import ChatLog

        log = ChatLog(
            user_message=user_message,
            tools_enabled=tools_enabled,
            intent_tool=intent_tool,
            intent_method=intent_method,
            llm_calls=llm_calls,
            tool_calls=tool_calls,
            response_text=response_text,
            model_used=model_used,
            duration_ms=duration_ms,
        )
        session.add(log)
        await session.commit()
    except Exception:
        logger.warning("chat_log_write_failed", exc_info=True)
```

- [ ] **Step 5.4: Create the stub `src/api/services/chat_tools.py`**

```python
"""Chat tool registry — aggregates tool schemas and dispatches calls."""
from __future__ import annotations

import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from src.llm.tool_agent import ToolError

ALL_TOOLS: list[dict] = []
_DISPATCH_TABLE: dict = {}


async def dispatch(
    tool_name: str,
    args: dict,
    session: AsyncSession,
    user_id: uuid.UUID,
) -> str:
    handler = _DISPATCH_TABLE.get(tool_name)
    if handler is None:
        raise ToolError(f"Unknown tool: {tool_name}")
    return await handler(tool_name, args, session, user_id)
```

- [ ] **Step 5.5: Run all tool agent tests** — Expected: All 4 PASS

```bash
pytest tests/test_tool_agent.py -v
```

- [ ] **Step 5.6: Commit**

```bash
git add src/llm/tool_agent.py src/api/services/chat_tools.py tests/test_tool_agent.py
git commit -m "feat(llm): add tool-use loop and chat_tools stub"
```

---

### Task 6: Wire chat route with `tools_enabled`

**Files:** `src/api/routes/chat.py`

- [ ] **Step 6.1: Write failing tests** — Add to `tests/test_chat.py`:

```python
# Check the calling convention for _patch_chat_deps in existing tests first.

@pytest.mark.asyncio
async def test_chat_tools_disabled_uses_rag_path(client, api_key_headers, monkeypatch):
    _patch_chat_deps(monkeypatch)
    with patch("src.api.routes.chat.classify_intent") as mock_classify:
        resp = await client.post(
            "/v1/chat",
            json={"message": "mark my gym todo as done"},
            headers=api_key_headers,
        )
    assert resp.status_code == 200
    mock_classify.assert_not_called()


@pytest.mark.asyncio
async def test_chat_tools_enabled_no_intent_uses_rag_path(client, api_key_headers, monkeypatch):
    _patch_chat_deps(monkeypatch)
    with patch("src.api.routes.chat.classify_intent", new=AsyncMock(return_value=(None, "none"))):
        with patch("src.api.routes.chat.run_tool_loop") as mock_loop:
            resp = await client.post(
                "/v1/chat",
                json={"message": "what is the meaning of life?", "tools_enabled": True},
                headers=api_key_headers,
            )
    assert resp.status_code == 200
    mock_loop.assert_not_called()


@pytest.mark.asyncio
async def test_chat_tools_enabled_with_intent_calls_tool_loop(client, api_key_headers, monkeypatch):
    _patch_chat_deps(monkeypatch)
    with patch("src.api.routes.chat.classify_intent", new=AsyncMock(return_value=("list_todos", "regex"))):
        with patch("src.api.routes.chat.run_tool_loop", new=AsyncMock(return_value="You have 2 todos.")) as mock_loop:
            resp = await client.post(
                "/v1/chat",
                json={"message": "show my todos", "tools_enabled": True},
                headers=api_key_headers,
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["response"] == "You have 2 todos."
    mock_loop.assert_called_once()
    call_kwargs = mock_loop.call_args.kwargs
    assert call_kwargs["model"] == "claude-sonnet-4-6"
    assert call_kwargs["intent_tool"] == "list_todos"
```

- [ ] **Step 6.2: Run to verify they fail** — Expected: `422` or `ImportError`

- [ ] **Step 6.3: Update `ChatRequest` in `src/api/routes/chat.py`**

Add `tools_enabled: bool = Field(default=False)` to `ChatRequest`.

- [ ] **Step 6.4: Add imports to `src/api/routes/chat.py`**

```python
import uuid as _uuid
from src.llm.intent_classifier import classify_intent
from src.llm.tool_agent import run_tool_loop
from src.api.services.chat_tools import ALL_TOOLS, dispatch
```

- [ ] **Step 6.5: Replace step 9 (Synthesize) in `src/api/routes/chat.py`**

```python
    # ── 9. Synthesize (or run tool loop) ────────────────────────────────────
    intent_tool: str | None = None
    intent_method: str = "none"

    if body.tools_enabled:
        intent_tool, intent_method = await classify_intent(body.message)

    if intent_tool is not None:
        response_text = await run_tool_loop(
            system_prompt=system_prompt,
            messages=messages_for_llm,
            tools=ALL_TOOLS,
            model="claude-sonnet-4-6",
            max_tokens=2048,
            session=session,
            user_id=_uuid.UUID(int=0),
            dispatch=dispatch,
            user_message=body.message,
            tools_enabled=body.tools_enabled,
            intent_tool=intent_tool,
            intent_method=intent_method,
        )
    else:
        response_text = await anthropic.complete_with_history(
            system_prompt=system_prompt,
            messages=messages_for_llm,
            model=resolved_model,
            max_tokens=2048,
        )
```

- [ ] **Step 6.6: Run tool routing tests** — Expected: All 3 PASS

```bash
pytest tests/test_chat.py -v -k "tools"
```

- [ ] **Step 6.7: Run full test suite for regressions**

```bash
pytest tests/test_chat.py -v
```

- [ ] **Step 6.8: Commit**

```bash
git add src/api/routes/chat.py tests/test_chat.py
git commit -m "feat(chat): wire tools_enabled param and intent routing"
```

**PR 1 complete.** Infrastructure in place. Tool list is empty — no domain tools yet.

---

### Task 7: `memory_service.search_memory_filtered()`

**Files:** `src/api/services/memory_service.py`

- [ ] **Step 7.1: Write failing tests** — Create `tests/test_memory_tools.py`:

```python
import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, patch, MagicMock


def _make_search_result(id="abc", content="test content", type="learning",
                         importance_score=0.7, project=None):
    from src.retrieval.search import SearchResult
    return SearchResult(
        id=id, content=content, summary="summary", type=type,
        importance_score=importance_score, combined_score=0.8,
        created_at=datetime(2026, 5, 1, tzinfo=UTC), project=project,
    )


@pytest.mark.asyncio
async def test_search_memory_filtered_no_filters(async_session):
    from src.api.services.memory_service import search_memory_filtered

    results = [_make_search_result(), _make_search_result(id="def", content="other")]
    with patch("src.api.services.memory_service.hybrid_search", new=AsyncMock(return_value=results)):
        with patch("src.api.services.memory_service.embedding_client") as mock_embed:
            mock_embed.embed = AsyncMock(return_value=[0.1] * 1024)
            out = await search_memory_filtered(async_session, query="test")

    assert len(out) == 2


@pytest.mark.asyncio
async def test_search_memory_filtered_by_type(async_session):
    from src.api.services.memory_service import search_memory_filtered

    with patch("src.api.services.memory_service.hybrid_search", new=AsyncMock(return_value=[])) as mock_search:
        with patch("src.api.services.memory_service.embedding_client") as mock_embed:
            mock_embed.embed = AsyncMock(return_value=[0.1] * 1024)
            await search_memory_filtered(async_session, query="test", type="learning")

    assert mock_search.call_args.kwargs["type_filter"] == "learning"


@pytest.mark.asyncio
async def test_search_memory_filtered_importance_min(async_session):
    from src.api.services.memory_service import search_memory_filtered

    results = [
        _make_search_result(id="high", importance_score=0.8),
        _make_search_result(id="low", importance_score=0.3),
    ]
    with patch("src.api.services.memory_service.hybrid_search", new=AsyncMock(return_value=results)):
        with patch("src.api.services.memory_service.embedding_client") as mock_embed:
            mock_embed.embed = AsyncMock(return_value=[0.1] * 1024)
            out = await search_memory_filtered(async_session, query="test", importance_min=0.5)

    assert len(out) == 1
    assert out[0].id == "high"
```

- [ ] **Step 7.2: Run to verify it fails** — Expected: `cannot import name 'search_memory_filtered'`

- [ ] **Step 7.3: Add `search_memory_filtered` to `src/api/services/memory_service.py`** — At end of file:

```python
async def search_memory_filtered(
    session: AsyncSession,
    *,
    query: str,
    type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    project: str | None = None,
    importance_min: float | None = None,
    limit: int = 10,
):
    from src.llm.client import embedding_client
    from src.retrieval.search import hybrid_search

    if embedding_client is None:
        logger.warning("search_memory_filtered_no_embedding_client")
        return []

    query_embedding = await embedding_client.embed(query)

    date_from_dt = datetime.fromisoformat(date_from).replace(tzinfo=UTC) if date_from else None
    date_to_dt = datetime.fromisoformat(date_to).replace(tzinfo=UTC) if date_to else None

    results = await hybrid_search(
        session=session,
        query_text=query,
        query_embedding=query_embedding,
        limit=limit,
        type_filter=type,
        date_from=date_from_dt,
        date_to=date_to_dt,
        project_filter=project,
    )

    if importance_min is not None:
        results = [r for r in results if r.importance_score >= importance_min]

    logger.info("search_memory_filtered", query=query[:80], type=type, result_count=len(results))
    return results
```

`UTC` and `datetime` are already imported in `memory_service.py`.

- [ ] **Step 7.4: Run the tests** — Expected: All 3 PASS

- [ ] **Step 7.5: Commit**

```bash
git add src/api/services/memory_service.py tests/test_memory_tools.py
git commit -m "feat(memory): add search_memory_filtered service method"
```

---

### Task 8: `todo_service.list_todos()`

**Files:** `src/api/services/todo_service.py`, `tests/test_todo_tools.py`

- [ ] **Step 8.1: Write failing tests** — Create `tests/test_todo_tools.py`:

```python
import pytest
from datetime import datetime, UTC


@pytest.mark.asyncio
async def test_list_todos_returns_all(async_session):
    from src.api.services.todo_service import create_todo, list_todos

    await create_todo(async_session, description="Buy milk")
    await create_todo(async_session, description="Write tests")

    todos = await list_todos(async_session)
    descriptions = [t.description for t in todos]
    assert "Buy milk" in descriptions
    assert "Write tests" in descriptions


@pytest.mark.asyncio
async def test_list_todos_filter_status(async_session):
    from src.api.services.todo_service import create_todo, list_todos, update_todo

    t1 = await create_todo(async_session, description="Open task")
    t2 = await create_todo(async_session, description="Done task")
    await update_todo(async_session, t2, status="done")

    open_todos = await list_todos(async_session, status="open")
    assert all(t.status == "open" for t in open_todos)
    done_todos = await list_todos(async_session, status="done")
    assert any(t.description == "Done task" for t in done_todos)


@pytest.mark.asyncio
async def test_list_todos_filter_project(async_session):
    from src.api.services.todo_service import create_todo, list_todos

    await create_todo(async_session, description="Proj A task", project="proj-a")
    await create_todo(async_session, description="Proj B task", project="proj-b")

    results = await list_todos(async_session, project="proj-a")
    assert all(t.project == "proj-a" for t in results)
    assert len(results) >= 1
```

- [ ] **Step 8.2: Run to verify they fail** — Expected: `cannot import name 'list_todos'`

- [ ] **Step 8.3: Add `list_todos` to `src/api/services/todo_service.py`** — At end of file:

```python
async def list_todos(
    session: AsyncSession,
    *,
    status: str | None = None,
    due_before: str | None = None,
    project: str | None = None,
) -> list[TodoItem]:
    from sqlalchemy import select

    stmt = select(TodoItem)

    if status is not None:
        stmt = stmt.where(TodoItem.status == status)
    if project is not None:
        stmt = stmt.where(TodoItem.project == project)
    if due_before is not None:
        from datetime import datetime as _dt
        due_dt = _dt.fromisoformat(due_before)
        stmt = stmt.where(TodoItem.due_date <= due_dt)

    stmt = stmt.order_by(TodoItem.created_at.desc())
    result = await session.execute(stmt)
    todos = list(result.scalars().all())
    logger.info("list_todos", count=len(todos), status=status, project=project)
    return todos
```

- [ ] **Step 8.4: Run the tests** — Expected: All 3 PASS

- [ ] **Step 8.5: Commit**

```bash
git add src/api/services/todo_service.py tests/test_todo_tools.py
git commit -m "feat(todo): add list_todos service method"
```

---

### Task 9: Memory tool handlers (`memory_tools.py`)

**Files:** `src/api/services/memory_tools.py`

- [ ] **Step 9.1: Write failing tests** — Append to `tests/test_memory_tools.py`:

```python
@pytest.mark.asyncio
async def test_handle_search_memory_filtered(async_session):
    from src.api.services.memory_tools import handle_search_memory_filtered
    import json, uuid

    results = [_make_search_result(id="abc", content="I learned about async")]
    with patch("src.api.services.memory_tools.search_memory_filtered", new=AsyncMock(return_value=results)):
        out = await handle_search_memory_filtered(
            "search_memory_filtered", {"query": "async patterns"}, async_session, uuid.UUID(int=0),
        )

    data = json.loads(out)
    assert len(data) == 1
    assert data[0]["id"] == "abc"


@pytest.mark.asyncio
async def test_handle_expand_memory(async_session):
    from src.api.services.memory_tools import handle_expand_memory
    from src.api.services.memory_service import ExpandResult
    import json, uuid

    expand_result = ExpandResult(
        memory_id="abc-123",
        content="Full content here",
        raw_text="Original input",
        neighbors=[],
        metadata={"source": "api", "project": None, "tags": [], "importance_score": 0.7, "created_at": "2026-05-01T00:00:00"},
    )
    with patch("src.api.services.memory_tools.expand_memory", new=AsyncMock(return_value=expand_result)):
        out = await handle_expand_memory(
            "expand_memory", {"memory_id": "abc-123"}, async_session, uuid.UUID(int=0),
        )

    data = json.loads(out)
    assert data["memory_id"] == "abc-123"
    assert data["content"] == "Full content here"
```

- [ ] **Step 9.2: Run to verify they fail** — Expected: `ModuleNotFoundError: No module named 'src.api.services.memory_tools'`

- [ ] **Step 9.3: Create `src/api/services/memory_tools.py`**

```python
"""Memory tool schemas and handlers for chat tool-use."""
from __future__ import annotations

import json
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.services.memory_service import (
    MemoryItemNotFound, SupersedesInvalidUUID, expand_memory, search_memory_filtered,
)
from src.llm.tool_agent import ToolError

logger = structlog.get_logger(__name__)

MEMORY_TOOLS: list[dict] = [
    {
        "name": "search_memory_filtered",
        "description": "Search your personal memory store with optional filters. Returns matching items with IDs, content, type, importance score, and project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"},
                "type": {"type": "string", "description": "Filter by memory type: learning, decision, todo, daily_pulse, etc."},
                "date_from": {"type": "string", "description": "ISO date lower bound, e.g. 2026-05-01"},
                "date_to": {"type": "string", "description": "ISO date upper bound, e.g. 2026-05-31"},
                "project": {"type": "string", "description": "Filter by project tag"},
                "importance_min": {"type": "number", "description": "Minimum importance score (0.0 to 1.0)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "expand_memory",
        "description": "Get the full content, raw source text, and neighboring items for a specific memory. Use after search_memory_filtered when you need complete details.",
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "UUID of the memory item to expand"},
            },
            "required": ["memory_id"],
        },
    },
]


async def handle_search_memory_filtered(
    tool_name: str, args: dict, session: AsyncSession, user_id: uuid.UUID,
) -> str:
    query = args.get("query")
    if not query:
        raise ToolError("search_memory_filtered requires a 'query' argument")

    results = await search_memory_filtered(
        session, query=query,
        type=args.get("type"), date_from=args.get("date_from"),
        date_to=args.get("date_to"), project=args.get("project"),
        importance_min=args.get("importance_min"),
    )
    return json.dumps([
        {
            "id": r.id, "content": r.content, "type": r.type,
            "importance_score": r.importance_score, "project": r.project,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in results
    ])


async def handle_expand_memory(
    tool_name: str, args: dict, session: AsyncSession, user_id: uuid.UUID,
) -> str:
    memory_id = args.get("memory_id")
    if not memory_id:
        raise ToolError("expand_memory requires a 'memory_id' argument")

    try:
        result = await expand_memory(session, memory_id=memory_id)
    except (MemoryItemNotFound, SupersedesInvalidUUID) as exc:
        raise ToolError(str(exc)) from exc

    return json.dumps({
        "memory_id": result.memory_id,
        "content": result.content,
        "raw_text": result.raw_text,
        "neighbors": [
            {"memory_id": n.memory_id, "content": n.content,
             "created_at": n.created_at.isoformat() if n.created_at else None}
            for n in result.neighbors
        ],
        "metadata": result.metadata,
    })


MEMORY_HANDLERS = {
    "search_memory_filtered": handle_search_memory_filtered,
    "expand_memory": handle_expand_memory,
}
```

- [ ] **Step 9.4: Run the tests** — Expected: All 5 PASS

```bash
pytest tests/test_memory_tools.py -v
```

- [ ] **Step 9.5: Commit**

```bash
git add src/api/services/memory_tools.py tests/test_memory_tools.py
git commit -m "feat(chat): add memory tool schemas and handlers"
```

---

### Task 10: Todo tool handlers (`todo_tools.py`)

**Files:** `src/api/services/todo_tools.py`

- [ ] **Step 10.1: Write failing tests** — Append to `tests/test_todo_tools.py`:

```python
import uuid, json
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_handle_list_todos(async_session):
    from src.api.services.todo_service import create_todo
    from src.api.services.todo_tools import handle_list_todos

    await create_todo(async_session, description="Feed the cat")
    out = await handle_list_todos("list_todos", {}, async_session, uuid.UUID(int=0))
    data = json.loads(out)
    assert any(t["description"] == "Feed the cat" for t in data)


@pytest.mark.asyncio
async def test_handle_create_todo(async_session):
    from src.api.services.todo_tools import handle_create_todo

    out = await handle_create_todo(
        "create_todo", {"description": "Write unit tests", "priority": "high"},
        async_session, uuid.UUID(int=0),
    )
    data = json.loads(out)
    assert data["description"] == "Write unit tests"
    assert "id" in data


@pytest.mark.asyncio
async def test_handle_complete_todo(async_session):
    from src.api.services.todo_service import create_todo
    from src.api.services.todo_tools import handle_complete_todo

    todo = await create_todo(async_session, description="Finish report")
    out = await handle_complete_todo(
        "complete_todo", {"todo_id": str(todo.id)}, async_session, uuid.UUID(int=0),
    )
    assert "Finish report" in out and "done" in out.lower()


@pytest.mark.asyncio
async def test_handle_complete_todo_not_found(async_session):
    from src.api.services.todo_tools import handle_complete_todo
    from src.llm.tool_agent import ToolError

    with pytest.raises(ToolError, match="not found"):
        await handle_complete_todo(
            "complete_todo", {"todo_id": str(uuid.uuid4())}, async_session, uuid.UUID(int=0),
        )


@pytest.mark.asyncio
async def test_handle_defer_todo(async_session):
    from src.api.services.todo_service import create_todo
    from src.api.services.todo_tools import handle_defer_todo

    todo = await create_todo(async_session, description="Submit taxes")
    out = await handle_defer_todo(
        "defer_todo", {"todo_id": str(todo.id), "until_date": "2026-06-01"},
        async_session, uuid.UUID(int=0),
    )
    assert "Submit taxes" in out or "deferred" in out.lower()


@pytest.mark.asyncio
async def test_handle_edit_todo(async_session):
    from src.api.services.todo_service import create_todo
    from src.api.services.todo_tools import handle_edit_todo

    todo = await create_todo(async_session, description="Old description")
    out = await handle_edit_todo(
        "edit_todo", {"todo_id": str(todo.id), "description": "New description"},
        async_session, uuid.UUID(int=0),
    )
    assert "New description" in out or "updated" in out.lower()
```

- [ ] **Step 10.2: Run to verify they fail** — Expected: `ModuleNotFoundError: No module named 'src.api.services.todo_tools'`

- [ ] **Step 10.3: Create `src/api/services/todo_tools.py`**

```python
"""Todo tool schemas and handlers for chat tool-use."""
from __future__ import annotations

import json
import uuid
from datetime import datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.services.todo_service import create_todo, list_todos, update_todo
from src.core.models import TodoItem
from src.llm.tool_agent import ToolError

logger = structlog.get_logger(__name__)

TODO_TOOLS: list[dict] = [
    {
        "name": "list_todos",
        "description": "List todos with optional filters for status, due date, or project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by status: open, done, cancelled"},
                "due_before": {"type": "string", "description": "ISO date — only todos due before this date"},
                "project": {"type": "string", "description": "Filter by project tag"},
            },
        },
    },
    {
        "name": "create_todo",
        "description": "Create a new todo item.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "The todo text (required)"},
                "priority": {"type": "string", "description": "high, normal, or low (default: normal)"},
                "due_date": {"type": "string", "description": "Optional ISO date for due date"},
                "project": {"type": "string", "description": "Optional project tag"},
            },
            "required": ["description"],
        },
    },
    {
        "name": "complete_todo",
        "description": "Mark a todo as done.",
        "input_schema": {
            "type": "object",
            "properties": {
                "todo_id": {"type": "string", "description": "UUID of the todo to complete"},
                "reason": {"type": "string", "description": "Optional reason or note"},
            },
            "required": ["todo_id"],
        },
    },
    {
        "name": "defer_todo",
        "description": "Defer (postpone) a todo to a later date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "todo_id": {"type": "string", "description": "UUID of the todo to defer"},
                "until_date": {"type": "string", "description": "ISO date to defer to (required)"},
                "reason": {"type": "string", "description": "Optional reason"},
            },
            "required": ["todo_id", "until_date"],
        },
    },
    {
        "name": "edit_todo",
        "description": "Edit a todo's description, priority, or project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "todo_id": {"type": "string", "description": "UUID of the todo to edit"},
                "description": {"type": "string", "description": "New description text"},
                "priority": {"type": "string", "description": "New priority: high, normal, or low"},
                "project": {"type": "string", "description": "New project tag"},
            },
            "required": ["todo_id"],
        },
    },
]


async def _get_todo(session: AsyncSession, todo_id: str) -> TodoItem:
    try:
        uid = uuid.UUID(todo_id)
    except ValueError as exc:
        raise ToolError(f"Invalid todo_id: {todo_id!r}") from exc

    todo = await session.get(TodoItem, uid)
    if todo is None:
        raise ToolError(f"Todo {todo_id} not found")
    return todo


async def handle_list_todos(tool_name: str, args: dict, session: AsyncSession, user_id: uuid.UUID) -> str:
    todos = await list_todos(session, status=args.get("status"), due_before=args.get("due_before"), project=args.get("project"))
    return json.dumps([
        {"id": str(t.id), "description": t.description, "status": t.status,
         "priority": t.priority, "due_date": t.due_date.isoformat() if t.due_date else None, "project": t.project}
        for t in todos
    ])


async def handle_create_todo(tool_name: str, args: dict, session: AsyncSession, user_id: uuid.UUID) -> str:
    description = args.get("description")
    if not description:
        raise ToolError("create_todo requires a 'description' argument")

    due_date = datetime.fromisoformat(args["due_date"]) if args.get("due_date") else None
    todo = await create_todo(session, description=description, priority=args.get("priority", "normal"),
                              due_date=due_date, project=args.get("project"))
    return json.dumps({"id": str(todo.id), "description": todo.description})


async def handle_complete_todo(tool_name: str, args: dict, session: AsyncSession, user_id: uuid.UUID) -> str:
    todo = await _get_todo(session, args.get("todo_id", ""))
    await update_todo(session, todo, status="done", reason=args.get("reason"))
    return f"Marked '{todo.description}' as done."


async def handle_defer_todo(tool_name: str, args: dict, session: AsyncSession, user_id: uuid.UUID) -> str:
    todo = await _get_todo(session, args.get("todo_id", ""))
    until_date_str = args.get("until_date")
    if not until_date_str:
        raise ToolError("defer_todo requires an 'until_date' argument")
    await update_todo(session, todo, due_date=datetime.fromisoformat(until_date_str), reason=args.get("reason"))
    return f"Deferred '{todo.description}' to {until_date_str}."


async def handle_edit_todo(tool_name: str, args: dict, session: AsyncSession, user_id: uuid.UUID) -> str:
    todo = await _get_todo(session, args.get("todo_id", ""))
    fields = {k: args[k] for k in ("description", "priority", "project") if k in args}
    if not fields:
        raise ToolError("edit_todo requires at least one field to update")
    await update_todo(session, todo, **fields)
    changes = ", ".join(f"{k}='{v}'" for k, v in fields.items())
    return f"Updated '{todo.description}': {changes}."


TODO_HANDLERS: dict = {
    "list_todos": handle_list_todos,
    "create_todo": handle_create_todo,
    "complete_todo": handle_complete_todo,
    "defer_todo": handle_defer_todo,
    "edit_todo": handle_edit_todo,
}
```

- [ ] **Step 10.4: Run the tests** — Expected: All PASS

```bash
pytest tests/test_todo_tools.py -v
```

- [ ] **Step 10.5: Commit**

```bash
git add src/api/services/todo_tools.py tests/test_todo_tools.py
git commit -m "feat(chat): add todo tool schemas and handlers"
```

---

### Task 11: Wire `chat_tools.py` dispatch table

**Files:** `src/api/services/chat_tools.py`

- [ ] **Step 11.1: Write failing tests** — Create `tests/test_chat_tools_dispatch.py`:

```python
import pytest
import uuid
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_dispatch_known_tool(async_session):
    from src.api.services.chat_tools import dispatch

    with patch("src.api.services.todo_tools.handle_list_todos", new=AsyncMock(return_value='[]')) as mock:
        result = await dispatch("list_todos", {}, async_session, uuid.UUID(int=0))

    mock.assert_called_once()
    assert result == '[]'


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_raises(async_session):
    from src.api.services.chat_tools import dispatch
    from src.llm.tool_agent import ToolError

    with pytest.raises(ToolError, match="Unknown tool"):
        await dispatch("nonexistent_tool", {}, async_session, uuid.UUID(int=0))


def test_all_tools_list_has_seven_entries():
    from src.api.services.chat_tools import ALL_TOOLS
    names = {t["name"] for t in ALL_TOOLS}
    assert names == {
        "search_memory_filtered", "expand_memory",
        "list_todos", "create_todo", "complete_todo", "defer_todo", "edit_todo",
    }
```

- [ ] **Step 11.2: Run to verify they fail** — Expected: `ALL_TOOLS` is empty, dispatch raises.

- [ ] **Step 11.3: Replace `src/api/services/chat_tools.py`**

```python
"""Chat tool registry — aggregates all tool schemas and dispatches calls."""
from __future__ import annotations

import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.services.memory_tools import MEMORY_HANDLERS, MEMORY_TOOLS
from src.api.services.todo_tools import TODO_HANDLERS, TODO_TOOLS
from src.llm.tool_agent import ToolError

ALL_TOOLS: list[dict] = MEMORY_TOOLS + TODO_TOOLS
_DISPATCH_TABLE: dict = {**MEMORY_HANDLERS, **TODO_HANDLERS}


async def dispatch(tool_name: str, args: dict, session: AsyncSession, user_id: uuid.UUID) -> str:
    handler = _DISPATCH_TABLE.get(tool_name)
    if handler is None:
        raise ToolError(f"Unknown tool: {tool_name}")
    return await handler(tool_name, args, session, user_id)
```

- [ ] **Step 11.4: Run dispatch tests** — Expected: All 3 PASS

- [ ] **Step 11.5: Run full backend test suite**

```bash
pytest tests/ -v --timeout=60 2>&1 | tail -30
```

- [ ] **Step 11.6: Commit PR2**

```bash
git add src/api/services/chat_tools.py src/api/services/memory_tools.py \
        src/api/services/todo_tools.py src/api/services/memory_service.py \
        src/api/services/todo_service.py tests/test_chat_tools_dispatch.py \
        tests/test_memory_tools.py tests/test_todo_tools.py
git commit -m "feat(chat): wire 7 domain tools into chat dispatch table"
```

**PR 2 complete.** Tools are wired, tests pass.

---

### Task 12: Frontend tools toggle

**Files:** `web/components/chat/ToolsToggle.tsx`, `web/app/chat/page.tsx`

- [ ] **Step 12.1: Find the chat page component**

```bash
find web/app -name "*.tsx" | xargs grep -l "model" | head -5
```

- [ ] **Step 12.2: Create `web/components/chat/ToolsToggle.tsx`**

```tsx
"use client";

interface ToolsToggleProps {
  enabled: boolean;
  onToggle: (enabled: boolean) => void;
}

export function ToolsToggle({ enabled, onToggle }: ToolsToggleProps) {
  return (
    <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer select-none">
      <input
        type="checkbox"
        checked={enabled}
        onChange={(e) => onToggle(e.target.checked)}
        className="h-4 w-4 rounded"
      />
      Tools
    </label>
  );
}
```

- [ ] **Step 12.3: Add `toolsEnabled` state to the chat page**

```tsx
import { ToolsToggle } from "@/components/chat/ToolsToggle";

const [toolsEnabled, setToolsEnabled] = React.useState<boolean>(() => {
  if (typeof window === "undefined") return false;
  return localStorage.getItem("chat_tools_enabled") === "true";
});

const handleToolsToggle = (enabled: boolean) => {
  setToolsEnabled(enabled);
  localStorage.setItem("chat_tools_enabled", String(enabled));
};
```

- [ ] **Step 12.4: Render the toggle near the model selector**

```tsx
<ToolsToggle enabled={toolsEnabled} onToggle={handleToolsToggle} />
```

- [ ] **Step 12.5: Add `tools_enabled` to the chat request body**

```tsx
body: JSON.stringify({
  message,
  history,
  model: selectedModel,
  tools_enabled: toolsEnabled,
}),
```

- [ ] **Step 12.6: Run frontend type checker**

```bash
cd web && npx tsc --noEmit
```

- [ ] **Step 12.7: Run Vitest** — Expected: All existing tests pass

- [ ] **Step 12.8: Commit PR3**

```bash
git add web/components/chat/ToolsToggle.tsx web/app/chat/
git commit -m "feat(web): add tools toggle to chat UI"
```

---

## Verification

**Backend end-to-end:**

```bash
make start
curl -s -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <your-key>" \
  -d '{"message": "show my open todos", "tools_enabled": true}' | jq .response
```

Expected: Response mentions todos (or "no open todos").

**Verify chat_logs row written:**

```sql
SELECT intent_tool, intent_method, model_used, duration_ms
FROM chat_logs ORDER BY created_at DESC LIMIT 1;
```

Expected: `intent_tool = 'list_todos'`, `intent_method = 'regex'` or `'haiku'`.

**Frontend manual test:**

1. Open `0xpai.com/chat`
2. Tools toggle appears next to model selector
3. Enable → send "show my todos" → tool-driven response
4. Disable → send "show my todos" → RAG response (no tool trace in DB)
5. Reload → toggle persists from localStorage

**Full test suite:**

```bash
pytest tests/ -v --timeout=60
cd web && npm test
```
