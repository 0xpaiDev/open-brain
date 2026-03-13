# Claude Code Collaboration Guidelines

**Project**: Open Brain
**Date**: 2026-03-13
**Owner**: Shu

---

## Overview

This document establishes how Claude Code agents should approach work on the Open Brain project. It covers decision-making, code style, architectural principles, and communication norms.

---

## Decision Authority & Escalation

### Decisions Claude Can Make (no approval needed)
- Code style, naming, formatting (within project conventions)
- Module organization and file structure (within planned architecture)
- Test implementation details and assertions
- Error messages and logging statements
- Dependency versions (within reasonable bounds)
- Documentation and comments
- Micro-optimizations that don't change logic

### Decisions Requiring Escalation to User
- Any change to the database schema (add/remove/rename tables or columns)
- Major architectural changes (e.g., swap from PostgreSQL queue to Redis)
- New external dependencies (LLM providers, cloud services, databases)
- Timeline changes or scope cuts
- Changes to API contract (request/response shapes)
- Security decisions (auth methods, encryption, key management)
- Phase re-ordering or skipping

**How to escalate**:
- Stop work if the issue is blocking
- Summarize the problem and 2-3 options with trade-offs
- Ask user via AskUserQuestion or direct text (depending on complexity)
- Wait for explicit approval before proceeding

---

## Code Style & Conventions

### Python
- **Version**: 3.12+
- **Format**: Black (line length 100 characters)
- **Lint**: ruff (all rules enabled, no exclusions)
- **Type hints**: Mandatory on all functions and methods
- **Async**: All I/O operations must be async (no sync blocking)
- **Logging**: structlog only, never print() or logging.basicConfig()

### FastAPI Routes
- All routes prefixed `/v1/`
- Path parameters and query params use lowercase_snake_case
- Request/response bodies are Pydantic models
- All 4xx/5xx responses documented in docstring
- Auth: X-API-Key header checked via middleware (not in route)

### SQLAlchemy ORM
- All PKs are UUID(as_uuid=True)
- Use `Column(..., nullable=False)` to enforce NOT NULL
- Use `ForeignKey(...)` with cascade options
- Use relationships for navigation, not raw joins (when possible)
- GENERATED columns defined in ORM but enforced at DDL in Alembic

### Testing
- Use pytest + pytest-asyncio
- Mock all external APIs (Anthropic, Voyage) — never hit production in tests
- Fixtures in conftest.py, not inline
- Test names follow `test_<function>_<scenario>`
- Assertions use plain `assert` (not custom matchers)

### Naming Conventions
- Database tables: `snake_case` (e.g., `memory_items`)
- Python modules: `snake_case` (e.g., `entity_resolver.py`)
- Python classes: `PascalCase` (e.g., `RefinementQueue`)
- Python constants: `UPPER_SNAKE_CASE` (e.g., `WEIGHT_VECTOR = 0.50`)
- Pydantic models: `PascalCase` + suffix (e.g., `MemoryItemResponse`, `MemoryItemCreate`)

### Error Handling
- Custom exception classes inherit from Exception (not BaseException)
- Named exceptions for expected failures (ExtractionFailed, EmbeddingFailed, ValidationFailed)
- Generic try/except only at task boundaries (worker process, HTTP route)
- All exceptions logged with structlog before re-raising

---

## Architectural Principles

### Immutability
- `raw_memory` is append-only, never deleted or updated
- Corrections create new `memory_items` with `supersedes_memory_id` pointing to original
- Original is marked `is_superseded = true` (for audit, not for hiding)
- No soft deletes via status flags (use explicit is_superseded)

### Async-First
- All database operations use asyncpg + SQLAlchemy async
- All external API calls (Anthropic, Voyage) are async
- No sync code except:
  - External library calls wrapped in `asyncio.to_thread()` (e.g., voyageai.Client)
  - Sync test fixtures (use `@pytest.fixture` not `@pytest_asyncio.fixture`)
  - CLI entry point (sync, calls async code via asyncio.run())

### Stateless Services
- No in-process state shared across requests
- No module-level mutable state (except config singleton + logging)
- Queue-based processing: API enqueues, worker processes (decoupled)

### Single Source of Truth
- Settings come from environment only (no config files)
- Ranking formula in one place (ranking.py constants)
- Prompts in one place (llm/prompts.py)
- Models in one place (core/models.py) — routes import from here, never duplicate definitions

### Security by Default
- API keys in SecretStr (never log raw values)
- `.env` excluded from git, `.dockerignore` excludes .env from image
- User input wrapped in `<user_input>` delimiters in prompts (injection defense)
- X-API-Key auth on all `/v1/*` routes (middleware, not per-route)
- Bound to localhost:8000 until Caddy reverse proxy added

---

## Task Execution Workflow

### Before Writing Code
1. Read the relevant section of IMPLEMENTATION_PLAN.md
2. Check PROGRESS.md for checkpoint dependencies
3. If checkpoint has prerequisites, verify they exist and pass
4. Summarize what needs to be done in a brief comment

