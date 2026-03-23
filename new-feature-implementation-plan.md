# Open Brain — Module Expansion Spec

**Created**: 2026-03-23
**Status**: Approved — implementation starts next session
**Phase priority**: A (Foundation) → B (Todo) → C (RAG Chat) → D (Pulse)

---

## Overview

Expand Open Brain with three new modules plus a Discord bot architectural refactor to support them. Each module is independently shippable and toggleable via config flags.

**Modules**:
1. **Todo System** — First-class todo management via Discord slash commands with full state history
2. **Morning Pulse** — Scheduled daily DM with calendar events, todos, and self-report collection
3. **Discord RAG Chat** — Conversational `?`-prefixed interface to the knowledge base

**Core constraint**: No cross-module dependencies. All modules communicate through the kernel (shared internal API). Capture under 15 seconds, zero navigation.

---

## Approved Decisions

| Decision | Choice | Reason |
|---|---|---|
| Todo storage | New `todo_items` table (not extending `tasks`) | `tasks` requires mandatory `memory_id` FK → 5-30s pipeline latency per todo |
| Schema migration | One migration `0003_new_modules.py` | Ship all 4 tables together |
| Pulse cron trigger | Host cron (`docker compose run --rm`) | Simpler; no new container needed |
| RAG trigger | `?` prefix in whitelisted `discord_rag_channel_ids` | Flexible, channel-agnostic |
| Discord bot pattern | `discord.Client` + `app_commands.Group` | Entire UI is slash commands; no prefix commands |
| Conversation buffer | DB-persisted in `rag_conversations` | Survives bot restarts |
| Calendar deps | Optional `[calendar]` pyproject extra | Not everyone needs Google Calendar |

---

## Schema: New Tables

> **Approved by user 2026-03-23.** All JSONB columns use `JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")` pattern.

### `todo_items`
```python
id: UUID PK
description: Text (NOT NULL)
priority: String(10), default="normal"      # "high" | "normal" | "low"
status: String(20), default="open"          # "open" | "done" | "cancelled"
due_date: timestamptz (nullable)
discord_message_id: String(30) (nullable)   # for in-place embed updates
discord_channel_id: String(30) (nullable)
created_at: timestamptz server_default=now()
updated_at: timestamptz server_default=now(), onupdate=now()
```
Index: `(status, due_date)` composite

### `todo_history` (append-only)
```python
id: UUID PK
todo_id: UUID FK → todo_items.id (CASCADE)
event_type: String(30)                      # "created" | "completed" | "deferred" | "cancelled" | "priority_changed"
old_value: JSONB (nullable)                 # snapshot before change
new_value: JSONB (nullable)                 # snapshot after change
reason: Text (nullable)                     # populated on deferrals
created_at: timestamptz server_default=now()
```

### `daily_pulse`
```python
id: UUID PK
pulse_date: timestamptz (UNIQUE)            # unique per day — prevents duplicate sends
raw_reply: Text (nullable)
sleep_quality: Integer (nullable)           # 1–10
energy_level: Integer (nullable)            # 1–10
wake_time: String(10) (nullable)            # "07:30"
parsed_data: JSONB (nullable)               # full Haiku-parsed JSON blob
ai_question: Text (nullable)               # contextual question sent to user
status: String(20), default="sent"          # "sent" | "replied" | "parsed" | "parse_failed" | "skipped"
discord_message_id: String(30) (nullable)
created_at: timestamptz server_default=now()
updated_at: timestamptz server_default=now(), onupdate=now()
```

### `rag_conversations`
```python
id: UUID PK
discord_channel_id: String(30) NOT NULL
discord_user_id: String(30) NOT NULL
messages: JSONB NOT NULL default=[]         # [{role: "user"|"assistant", content: "..."}]
model_name: String(100) default="claude-haiku-4-5-20251001"
created_at: timestamptz server_default=now()
last_active_at: timestamptz server_default=now(), onupdate=now()
```
Unique index: `(discord_channel_id, discord_user_id)`

---

## Phase A: Foundation

**Goal**: Refactor bot + add schema. Required before any module work.

### A1: Discord Bot Refactor

**Problem**: `discord_bot.py` is a monolithic ~300-line class. Three modules can't fit here.

**New structure**:
```
src/integrations/
├── discord_bot.py          # Thin loader — conditionally loads module groups
├── kernel.py               # Shared pure helpers (moved from discord_bot.py)
└── modules/
    ├── __init__.py
    ├── core_cog.py         # /search, /digest, /status (extracted, unchanged behavior)
    ├── todo_cog.py         # Todo module (Phase B)
    ├── pulse_cog.py        # Morning Pulse module (Phase D)
    └── rag_cog.py          # RAG Chat module (Phase C)
```

