# Claude Code Collaboration Guidelines

**Project**: Open Brain | **Owner**: Shu | **Last Updated**: 2026-03-24

---

## Decision Authority & Escalation

**Claude can decide alone** (no approval needed):
- Code style, naming, formatting, comments
- Module organization and file structure
- Test implementation details and assertions
- Error messages, logging statements, documentation
- Micro-optimizations (no logic change)
- Dependency versions (within reason)

**Escalate to user** before proceeding:
- **Schema changes**: Add/remove/rename tables or columns
- **Architecture shifts**: Technology swaps (e.g., PostgreSQL → Redis queue)
- **External dependencies**: New LLM providers, cloud services, databases
- **Timeline/scope**: Deadline changes or phase cuts
- **API contract**: Request/response shape changes
- **Security**: Auth methods, encryption, key management, TLS setup
- **Phase re-ordering or skipping**

---

## Code Style & Conventions

### Python
- **Version**: 3.12+ | **Format**: Black (100 char) | **Lint**: ruff (all enabled)
- **Type hints**: Mandatory on all functions/methods
- **Async**: All I/O must be async; no sync blocking in event loop
- **Logging**: structlog only (never print() or logging.basicConfig())

### FastAPI Routes
- Routes prefixed `/v1/` | Query/path params use `lowercase_snake_case`
- Request/response bodies are Pydantic models
- All 4xx/5xx responses documented in docstring
- Auth: X-API-Key header checked via middleware (not per-route)

### SQLAlchemy ORM
- All PKs: `UUID(as_uuid=True)` | All FKs must match type
- Use `nullable=False` to enforce NOT NULL
- Use `ForeignKey(...)` with cascade options
- Use relationships for navigation, not raw joins
- GENERATED columns: defined in ORM, enforced at DDL in Alembic

### Testing
- **Framework**: pytest + pytest-asyncio
- **Mandatory Coverage**: Generate tests for every feature or logic change.
- **Rigor**: Do not limit tests to the "happy path." Explicitly cover:
  - **Edge Cases**: Empty states (0-item lists), boundary values, and `None` handling.
  - **Negative Scenarios**: Validation errors, 4xx/5xx triggers, and unauthorized attempts.
  - **Logic Restrictions**: Critical UX/Business rules (e.g., "cannot delete last remaining service").
  - **Data Integrity**: Verify that public-facing API views correctly reflect backend database changes.
- **Mocks**: Mock all external APIs (Anthropic, Voyage) — **never hit production in tests**
- **Organization**: Fixtures in conftest.py, not inline
- **Naming**: `test_<function>_<scenario>` (e.g., `test_delete_service_fails_if_last_remaining`)
- **Assertions**: Use plain `assert`, not custom matchers

### Naming Conventions
- Tables: `snake_case` | Modules: `snake_case` | Classes: `PascalCase` | Constants: `UPPER_SNAKE_CASE`
- Pydantic models: `PascalCase` + suffix (e.g., `MemoryItemResponse`, `MemoryItemCreate`)

### Error Handling
- Custom exceptions inherit from `Exception` (not `BaseException`)
- Use named exceptions for expected failures (e.g., `ExtractionFailed`, `EmbeddingFailed`)
- Generic try/except only at boundaries (worker, HTTP route)
- Log all exceptions with structlog before re-raising

---

## Architectural Principles

**Immutability**: `raw_memory` is append-only. Corrections create new `memory_items` with `supersedes_memory_id`, mark original `is_superseded=true`. No soft deletes via flags.

**Async-First**: All database (asyncpg + SQLAlchemy) and external API calls (Anthropic, Voyage) are async. Sync only for: external libs wrapped in `asyncio.to_thread()`, sync test fixtures, CLI entry point (via `asyncio.run()`).

**Stateless Services**: No in-process state shared across requests, no module-level mutable state (except config singleton + logging). Queue-based: API enqueues, worker processes (decoupled).

**Single Source of Truth**: Settings from environment only (no config files). Ranking formula, prompts, models each in one file. Routes import models, never duplicate definitions.

