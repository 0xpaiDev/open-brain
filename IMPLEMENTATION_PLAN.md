# Open Brain Implementation Plan

**Version**: 1.0
**Date**: 2026-03-13
**Status**: Planning phase complete, ready for Phase 1 execution

---

## Overview

Open Brain is an AI-native organizational memory system that captures thoughts, decisions, and context into a structured PostgreSQL database with Claude-powered refinement and Voyage AI embeddings.

This implementation plan incorporates:
- Full architectural review by Senior Architect
- 5 critical bug fixes (UUID PKs, stale lock reclaim, retrieval log, GIN index, composite PKs)
- ~20 medium/high improvements (auth, security, observability, scaling)
- Voyage AI embeddings (single-vendor, Anthropic-backed, free tier 200M tokens/mo)

**Total scope**: ~113 hours across 4 phases (~6 weeks part-time)

---

## Stack Decisions

| Component | Technology | Why |
|---|---|---|
| Language | Python 3.12 | Async, type-safe, FastAPI ecosystem |
| Framework | FastAPI | Async HTTP, auto-docs, dependency injection |
| Database | PostgreSQL 16 + pgvector + pg_trgm | Vector + relational + fuzzy matching in one system |
| LLM (extraction) | Claude Haiku (claude-haiku-4-5) | Cost-effective, strong JSON output, Anthropic credits |
| Embeddings | Voyage AI voyage-3 (1024 dims) | Single vendor, Anthropic-integrated, free tier 200M tokens/mo |
| Queue | PostgreSQL (SELECT FOR UPDATE SKIP LOCKED) | No external dependencies at MVP scale |
| CLI | typer + requests | Simple, reuses API client, no new deps |
| Settings | pydantic-settings | Env-based config with validation, SecretStr for keys |
| Logging | structlog | Structured, machine-parseable logs |
| Migrations | Alembic | Async SQLAlchemy support, manual DDL for custom indexes |
| Testing | pytest + pytest-asyncio | Standard async testing |
| Package manager | uv | Fast, modern Python package management |

---

## Architecture Summary

### Ingestion Pipeline (async, durable queue-based)
```
POST /v1/memory
  → raw_memory table (immutable)
  → refinement_queue entry (pending)
  → HTTP 202 response (async processing)

background worker process:
  SELECT FOR UPDATE SKIP LOCKED (poll every 5s + jitter)
  → Normalize (rule-based text cleaning)
  → Extract (Claude Haiku + 3 escalating prompts)
  → Validate (Pydantic schema + entity name normalization)
  → Embed (Voyage AI voyage-3 with tenacity retry)
  → Store (memory_items + entities + links)
  → Update queue status = 'done'

On failures:
  → 3-attempt retry with escalating prompts
  → move to failed_refinements after 3 failures
```

### Retrieval (hybrid ranking)
```
GET /v1/search?q=...
  → Compute query embedding (Voyage AI)
  → Vector search (HNSW index, 100 results)
  → Keyword search (FTS with GIN index, 100 results)
  → Hybrid rank: 0.50×vector + 0.20×keyword + 0.20×importance + 0.10×recency
  → Context builder (token budget, ~8k default)
  → Return structured JSON

Side effect:
  → Log retrieval event (feeds dynamic importance)
```

### Intelligence Layer (async jobs, external cron)
```
Daily (3 AM):
  → Aggregate retrieval_events
  → Update dynamic_importance on memory_items

Weekly Sunday (2 AM):
  → Fetch memories from past 7 days
  → Cluster by entities
  → Claude synthesis (themes, decisions, status)
  → Store as weekly_report memory_item
```

---

## Database Schema (12 tables)

All PKs are **UUID** (not BigInteger). All FKs must be checked at migration time.

### Immutable logs
- `raw_memory`: Original input text, source, chunking metadata
- `retrieval_events`: Search access log (feeds importance)