**What moves to `kernel.py`**:
- `ingest_memory()`, `search_memories()`, `trigger_digest()`, `get_api_health()` (existing pure helpers)
- `require_allowed_user()` (new — extracted from per-command inline checks)

**Loader pattern** (`discord_bot.py`):
```python
class OpenBrainBot(discord.Client):
    async def setup_hook(self) -> None:
        # Core always loaded
        from src.integrations.modules.core_cog import register_core
        register_core(self.tree, self._http, self._settings)

        if self._settings.module_todo_enabled:
            from src.integrations.modules.todo_cog import TodoGroup
            self.tree.add_command(TodoGroup(self._http, self._settings))

        if self._settings.module_rag_chat_enabled:
            from src.integrations.modules.rag_cog import register_rag
            register_rag(self, self._http, self._settings)

        if self._settings.module_pulse_enabled:
            from src.integrations.modules.pulse_cog import register_pulse
            register_pulse(self, self._http, self._settings)
```

**Exit criteria**: All existing `test_discord_bot.py` tests pass unchanged.

### A2: Schema Migration + Config

1. Add 4 ORM models to `src/core/models.py`
2. Write `alembic/versions/0003_new_modules.py`
3. Add to `src/core/config.py`:

```python
# Feature flags
module_todo_enabled: bool = True
module_pulse_enabled: bool = True
module_rag_chat_enabled: bool = True

# Todo
todo_priority_levels: list[str] = ["high", "normal", "low"]

# Morning Pulse
pulse_send_time: str = "07:00"
pulse_timezone: str = "UTC"
pulse_reply_window_minutes: int = 120
google_calendar_credentials_path: str = ""
google_calendar_token_path: str = ""
discord_pulse_user_id: int = 0

# RAG Chat
rag_trigger_prefix: str = "?"
rag_conversation_buffer_size: int = 5
rag_conversation_ttl_hours: int = 24
rag_default_model: str = "claude-haiku-4-5-20251001"
rag_sonnet_model: str = "claude-sonnet-4-6"
rag_save_qa_as_memory: bool = False
discord_rag_channel_ids: list[int] = []
```

**Exit criteria**: `alembic upgrade head` runs clean; new model unit tests pass on SQLite.

---

## Phase B: Todo Module ← START HERE

**Priority**: Highest — most standalone, immediately useful.

### B1: Todo API

**New**: `src/api/routes/todos.py`

```
POST   /v1/todos              — create todo
GET    /v1/todos              — list (filters: status, priority, due_before)
GET    /v1/todos/{id}         — fetch single
PATCH  /v1/todos/{id}         — update (writes TodoHistory in same transaction)
GET    /v1/todos/{id}/history — state change log
```

Pydantic models:
```python
class TodoCreate(BaseModel):
    description: str
    priority: str = "normal"
    due_date: datetime | None = None

class TodoUpdate(BaseModel):
    description: str | None = None
    priority: str | None = None
    due_date: datetime | None = None
    status: str | None = None
    reason: str | None = None    # Stored in TodoHistory, not TodoItem

class TodoResponse(BaseModel):
    id: str
    description: str
    priority: str
    status: str
    due_date: datetime | None
    discord_message_id: str | None
    discord_channel_id: str | None
    created_at: datetime
    updated_at: datetime
```

**New**: `src/api/services/todo_service.py`
- `create_todo(session, data) → TodoItem` — inserts `TodoItem` + `TodoHistory(event_type="created")` in one transaction
- `update_todo(session, todo_id, data) → TodoItem` — inserts update + `TodoHistory` diff row in one transaction

The service layer ensures history rows are never forgotten (if only routes called DB directly, a missed flush would silently skip history).

Register router in `src/api/main.py`.

### B2: Todo Discord Cog

**New**: `src/integrations/modules/todo_cog.py`

Commands:
```
/todo                               → Show open todos as embed with Done/Defer buttons
/todo add <text> [@date] [priority] → Create todo, show confirmation embed
/todo done <id>                     → Mark done
/todo defer <id> <date> [reason]    → Defer (modal for date + optional reason)
```

**Natural date parsing** (pure function, no new deps):
```python
def parse_natural_date(token: str, today: date) -> date | None:
    """Parse @tomorrow, @monday–@sunday, @next-week, @YYYY-MM-DD. Returns None on failure."""
```