**Security by Default**: API keys in `SecretStr` (never log raw). `.env` in .gitignore, `.dockerignore` excludes .env. User input wrapped in `<user_input>...</user_input>` delimiters in all prompts. X-API-Key auth on `/v1/*` routes (middleware). Bound to localhost:8000 until Caddy reverse proxy (Phase 4).

---

## Task Execution Workflow

**Before writing code**: Read relevant IMPLEMENTATION_PLAN.md section. Check PROGRESS.md dependencies. Verify prerequisites exist and pass.

**While writing code**: Follow style conventions. Add type hints + docstrings. Log decisions with structlog. Test-driven when possible. Run `ruff check`, `black --check`, `mypy` before committing.

**After checkpoint**: Update PROGRESS.md (mark complete). Run tests. Verify gates. Commit: `feat(phase-X): checkpoint-name — description`. Report back with summary + blockers.

**Mandatory smoke test for bigger features**: Any feature that adds a new API route, Discord cog, background job, or integration (i.e. touches more than one module or introduces a new Docker service interaction) MUST be smoke-tested end-to-end before the checkpoint is considered complete. Smoke test means running the feature against the live Docker stack — not just unit tests — and confirming the full flow produces the expected output (e.g. a DM is sent, a DB record is created, a route returns the expected response). Unit tests alone are not sufficient for multi-module features.

Smoke test checklist:
1. Rebuild affected container(s) with `--no-cache` if any Python source changed
2. Apply migrations if schema changed (`docker compose --profile migrate run --rm migrate`)
3. Run the feature end-to-end and check logs for success events, not just absence of errors
4. Query the API or DB directly to confirm state was persisted correctly
5. Confirm idempotency: re-running the feature produces the correct result (no duplicate records, no crash)

**When blocked** (same issue 3+ times): Stop. Document blocker. Ask user via AskUserQuestion. Propose 2–3 workarounds. Wait for guidance before retry.

---

## Git Workflow

**Commit format**: `<type>(<scope>): <description>`
- **type**: feat, fix, refactor, test, docs, chore
- **scope**: phase-1, phase-2, core, pipeline, api, retrieval
- **description**: short, imperative ("add X" not "added X")
- **Example**: `feat(phase-1): add worker polling with stale lock reclaim`

**Branches**: Start on `main`. Create feature branch if needed. Never force push. Delete after merge.

**Code review**: All code reviewed before merge (solo review OK). Ensure: clean imports, type hints/docstrings, tests pass, no secrets/PII, actionable errors, structlog only.

---

## Critical Files

| File | Why | Approval Needed? |
|---|---|---|
| `src/core/models.py` | All 15 tables, PKs, FKs, indexes | Yes, if schema changes |
| `src/pipeline/worker.py` | SELECT FOR UPDATE SKIP LOCKED, retry logic | Yes, if polling changes |
| `alembic/versions/0001_initial_schema.py` | HNSW/GIN indexes, type checking | Yes, always |
| `src/retrieval/search.py` | Hybrid search formula, ranking | Yes, if ranking changes |
| `src/llm/prompts.py` | Extraction prompts, prompt injection defense | Yes, if prompts change |

---

## Common Pitfalls (do NOT do these)

❌ **Don't**: Log settings object directly (contains API keys)
✅ **Do**: Log only specific non-sensitive fields

❌ **Don't**: Use sync code in async context (e.g., `time.sleep()` in worker)
✅ **Do**: Use `await asyncio.sleep()` or `asyncio.to_thread()` for blocking calls

❌ **Don't**: Share SQLAlchemy sessions across async tasks
✅ **Do**: Create new session per task via `async with get_db() as session:`

❌ **Don't**: Update `importance_score` column directly
✅ **Do**: Update `base_importance` or `dynamic_importance`, let GENERATED column recompute

❌ **Don't**: Use `INSERT OR REPLACE` for deduplication
✅ **Do**: Use `INSERT ... ON CONFLICT DO NOTHING` (explicit, safer)

❌ **Don't**: Hardcode ranking weights in code
✅ **Do**: Read from settings (env vars)

❌ **Don't**: Mock LLM calls in some tests, hit real API in others
✅ **Do**: Always mock, never hit production in tests