### Refined knowledge
- `memory_items`: Extracted, normalized, ranked knowledge with importance score
- `decisions`: Structured decision records with alternatives
- `tasks`: Task items with owner, due date, status

### Entity knowledge graph
- `entities`: Canonical entity names with types (person, org, project, concept, tool, place)
- `entity_aliases`: Variant names → canonical entity
- `entity_relations`: Graph edges (works_on, owns, related_to, decided_by)
- `memory_entity_links`: M2M junction (PK: memory_id + entity_id)

### Processing state
- `refinement_queue`: Job queue with SELECT FOR UPDATE SKIP LOCKED polling
- `failed_refinements`: Dead letter queue with retry_count and escalation
- `entity_relations`: Graph edges (PK: from_entity + to_entity + relation_type + memory_id)

### Key design patterns
- **Append-only**: Corrections supersede originals via `supersedes_memory_id`, never overwrite
- **GENERATED column**: `importance_score = 0.6 × base_importance + 0.4 × dynamic_importance` (read-only, computed by Postgres)
- **Composite PKs**: Junction tables prevent duplicates on reprocessing

---

## Critical Fixes Applied

### FIX-1: UUID PKs everywhere
- All tables use `UUID(as_uuid=True)` from SQLAlchemy
- All FKs must match type and be audited in Alembic

### FIX-2: Stale lock reclaim in worker
```sql
WHERE status = 'pending' OR (status = 'processing' AND locked_at < now() - interval '5 minutes')
```
- Prevents crashed workers from permanently blocking jobs
- TTL is application-enforced, not DB-level

### FIX-3: Retrieval events table
- Feeds dynamic importance calculation
- Without this, `dynamic_importance` stays 0.0 forever
- Nightly job aggregates with configurable decay

### FIX-4: GIN index expression matching
- Index must use: `to_tsvector('english', content)`
- Query must use identical expression, no substitution
- Mismatch causes index miss → sequential scan

### FIX-5: Composite PKs on junctions
- `entity_relations(from_entity, to_entity, relation_type, memory_id)`
- `memory_entity_links(memory_id, entity_id)`
- Prevents duplicate rows on reprocessing
- Use `ON CONFLICT DO NOTHING` in pipeline

---

## Security Posture (Phase 1)

✅ **In Phase 1**:
- X-API-Key header auth on all `/v1/*` routes
- SecretStr for API keys (anthropic_api_key, voyage_api_key)
- `.env` excluded from git, `.dockerignore` excludes .env from image
- Prompt injection defense: wrap user input in `<user_input>` delimiters in all prompts
- API bound to localhost:8000 until Caddy reverse proxy added

⚠️ **Post-MVP (Phase 4)**:
- TLS termination via Caddy/nginx
- Rate limiting middleware
- Request/response logging with structlog
- Audit trail of schema changes

---

## Implementation Phases

### Phase 1: Foundation (44h + 15h for test-first = 59h estimated)
**Goal**: Working ingestion → refinement → storage pipeline with basic search, **with self-confirm test loop**

**Critical path**:
0. **Test Infrastructure First** (Checkpoint 0) — conftest.py with all fixtures before any source code
1. Project scaffold (pyproject.toml, Docker, .env)
2. Config + database setup (with test_config.py, test_database.py)
3. Models (with test_models.py to catch UUID/composite PK bugs)
4. Alembic migration (HNSW, GIN, retrieval_events, manual DDL)
5. LLM clients (with test_llm_clients.py, test_prompts.py)
6. Pipeline stages (with test_normalizer.py, test_extractor.py, test_validator.py, test_embedder.py, test_entity_resolver.py) — HIGH PRIORITY tests
7. Worker (with test_worker.py testing stale lock reclaim + 3-failure dead letter) — CRITICAL TESTS
8. Ingestion endpoint (with test_ingestion.py testing 202 response + auth) — HIGH PRIORITY tests
9. Basic search (with test_ranking.py, test_search.py testing hybrid ranking) — HIGH PRIORITY tests
10. Full test suite pass (pytest all tests green, >80% coverage on critical modules)