**Interactive embeds**: `discord.ui.View` + `discord.ui.Button`. Buttons call the API. `discord_message_id` + `discord_channel_id` in `todo_items` allows embed re-fetch + edit on bot restart (no in-memory state).

**Defer modal flow**:
1. User clicks Defer or runs `/todo defer <id>`
2. `discord.ui.Modal` opens with date + optional reason fields
3. On submit → PATCH `/v1/todos/{id}` with `due_date` + `reason`
4. Service writes `TodoHistory(event_type="deferred", old_value={...}, new_value={...}, reason=...)`
5. Original message edited in-place

**Exit criteria**: Interactive embed updates in-place; all `tests/test_todos.py` + `tests/test_todo_cog.py` pass.

---

## Phase C: Discord RAG Chat

**Parallelizable with Phase B.**

### C1: RAG Pipeline

**New**: `src/integrations/modules/rag_cog.py`

Full pipeline:
```
? message
  → parse_model_override(content) → (model_id, clean_query)
  → check rate limit (last_active_at < 10s ago → throttle)
  → load_conversation(channel_id, user_id) from rag_conversations
  → embed query via existing VoyageClient
  → GET /v1/search?q={query} — reuse existing hybrid_search
  → build_rag_prompt(query, context, history)
  → AnthropicClient with messages=[...history, {role:"user", content:prompt}]
  → trim_buffer(messages, buffer_size)
  → upsert rag_conversations
  → Discord reply + source citations as embed fields
```

**Model routing**:
```python
def _parse_model_override(content: str, settings) -> tuple[str, str]:
    # "?sonnet query" → (settings.rag_sonnet_model, "query")
    # "?haiku query"  → (settings.rag_default_model, "query")
    # "? query"       → (settings.rag_default_model, "query")
```
Model persisted in `rag_conversations.model_name`. `?sonnet` on next message switches.

**Context re-fetch design**: Memory context is re-fetched fresh on every turn (not stored in history). History provides conversational coherence; fresh search provides up-to-date retrieval. Keeps buffer small.

**Prompt injection defense**:
```python
def build_rag_user_message(query: str, context: str) -> str:
    return (
        f"Memory context:\n<context>{context}</context>\n\n"
        f"User question:\n<user_input>{query}</user_input>"
    )
```

**`on_message` handler** (in `discord_bot.py` or `rag_cog.py`):
```python
if (message.author.id in settings.discord_allowed_user_ids
        and message.channel.id in settings.discord_rag_channel_ids
        and message.content.startswith(settings.rag_trigger_prefix)):
    await handle_rag_query(message)
```

**Exit criteria**: `?` messages in configured channels return RAG responses; `?sonnet` switches model; all `tests/test_rag_cog.py` pass.

---

## Phase D: Morning Pulse

**Depends on A2 only. Can be built after B + C.**

### D1: Calendar Port

**New**: `src/integrations/calendar.py`

Port from `/home/shu/projects/Cadence/scripts/fetch/calendar_fetcher.py`:
- `CalendarFetcher`, `CalendarEvent`, `CalendarState`
- Replace stdlib logging with structlog
- Graceful fallback: empty `CalendarState` if creds not configured or auth fails

**New optional extra** in `pyproject.toml`:
```toml
[project.optional-dependencies]
calendar = [
    "google-auth>=2.0.0",
    "google-auth-oauthlib>=1.0.0",
    "google-api-python-client>=2.0.0",
]
```

If not installed, `pulse_cog.py` skips the calendar section silently.

### D2: Pulse Job + API

**New**: `src/jobs/pulse.py`

`send_morning_pulse()`:
1. Check `daily_pulse` for today — if exists and status != "skipped", return (idempotent)
2. Fetch calendar events (graceful fallback)
3. Fetch open todos via `GET /v1/todos?status=open`
4. Generate contextual question via Haiku (based on recent memories + deferred todos)
5. Build DM embed
6. Send via Discord REST API (`httpx` direct POST — no gateway needed for cron job)
7. Insert `DailyPulse(status="sent", discord_message_id=...)`

`parse_pulse_reply(raw_reply: str) → ParsedPulseData | None`:
- Calls Haiku with structured parse prompt
- On failure: returns `None`, caller sets `status="parse_failed"` + stores raw reply

**Pulse parse prompt**:
```
Parse the user's morning check-in into JSON:
{"sleep_quality": <1-10 or null>, "energy_level": <1-10 or null>, "wake_time": "<HH:MM> or null", "notes": "..."}
Return ONLY valid JSON. Use null for missing values. Do not invent values.
```

**Host cron** (document in README, no new Docker service):
```bash
0 7 * * * docker compose -f /path/to/open-brain/docker-compose.yml run --rm worker python -m src.jobs.pulse
```