❌ **Don't**: Use Supabase PgBouncer pooler URL (port 6543) for worker — `SELECT FOR UPDATE SKIP LOCKED` breaks
✅ **Do**: Use Supabase direct connection (port 5432) for all services. PgBouncer optimization deferred to Phase 4

❌ **Don't**: Create migration with `alembic revision --autogenerate` and trust it
✅ **Do**: Autogenerate, then manually verify HNSW/GIN/composite PKs/UUIDs

❌ **Don't**: Use `Base.metadata.create_all()` against Supabase to create schema
✅ **Do**: Always use `alembic upgrade head`. The embedding column is created as JSONB by SQLAlchemy (placeholder type), but the actual DDL (via Alembic) converts it to `vector(1024)` at runtime. Using `create_all()` leaves embeddings as JSONB, breaking vector operations.

---

## CP4-6 Implementation Gotchas

**Session 2 (2026-03-14)**: Checkpoints 4–6 implementation revealed critical issues with database compatibility, async patterns, and mocking.

### JSONB Incompatibility with SQLite

❌ **Don't**: Use `JSONB` type directly in SQLAlchemy ORM
✅ **Do**: Use `.with_variant()` pattern for cross-database compatibility

```python
JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")
metadata_: Mapped[Optional[dict]] = mapped_column(JSON_TYPE, nullable=True, name="metadata")
```

**Why**: Tests run on SQLite (no JSONB), production on PostgreSQL. SQLite compilation error: "can't render element of type JSONB". Applied to `metadata_`, `embedding`, `alternatives` in all models.

### UUID Generation Pattern

❌ **Don't**: Use `default=lambda: str(__import__("uuid").uuid4())` (string type)
✅ **Do**: Use `default=uuid4` (UUID object, SQLAlchemy handles conversion)

```python
id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
```

**Why**: Type mismatch between `str()` and `UUID(as_uuid=True)` which expects a UUID object. SQLAlchemy's `UUID(as_uuid=True)` automatically calls `uuid4()` and stores as string in DB.

### Tenacity + Structlog Incompatibility

❌ **Don't**: Use `after=after_log(logger, "warning")` in `@retry` decorator with structlog
✅ **Do**: Omit the `after` parameter; use structlog inside the function

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=8),
)
async def embed(self, text: str) -> list[float]:
    # ... tenacity will retry on exception
    # log inside function if needed
```

**Why**: Tenacity's `after_log()` expects stdlib logging; structlog uses a different logger interface. TypeError on level comparison. Solution: let tenacity handle retries, log at function level if needed.

### AsyncContextManager Mocking Pattern

❌ **Don't**: Mock `get_db` as `AsyncMock()` returning session directly
✅ **Do**: Use `@asynccontextmanager` decorator and patch with the manager instance

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def mock_get_db():
    yield async_session

with patch("src.pipeline.worker.get_db", return_value=mock_get_db()):
    await process_job(queue, mock_anthropic, mock_voyage)
```

**Why**: `get_db()` is an async context manager (`async with get_db() as session`), not a simple coroutine. The mock must return a context manager instance, not a coroutine. Without `@asynccontextmanager`, the mock is incompatible with the actual function signature.

### Transaction Boundaries in Async Tests

❌ **Don't**: Use `async with session.begin():` when test session already in transaction
✅ **Do**: Use `await session.flush()` for atomic operations; rely on fixture transaction

```python
# In worker.py:
async def store_memory_item(...) -> MemoryItem:
    memory_item = MemoryItem(...)
    session.add(memory_item)
    await session.flush()  # NOT session.begin()
```

**Why**: Test fixture creates async_session with active transaction (`await async_session.begin()`). Nested `session.begin()` in production code conflicts with test transaction. `flush()` persists changes within the outer transaction; rollback on test cleanup leaves queue in 'processing' for stale lock reclaim tests.

### Entity Resolver Field Naming

❌ **Don't**: Use inconsistent names like `entity_type` vs `type`, `alias_name` vs `alias`
✅ **Do**: Use ORM field names directly in code

```python
# In models.py: Entity has 'type' field
class Entity(Base):
    type: Mapped[str] = mapped_column(String(50))

# In entity_resolver.py: use 'type' not 'entity_type'
entity = Entity(name=name, type=entity_type)

# In models.py: EntityAlias has 'alias' field
class EntityAlias(Base):
    alias: Mapped[str] = mapped_column(String(255), unique=True)

# In entity_resolver.py: use 'alias' not 'alias_name'
alias_obj = EntityAlias(entity_id=entity.id, alias=name)
```

