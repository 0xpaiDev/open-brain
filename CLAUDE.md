# Claude Code Collaboration Guidelines

**Project**: Open Brain | **Owner**: Shu | **Last Updated**: 2026-03-13

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
| `src/core/models.py` | All 12 tables, PKs, FKs, indexes | Yes, if schema changes |
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
| Memory processing / pipeline | `src/pipeline/` | `worker.py`, `extractor.py`, `entity_resolver.py` |
| Change ranking / hybrid search | `src/retrieval/` | `search.py`, `ranking.py`, `context_builder.py` |
| Update prompts / LLM clients | `src/llm/` | `prompts.py`, `client.py` |
| Database schema | `src/core/` + `alembic/` | `models.py`, `database.py`, `versions/0001_initial_schema.py` |
| Shared config / settings | `src/core/` | `config.py` |
| Intelligence jobs (daily/weekly) | `src/jobs/` | `importance.py`, `synthesis.py` |
| CLI commands | `cli/` | `ob.py` |
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