### While Writing Code
1. Follow this file's style and naming conventions
2. Add type hints to all functions and methods
3. Add docstrings to modules, classes, and public functions
4. Log important decisions and transitions (structlog)
5. Test-driven when possible (write test first, then code)
6. Run `ruff check`, `black --check`, `mypy` before committing

### After Completing a Checkpoint
1. Update PROGRESS.md: mark checkpoint tasks complete with [ x ]
2. Run all tests for that checkpoint
3. Verify gate conditions in Verification section
4. Commit to git with message: `feat(phase-1): checkpoint-name — description`
5. Report back with checkpoint summary and any blockers

### When Blocked
- Do NOT try 3+ times to fix the same issue
- Stop, document the blocker clearly
- Ask user via AskUserQuestion (not in code)
- Propose 2-3 workarounds if possible
- Wait for guidance before retrying

---

## Communication Norms

### With User
- **Daily**: Brief summary of completed checkpoints + blockers (if any)
- **On decisions**: Escalate early, don't assume
- **On changes**: If a completed checkpoint needs rework, ask first
- **Tone**: Direct, terse, no filler ("Done X, next is Y" not "I have successfully completed...")

### With Other Agents (if using team)
- Use SendMessage tool for async coordination
- Share critical files (models, migration, worker) — ensure alignment before parallel work
- Test database-touching code together before parallel execution
- Report progress via SendMessage at major milestones

### In Code Comments
- **Why** not what (code is self-documenting)
- Flag architectural constraints (e.g., "GENERATED column, do not UPDATE directly")
- Note non-obvious dependencies (e.g., "GIN index query must match expression exactly")
- Leave FIXMEs only for post-MVP improvements, not blockers

---

## Git Workflow

### Commits
- One feature per commit
- Message format: `<type>(<scope>): <description>`
  - type: feat, fix, refactor, test, docs, chore
  - scope: phase-1, phase-2, core, pipeline, api, retrieval
  - description: short, imperative ("add worker poll loop" not "added")
- Example: `feat(phase-1): add worker polling with stale lock reclaim`

### Branches
- Start feature work on `main`
- Create feature branch if needed: `feature/phase-1-scaffold`
- Never force push (--force, --force-with-lease forbidden)
- Delete branches after merge

### Review
- All code reviewed before merge (even if solo)
- Self-review checklist:
  - [ ] Imports are clean (no unused, no circular)
  - [ ] All functions have type hints and docstrings
  - [ ] Tests exist and pass
  - [ ] No hardcoded secrets or PII
  - [ ] Error messages are actionable
  - [ ] Logging is structured (structlog, not print)

---

## Testing Requirements

### Unit Tests (required)
- All pure functions (ranking, normalization, validation)
- All ORM models (constraints, relationships)
- All Pydantic schemas (validation rules)

### Integration Tests (required)
- Pipeline stages in sequence (normalize → extract → validate → embed → store)
- Worker polling + job processing
- API routes (happy path + error cases)
- Search ranking (verify score formula)

### End-to-End Tests (Phase 1 only: minimal, Phase 4: comprehensive)
- Ingest → refine → search → context builder
- Run with real (mocked) API responses

### Coverage Target
- Phase 1: 70%+ overall, 95%+ on critical paths (worker, search)
- Phase 2+: 80%+ overall

---

## Critical Files (do NOT edit without care)

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

❌ **Don't**: Create migration with `alembic revision --autogenerate` and trust it
✅ **Do**: Autogenerate, then manually verify HNSW/GIN/composite PKs/UUIDs

---

## Success Criteria for Each Phase

### Phase 1
- All 8 verification gates pass
- 70%+ test coverage
- Code passes ruff + black + mypy
- API responds to requests end-to-end
- Worker successfully processes queue items

### Phase 2
- All Phase 1 gates still pass
- CLI tool works (ob add, ob search, ob tasks)
- Context builder formats output correctly
- Entity resolution works (fuzzy match, auto-merge)
- 80%+ test coverage

### Phase 3
- Dynamic importance updates daily
- Weekly synthesis runs and stores reports
- 85%+ test coverage
- Observability logging is structured and queryable

### Phase 4
- Docker Compose production config works
- VPS deployment successful
- Caddy reverse proxy handles TLS
- Backups and restore verification automated
- API docs auto-generated and complete

---

## Escalation Contacts

**For**: Architecture, scope, timeline, team decisions
**Contact**: User (Shu)
**Method**: Stop work, AskUserQuestion or direct message

**For**: Code review, best practices
**Contact**: User or Lead Architect (if team)
**Method**: SendMessage (if team) or ask in response

---

## Resources

- Implementation plan: `/home/shu/projects/open-brain/IMPLEMENTATION_PLAN.md`
- Progress tracking: `/home/shu/projects/open-brain/PROGRESS.md`
- Architectural review: `/home/shu/.claude/plans/atomic-puzzling-zephyr.md`
- Original spec: `open-brain-implementation-plan.docx` (archived, reference only)

---

## Version History

| Date | Author | Change |
|---|---|---|
| 2026-03-13 | Planning | Initial version, pre-Phase 1 |