**Why**: Type hints on ORM models enforce the actual column names. Using different names in code causes AttributeError at runtime. Applied fixes: Entity.type (not entity_type), EntityAlias.alias (not alias_name).

### Idempotency via Unique Alias Creation

❌ **Don't**: Call `resolve_entities()` twice with same input — violates unique constraint
✅ **Do**: Create alias on first resolution so second call finds via exact match

```python
# Test approach:
result1 = await resolve_entities(async_session, [EntityExtract(name="Test", type="org")])
await async_session.commit()

# Manually create alias so second call uses exact match path
alias = EntityAlias(entity_id=result1[0].id, alias="Test")
async_session.add(alias)
await async_session.commit()

# Second call finds via alias match, not fuzzy match
result2 = await resolve_entities(async_session, [EntityExtract(name="Test", type="org")])
```

**Why**: `resolve_entities()` creates new Entity if fuzzy match fails. On second call with same name, the new create fails on unique constraint for Entity.name. Creating an explicit alias makes subsequent calls idempotent via the 3-step exact→fuzzy→insert logic (exact match short-circuits).

### Three-Failure Dead Letter Implementation

❌ **Don't**: Check `attempts >= 3` for dead letter; use `attempts == 3`
✅ **Do**: Increment first, then check: if `attempts >= 3`, move to dead letter

```python
# In claim_batch():
job.attempts += 1  # Now 1 on first claim

# In process_job():
if queue_row.attempts >= 3:  # True only on 3rd attempt (after 3 increments)
    await move_to_dead_letter(...)
else:
    queue_row.status = "pending"  # Reset for retry
```

**Why**: `attempts` is incremented on every claim (claim_batch increments before returning). On 3rd claim, `attempts=3`. So check `>= 3` not `== 3` to handle edge cases.

---

### Settings Singleton is None in Full Test Suite

❌ **Don't**: Import `settings` at module level in middleware/routes: `from src.core.config import settings`
✅ **Do**: Use a lazy `_get_settings()` helper that creates Settings on demand if None

```python
def _get_settings():
    from src.core import config
    if config.settings is None:
        config.settings = config.Settings()
    return config.settings
```

**Why**: `config.settings` is `None` at module level when no `.env` file exists (common in CI/tests). When `test_config.py` imports `from src.core.config import settings` during pytest collection, the module is cached as `settings=None`. Later, `monkeypatch.setenv` sets env vars, but any module that imported `settings` at its own module level still holds the `None` reference. The lazy helper re-creates Settings() the first time it's called during a test, by which point the env vars are available. Applied to: `auth.py`, `ranking.py`, `search.py`.

### Settings Singleton Captures .env Values When .env Exists

❌ **Don't**: Rely on the lazy `_get_settings()` pattern alone when a `.env` file is present on disk
✅ **Do**: Reset `config.settings` to a fresh instance in the autouse test fixture

```python
# In tests/conftest.py autouse fixture:
from src.core import config as _config
monkeypatch.setattr(_config, "settings", _config.Settings())  # re-reads from test env vars
```

**Why**: Once a `.env` file exists (created during actual deployment), `config.settings` is initialized at import time with production values (e.g. `API_KEY=openbrain-demo-secret-key-2026`). The lazy helper's `if config.settings is None` check short-circuits — it returns the production key, causing all API tests to get 401. The autouse fixture re-creates the singleton from test env vars (env vars take priority over .env in pydantic-settings). monkeypatch restores the original singleton after each test.

**For config validation tests**: When testing that missing vars raise `ValidationError`, pass `_env_file=None` to suppress `.env` fallback:
```python
Settings(_env_file=None)  # .env file won't supply the missing value
```

### pgvector ORM Type Must Use SQLite Variant for Tests

❌ **Don't**: Use `Vector(1024)` directly without a SQLite fallback
✅ **Do**: Use `.with_variant(JSON(), "sqlite")` for test compatibility