**Verification gate**: All 8 items in Verification Plan must pass before Phase 2

### Phase 2: Retrieval + CLI (31h)
**Goal**: Production-quality retrieval with context builder and CLI tool

- Context builder with token budget
- Structured filter endpoints (type, entity, date range)
- Superseding chain (corrections with is_superseded flag)
- Entity resolution (pg_trgm fuzzy match + auto-merge)
- Entity alias + merge endpoints
- CLI (typer) with --sync flag
- Task + decision endpoints
- Dead-letter review + retry with retry_count guard

### Phase 3: Intelligence Layer (21h)
**Goal**: Dynamic importance, weekly synthesis, observability

- Base importance scoring in extraction
- Daily importance decay job
- Weekly synthesis job (cluster → Claude → report)
- Observability: ingestion rate, error rate, queue depth logging

### Phase 4: Hardening + Deploy (17h)
**Goal**: VPS deployment with monitoring and backups

- Docker Compose production config
- Caddy reverse proxy setup
- Rate limiting middleware
- pg_dump cron backups + restore verification
- End-to-end integration tests
- API docs + CLI help + README

**Total**: ~113 hours base + ~15 hours for test-first approach = **~128 hours (~7 weeks at ~20 hours/week)**

---

## Known Constraints

1. **GENERATED column migration**: Changing the `importance_score` formula requires Alembic migration to drop + recreate the column. Documented in `models.py`.

2. **Custom indexes**: HNSW and GIN indexes cannot be autogenerated by Alembic. Always add `# MANUAL DDL` comment above these blocks in migrations.

3. **Scheduled jobs**: Weekly synthesis and daily importance jobs run as separate Docker services via host cron, NOT inside the FastAPI process. Prevents blocking async event loop.

4. **Voyage AI free tier**: 200M tokens/month. At ~50 memories/day with ~200 tokens per memory, this is ~300k tokens/month = well within free tier.

5. **Single-user assumption**: The system assumes a single author (`author` field in raw_memory). Multi-user support would require auth per user + row-level security in Phase 4+.

---

## Dependencies (pyproject.toml)

**Core**:
- fastapi >= 0.104.0
- sqlalchemy >= 2.0.0 (async, pydantic v2 integration)
- asyncpg >= 0.29.0 (postgres async driver)
- alembic >= 1.13.0
- pydantic >= 2.0.0
- pydantic-settings >= 2.0.0
- psycopg[binary] >= 3.1.0

**LLM/Embedding**:
- anthropic >= 0.21.0
- voyageai >= 0.2.0

**Pipeline**:
- tenacity >= 8.2.0 (retry logic)
- python-slugify >= 8.0.0 (entity name normalization)
- tqdm >= 4.66.0 (progress bars for jobs)

**CLI**:
- typer >= 0.9.0
- requests >= 2.31.0

**Logging**:
- structlog >= 23.2.0
- python-json-logger >= 2.0.0

**Testing**:
- pytest >= 7.4.0
- pytest-asyncio >= 0.21.0
- pytest-cov >= 4.1.0
- httpx >= 0.25.0 (async test client)

**Dev**:
- uv (package manager)
- black, ruff, mypy (linting)

---

## File Structure (pre-Phase 1)