**New**: `src/api/routes/pulse.py`
```
POST /v1/pulse          — Create/update today's pulse
GET  /v1/pulse/today    — Today's pulse status
GET  /v1/pulse          — History (paginated)
GET  /v1/pulse/{date}   — Specific date (YYYY-MM-DD)
```

### D3: Pulse Discord Cog

**New**: `src/integrations/modules/pulse_cog.py`

`on_message` handler:
1. Is DM? Author is `discord_pulse_user_id`? Today's pulse `status="sent"`?
2. If all true → call `parse_pulse_reply()` → PATCH `/v1/pulse` with parsed data → react ✅
3. Disambiguate from normal auto-ingest (DM from pulse user goes to pulse parser, not memory ingest)

---

## Phase E: Hardening

1. Update `CLAUDE.md` Module Ownership table
2. Update `ARCHITECTURE.md` with module system, new tables
3. End-to-end integration test: all three modules simultaneously, verify no cross-contamination
4. Rate limit tests for `/v1/todos/*` and `/v1/pulse/*`

---

## Critical Files

| File | Change |
|---|---|
| `src/core/models.py` | Add `TodoItem`, `TodoHistory`, `DailyPulse`, `RagConversation` |
| `src/core/config.py` | Feature flags + all new module settings |
| `src/api/main.py` | Register `todos` + `pulse` routers |
| `src/integrations/discord_bot.py` | Refactor to module loader |
| `src/integrations/kernel.py` | **New** — shared helpers |
| `src/integrations/modules/core_cog.py` | **New** — extracted core commands |
| `src/integrations/modules/todo_cog.py` | **New** |
| `src/integrations/modules/rag_cog.py` | **New** |
| `src/integrations/modules/pulse_cog.py` | **New** |
| `src/integrations/calendar.py` | **New** — ported from Cadence |
| `src/api/routes/todos.py` | **New** |
| `src/api/services/todo_service.py` | **New** |
| `src/api/routes/pulse.py` | **New** |
| `src/jobs/pulse.py` | **New** |
| `alembic/versions/0003_new_modules.py` | **New** migration |
| `pyproject.toml` | Add `[calendar]` optional extra |
| `CLAUDE.md` | Update Module Ownership table (Phase E) |
| `ARCHITECTURE.md` | Update for module system + new tables (Phase E) |

---

## Test Strategy

### Phase A
- `tests/test_discord_bot.py` — all existing tests must pass unchanged after refactor
- `tests/test_bot_modules.py` — disabled module commands not registered; core always available

### Phase B (Todo)
- `tests/test_todos.py` — CRUD happy paths, 422 validation, filter queries, history append-only invariant
- `tests/test_todo_cog.py` — `parse_natural_date()` edge cases, button callbacks (mock httpx), unauthorized rejection

### Phase C (RAG Chat)
- `tests/test_rag_cog.py` — model routing parser, buffer trimming, conversation upsert, TTL expiry, injection defense, per-user rate limit

### Phase D (Pulse)
- `tests/test_pulse.py` — unique-per-date constraint, Haiku parse (full/partial/invalid JSON), idempotent send, API routes
- `tests/test_calendar.py` — graceful fallback when creds missing, mock Google API

### All phases
- `pytest tests/` must pass on SQLite (no external services in tests)
- Mock all LLM + embedding calls (never hit production in tests)

---

## Verification Checklist

- [ ] `alembic upgrade head` — clean run
- [ ] `pytest tests/` — all pass
- [ ] `/todo add "test @tomorrow high"` — embed appears with Done/Defer buttons
- [ ] Click Done — embed updates in-place, history row created in DB
- [ ] `?sonnet What do I know about X?` — cited response, model switched for conversation
- [ ] `python -m src.jobs.pulse` — DM arrives; reply → ✅ reaction; `GET /v1/pulse/today` shows parsed data

---

## Reuse from Cadence

| Component | Location | Reuse strategy |
|---|---|---|
| `CalendarFetcher` | `Cadence/scripts/fetch/calendar_fetcher.py` | Port as `src/integrations/calendar.py` (structlog + graceful fallback) |
| `CalendarEvent`, `CalendarState` | `Cadence/scripts/schemas.py` | Adapt inline in `calendar.py` |
| OAuth2 flow | `calendar_fetcher.py` | Port as-is |
| Daily planning logic | `Cadence/scripts/agent_daily_planner.py` | **Do NOT reuse** — Cadence daily briefing doesn't exist yet as noted in ARCHITECTURE.md |