```python
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON

VECTOR_TYPE = Vector(1024).with_variant(JSON(), "sqlite")
```

**Why**: Tests run on SQLite (in-memory). `Vector(1024)` is a PostgreSQL-specific type with no SQLite support. Without the variant, SQLite table creation and embedding inserts fail. The production DB column is already `vector(1024)` (set by Alembic migration) — only the ORM type needs the variant. Applied in: `src/core/models.py`.

### pgvector asyncpg Codec Conflicts with SQLAlchemy Vector Type

❌ **Don't**: Call `register_vector(conn)` via an asyncpg event listener alongside `pgvector.sqlalchemy.Vector`
✅ **Do**: Use `pgvector.sqlalchemy.Vector` only — no `register_vector` needed

```python
# database.py — DO NOT add this:
# from pgvector.asyncpg import register_vector
# @event.listens_for(async_engine.sync_engine, "connect")
# def on_connect(dbapi_conn, _):
#     dbapi_conn.run_async(lambda conn: register_vector(conn))  ← CONFLICT
```

**Why**: `pgvector.sqlalchemy.Vector.process_bind_param` returns a text string like `'[0.1,0.2,...]'`. The `register_vector` asyncpg codec's `encode_vector()` function expects a `list[float]` or `np.ndarray` — it raises `TypeError` for strings. SQLAlchemy passes the string to the codec, which causes `asyncpg.exceptions.DataError: invalid input for query argument`. Without `register_vector`, asyncpg sends the string as PostgreSQL `text` type, and PostgreSQL casts it to `vector` natively. Applied fix: removed `register_vector` from `on_connect` in `database.py`.

---

### Worker Session Never Commits — All Changes Roll Back

❌ **Don't**: Use only `await session.flush()` in the worker pipeline and rely on the context manager to persist
✅ **Do**: Explicitly call `await session.commit()` after every terminal operation (success or dead letter)

```python
# In process_job() — after successful store:
await store_memory_item(session, raw, queue_row, extraction, embedding, entities)
await session.commit()  # REQUIRED — flush alone does not persist
logger.info("process_job_success")

# In move_to_dead_letter() — after flush:
await session.flush()
await session.commit()  # REQUIRED — or the dead letter write also rolls back

# In run() — after claim_batch:
jobs = await claim_batch(session)
await session.commit()  # Persist "processing" status before handing off
```

**Why**: SQLAlchemy's `AsyncSession` context manager (`async with session:`) calls `session.close()` on normal exit — it does NOT auto-commit. `flush()` only writes to the in-memory transaction buffer. Without `commit()`, every change in the session is rolled back when the context exits. The worker was logging `store_memory_item_success` and `process_job_success` but the DB remained empty because `close()` triggered an implicit rollback.

**Additional fix**: `process_job` opens its own inner session but received `queue_row` from the outer `claim_batch` session (a different session context). The inner session cannot track or commit changes to objects from another session. Fix: capture `queue_row.id` before entering the inner session, then re-fetch with `await session.get(RefinementQueue, queue_id)` inside the inner session so the object is tracked by the correct session.

### Raw SQL text() + UUID Type Mismatch on SQLite

❌ **Don't**: Use `text("... WHERE id = :v")` with `str(uuid_obj)` (dashes) in raw SQL on SQLite
✅ **Do**: Use SQLAlchemy Core `sa_delete(Model).where(Model.id == uuid_obj)` or `sa_update(Model).values(...)` — Core routes through the column's `process_bind_param`, handling dialect differences automatically

```python
from sqlalchemy import delete as sa_delete, update as sa_update

# Correct — Core handles UUID format per dialect
await session.execute(sa_delete(Entity).where(Entity.id == source_uuid))
await session.execute(
    sa_update(MemoryEntityLink)
    .where(MemoryEntityLink.entity_id == source_uuid)
    .values(entity_id=target_uuid)
)
```

**Why**: SQLite stores `UUID(as_uuid=True)` as 32-char hex without dashes. `str(uuid_obj)` = "abc-def-..." (with dashes, 36 chars) doesn't match. PostgreSQL accepts either format for native UUID columns. Using Core bypasses this divergence.

---

### ORM Identity Map Conflict After Raw SQL + session.delete()