```
open-brain/
├── .git/                           # git repository
├── .gitignore
├── .dockerignore
├── README.md                       # User-facing documentation
├── IMPLEMENTATION_PLAN.md          # This file
├── PROGRESS.md                     # Task tracking and milestones
├── CLAUDE.md                       # Claude Code collaboration guidelines
├── Makefile                        # Development shortcuts
├── docker-compose.yml              # Services: db, api, worker, migrate
├── Dockerfile                      # Multi-stage build
├── pyproject.toml                  # Python project config + dependencies
├── uv.lock                         # Locked dependencies
├── .env.example                    # Environment variables template
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 0001_initial_schema.py  # MANUAL DDL for indexes
├── src/
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app factory
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── memory.py           # POST /v1/memory, GET /v1/memory/{id}
│   │   │   ├── search.py           # GET /v1/search, GET /v1/search/context
│   │   │   ├── entities.py
│   │   │   ├── tasks.py
│   │   │   ├── decisions.py
│   │   │   ├── queue.py            # GET /v1/queue/status, /v1/dead-letters
│   │   │   └── health.py           # GET /health, GET /ready
│   │   └── middleware/
│   │       ├── __init__.py
│   │       ├── auth.py             # X-API-Key header check
│   │       └── logging.py          # structlog middleware
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py               # pydantic-settings + validation
│   │   ├── database.py             # async engine + session factory
│   │   └── models.py               # all 12 SQLAlchemy ORM models
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── worker.py               # Main polling loop
│   │   ├── normalizer.py           # Text cleaning + chunking
│   │   ├── extractor.py            # Claude Haiku extraction
│   │   ├── validator.py            # Pydantic validation
│   │   ├── embedder.py             # Voyage AI embedding
│   │   └── entity_resolver.py      # pg_trgm fuzzy match + merge
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── search.py               # Hybrid search SQL + execution
│   │   ├── ranking.py              # Score formula constants
│   │   └── context_builder.py      # Format results for LLM
│   ├── jobs/
│   │   ├── __init__.py
│   │   ├── importance.py           # Daily importance aggregation
│   │   └── synthesis.py            # Weekly synthesis job
│   └── llm/
│       ├── __init__.py
│       ├── client.py               # Anthropic + Voyage singletons
│       └── prompts.py              # All prompts + typed constants
├── cli/
│   ├── __init__.py
│   └── ob.py                       # Main CLI entry point (typer)
└── tests/
    ├── __init__.py
    ├── conftest.py                 # Async fixtures, mocked clients
    ├── test_ingestion.py
    ├── test_pipeline.py
    ├── test_search.py
    ├── test_ranking.py
    ├── test_entity_resolver.py
    └── test_context_builder.py
```

---

## Test-First Self-Confirm Loop (NEW — as of 2026-03-13)

**Why test-first over big-bang testing?**

The original plan had tests at Checkpoint 9 — after 40 hours of code. This meant bugs could compound silently and failures would be hard to trace.

**New approach**: Each checkpoint includes paired test file(s). Tests are written first (red), then code (green). End result:

```
Checkpoint 1 (scaffold) ✅
Checkpoint 2 (config + tests) ✅
Checkpoint 3 (models + tests) ✅
... → every checkpoint self-validates before next builds on it
Checkpoint 9 (full suite pass) ✅
```

**Critical tests to prioritize** (by risk from PROGRESS.md):
1. `test_worker.py` — Stale lock reclaim (FIX-2) + 3-failure dead letter (FIX-3)
2. `test_ingestion.py` — Core API contract
3. `test_pipeline.py` — Full end-to-end flow
4. `test_entity_resolver.py` — Fuzzy merge threshold
5. `test_ranking.py` + `test_search.py` — Hybrid ranking formula

**Coverage target**: >80% on critical modules (worker, search, ingestion routes).

---

## Next Steps

1. **Checkpoint 0**: Create `tests/conftest.py` with all fixtures
2. **Checkpoint 1**: All project files created, no code yet
3. **Phase 1 execution**: Follow task order, write tests first, then code
4. **Phase 1 verification**: All test suites pass + all 8 gates before Phase 2
5. **Iterate Phases 2–4**

---

## References

- Original spec: `open-brain-implementation-plan.docx`
- Architectural review: Lead Architect + Senior Architect critique
- Plan file: `/home/shu/.claude/plans/atomic-puzzling-zephyr.md`