❌ **Don't**: Call `session.delete(entity)` after raw SQL `UPDATE` on dependent tables — SQLAlchemy tries to blank-out FK references it sees in the stale identity map, crashing on PK columns
✅ **Do**: `session.expunge(entity)` before any raw SQL operations on dependent tables, then delete via Core

```python
# Capture what you need before expunge
source_name = source_entity.name
session.expunge(source_entity)  # Remove from identity map

# ... do raw SQL / Core operations on dependent tables ...

# Delete via Core — no ORM dependency processing, no identity map issues
await session.execute(sa_delete(Entity).where(Entity.id == source_uuid))
await session.commit()
```

**Why**: Raw SQL `UPDATE` statements bypass the ORM identity map. When a parent entity is later deleted via `session.delete()`, SQLAlchemy's unit-of-work processor sees stale child objects in the identity map still referencing the parent, and attempts to SET NULL on them — which fails when those FKs are part of a composite PK. `expunge()` removes the entity from tracking entirely; Core `sa_delete()` then issues a plain DELETE with no dependency processing.

### `session.refresh()` Required After flush+commit for server_default/onupdate Columns

❌ **Don't**: Return the ORM object after flush+commit without refreshing — `created_at` / `updated_at` will be expired and trigger async lazy-load failure
✅ **Do**: Call `await session.refresh(obj)` after flush+commit when the response accesses server-generated columns

```python
session.add(todo)
await session.flush()   # expires server_default/onupdate columns
await session.commit()
await session.refresh(todo)  # REQUIRED — eagerly reload created_at, updated_at
return todo  # now safe to access all columns
```

**Why**: After `session.flush()`, SQLAlchemy marks columns with `server_default` or `onupdate` as expired because their values were generated server-side. Accessing them (e.g. in `_todo_to_response(todo)`) triggers lazy loading. In an async session, lazy loading is unsupported and raises `MissingGreenlet`. This manifests as a hard-to-debug failure on the SECOND request in a test that shares a session — the first request works because the connection is fresh, but the second fails when the connection state changes after a commit. Applied in: `src/api/services/todo_service.py`.

### Optional Google Dependencies in `calendar.py`

❌ **Don't**: Import `google.auth` / `googleapiclient` at module level without guard
✅ **Do**: Wrap in `try/except ImportError` and set a `_GOOGLE_AVAILABLE` flag

```python
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    _GOOGLE_AVAILABLE = True
except ImportError:
    _GOOGLE_AVAILABLE = False
```

**Why**: Google Calendar deps are optional — the pulse job runs without them (falls back to `_empty_calendar_state()`). If the imports are unconditional, deploying without `google-api-python-client` installed crashes the entire module. The sync `GoogleCalendarClient` class is wrapped in `asyncio.to_thread()` at the public API boundary (`fetch_today_events()`), so the event loop is never blocked.

---

## Living Document Rule

**Update CLAUDE.md during implementation when you**:
- Discover a new pitfall or gotcha
- Make an architectural decision not covered here
- Find a section that's stale or wrong

Add a new subsection under Common Pitfalls, or edit existing sections. This file grows as we learn, rather than trying to front-load everything.

---

## Continuous Learning Rule

**At the end of every session**, update `/home/shu/.claude/projects/-home-shu-projects-open-brain/learning.md`:

1. **Identify**: Review features/tools touched (pgvector, OpenAI API, React hooks, etc.)
2. **Log**: Add new concepts implemented but not deeply understood to "Current Session Topics"
3. **Clean**: Move topics you've mastered to "Completed" section
4. **Context**: Keep topics concise — goal is a "lookup list" for independent study

This maintains a personal knowledge graph of what you've learned and what still needs deeper study.

---

## Deferred

Items intentionally deferred — revisit when thresholds are reached.

- **L3** — Hardcoded LIMIT 100 in search CTEs (`src/retrieval/search.py:61, 68, 125, 135`). Revisit when corpus exceeds 10k memories.
- **L4** — `merge_entities()` is 162 lines (`src/api/routes/entities.py:150–311`). Revisit if function exceeds 200 lines.
- **S1** — Narrow `--forwarded-allow-ips=172.0.0.0/8` to exact Docker subnet after Caddy reverse proxy is deployed (`docker network inspect openbrain`).

---

## Resources

- **Architecture**: `/home/shu/projects/open-brain/ARCHITECTURE.md` (design decisions, system overview)
- **Implementation plan**: `/home/shu/projects/open-brain/IMPLEMENTATION_PLAN.md` (tasks, phases, file structure)
- **Progress tracking**: `/home/shu/projects/open-brain/PROGRESS.md` (checkpoint tracking, gates)

---

## Module Ownership

Quick reference: which module owns which task.

| Task | Module | Key Files |
|---|---|---|
| Add API endpoint | `src/api/` | `routes/memory.py`, `routes/search.py`, `middleware/auth.py` |
| Todo API (CRUD + history) | `src/api/` | `routes/todos.py`, `services/todo_service.py` |
| Memory processing / pipeline | `src/pipeline/` | `worker.py`, `extractor.py`, `entity_resolver.py` |
| Change ranking / hybrid search | `src/retrieval/` | `search.py`, `ranking.py`, `context_builder.py` |
| Update prompts / LLM clients | `src/llm/` | `prompts.py`, `client.py` |
| Database schema | `src/core/` + `alembic/` | `models.py`, `database.py`, `versions/0001_initial_schema.py` |
| Shared config / settings | `src/core/` | `config.py` |
| Intelligence jobs (daily/weekly) | `src/jobs/` | `importance.py`, `synthesis.py` |
| CLI commands | `cli/` | `ob.py` |
| Discord bot loader + auto-ingest | `src/integrations/` | `discord_bot.py`, `kernel.py` |
| Discord core commands (/search, /digest, /status) | `src/integrations/modules/` | `core_cog.py` |
| Discord todo commands + interactive embeds | `src/integrations/modules/` | `todo_cog.py` |
| Discord RAG chat (Phase C) | `src/integrations/modules/` | `rag_cog.py` |
| Morning Pulse job + Discord cog (Phase D) | `src/integrations/modules/`, `src/jobs/` | `pulse_cog.py`, `pulse.py` |
| Google Calendar integration | `src/integrations/` | `calendar.py` |
| Tests | `tests/` | `conftest.py`, `test_*.py` |

---

## Repository Map Governance

Ensures architecture remains coherent as the codebase grows.

### Mandatory Pre-Work

Before implementing any task Claude must:

1. Read the Module Ownership table above
2. Identify the module responsible for the task
3. Verify the change belongs in that module

Claude must **never create new folders or modules** without first checking the table.

---

### When Module Ownership Must Be Updated

If a change modifies any of the following:

- folder structure
- module responsibilities
- architectural boundaries
- new services (worker/API/CLI)
- new core components or stack decisions

Claude must update the Module Ownership table above.

Example triggers:

```
new pipeline stage
new retrieval module
new database layer
new CLI subsystem
```

Minor internal refactors do **not** require updates.

---

### Agent Swarm Rule

If a change affects repository architecture, Claude must use an **Agent Swarm review process**.

Agents involved:

**Architect Agent**
- verifies architecture consistency
- ensures boundaries are preserved

**Implementation Agent**
- implements code changes

**Documentation Agent**
- updates Module Ownership table in CLAUDE.md
- updates ARCHITECTURE.md

Workflow:

```
Architect Agent
      ↓
Implementation Agent
      ↓
Documentation Agent
```

All three steps must complete before the task is considered finished.

---

### Swarm Conflict Resolution

If agents disagree about structure:

Priority order:

```
SPEC.md > ARCHITECTURE.md > CLAUDE.md > IMPLEMENTATION_PLAN.md
```

If ambiguity remains, Claude must escalate to the user.

---

### Repository Integrity Rule

Claude must not:

- create undocumented modules
- introduce parallel architecture
- duplicate responsibilities across folders

All new structural components must be reflected in the Module Ownership table and ARCHITECTURE.md.

---

### Validation Step

Before completing any structural change Claude must verify:

```
1. Code compiles
2. Tests pass
3. Module Ownership table in CLAUDE.md reflects the new structure
4. ARCHITECTURE.md reflects design changes
```

Failure to update the documentation is considered an **incomplete task**.
