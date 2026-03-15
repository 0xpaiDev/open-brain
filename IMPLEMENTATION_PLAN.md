# Open Brain Implementation Plan

**Version**: 2.0 (As-Built)
**Date**: 2026-03-15
**Status**: Phase 1 + 2 complete | 270 tests passing | Phase 3 starting

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
| Database | Supabase (managed PostgreSQL 15/16) + pgvector + pg_trgm | Vector + relational + fuzzy matching; pgvector/pg_trgm pre-installed; SSL mandatory; free tier covers MVP |
| LLM (extraction) | Claude Haiku (claude-haiku-4-5) | Cost-effective, strong JSON output, Anthropic credits |
| Embeddings | Voyage AI voyage-3 (1024 dims) | Single vendor, Anthropic-integrated, free tier 200M tokens/mo |
| Queue | PostgreSQL (SELECT FOR UPDATE SKIP LOCKED) | No external dependencies at MVP scale. **Use direct connection (port 5432), not PgBouncer pooler** |
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
POST /v1/memory  [source: "api" | "discord" | "cli"]
  → SHA-256 content-hash dedup (24h window) → 200 duplicate if match
  → raw_memory table (immutable, content_hash stored)
  → refinement_queue entry (pending)
  → HTTP 202 response (async processing)

background worker process:
  SELECT FOR UPDATE SKIP LOCKED (poll every 5s + jitter)
  → Normalize (rule-based text cleaning + tiktoken chunking)
  → Extract (Claude Haiku + 3 escalating prompts)
  → Validate (Pydantic schema + entity name normalization)
  → Embed (Voyage AI voyage-3 with tenacity retry)
  → Store (memory_items + entities + links + decisions + tasks)
  → Update queue status = 'done'

On failures:
  → 3-attempt retry with escalating prompts
  → move to failed_refinements after 3 failures
```

### Discord Integration (live, pre-Phase 3)
```
Discord message from allowlisted user
  → on_message() captures text
  → POST /v1/memory [source="discord", metadata={channel_id, author_id}]
  → 🧠 reaction on success, ❌ on error

/search <query> slash command
  → GET /v1/search [limit=5]
  → Results formatted as Discord Embed (score + 200-char preview)

/status slash command
  → GET /ready health probe
  → ✅ online or ❌ unreachable
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

## Database Schema (11 tables built; jobs table deferred to Phase 3)

All PKs are **UUID** (not BigInteger). All FKs must be checked at migration time.

> **As-Built note**: The original plan specified 12 tables. `jobs` (for scheduled job tracking) was deferred to Phase 3 — it is not needed until the intelligence layer is implemented. All other 11 tables are live in production.

### Immutable logs
- `raw_memory`: Original input text, source, chunking metadata, **`content_hash` VARCHAR(64)** (added via migration 0002)
- `retrieval_events`: Search access log (feeds importance)

### Refined knowledge
- `memory_items`: Extracted, normalized, ranked knowledge with importance score; embedding stored as `vector(1024)`
- `decisions`: Structured decision records with alternatives
- `tasks`: Task items with owner, due date, status

### Entity knowledge graph
- `entities`: Canonical entity names with types (person, org, project, concept, tool, place)
- `entity_aliases`: Variant names → canonical entity (globally unique constraint)
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

### Phase 1: Foundation ✅ AS BUILT — COMPLETE
**Goal**: Working ingestion → refinement → storage pipeline with basic search
**Actual duration**: ~59 hours | **Tests**: 89 passing | **Commits**: `db796de` → `a297aec` + 3 bug-fix commits

**Delivered (checkpoints 0–9):**
- CP0: `tests/conftest.py` — async SQLite fixtures, mock clients, test API client
- CP1: Full project scaffold (pyproject.toml, Dockerfile, docker-compose.yml, .env.example, Makefile)
- CP2: `src/core/config.py` (25 env vars, SecretStr, lazy singleton) + `src/core/database.py` (async engine, pool, health check)
- CP3: `src/core/models.py` (11 tables, UUID PKs, composite PKs, GENERATED importance_score, Vector/JSON variant) + `alembic/versions/0001_initial_schema.py` (HNSW + GIN manual DDL)
- CP4: `src/llm/client.py` + `src/llm/prompts.py` (3 escalating prompts, `<user_input>` injection defense)
- CP5: Full pipeline — normalizer, extractor (+ markdown fence fix), validator, embedder, entity_resolver
- CP6: `src/pipeline/worker.py` (SELECT FOR UPDATE SKIP LOCKED, FIX-2 stale lock reclaim, FIX-3 3-failure dead letter, SIGTERM handler)
- CP7: `src/api/routes/memory.py` (POST /v1/memory → 202) + auth middleware + health/ready endpoints
- CP8: `src/retrieval/search.py` + `src/retrieval/ranking.py` (hybrid 0.50×vector + 0.20×keyword + 0.20×importance + 0.10×recency, FIX-4 GIN expression, FIX-3 retrieval events)
- CP9: 89/89 tests green; `alembic/versions/0002_add_content_hash.py` (SHA-256 dedup on POST /v1/memory moved here from Phase 2); all 8 Phase 1 verification gates passed

**Verification gate**: All 8 gates passed ✅ (2026-03-15 smoke test)

### Phase 2: Retrieval + CLI ✅ AS BUILT — COMPLETE
**Goal**: Production-quality retrieval with context builder and CLI tool
**Actual duration**: ~17 hours | **Tests**: 270 passing (Phase 1 + 2) | **Commits**: `69b3963`, `bf3bc73`, `c451c50`

**Delivered (checkpoints 2.0–2.8):**
- CP2.0: `src/retrieval/context_builder.py` + GET /v1/search/context (token-budgeted LLM context, 8192-token default)
- CP2.1: Structured filter endpoints — `type_filter`, `entity_filter`, `date_from`, `date_to` on GET /v1/search
- CP2.2: Superseding chain — transactional `supersedes_memory_id` write + `is_superseded=true` on original
- CP2.3: Entity resolution — pg_trgm fuzzy match (0.92 threshold), exact alias match → fuzzy → new
- CP2.4: Entity endpoints — GET /v1/entities, GET /v1/entities/{id}, POST /v1/entities/merge (atomic with FK migration, expunge pattern), POST /v1/entities/{id}/aliases
- CP2.5: CLI — `cli/ob.py` with `ob ingest`, `ob search`, `ob worker --sync`, `ob context`, `ob health`
- CP2.6: Task + decision endpoints — GET/POST /v1/tasks, PATCH /v1/tasks/{id}, GET/POST /v1/decisions
- CP2.7: Dead-letter endpoints — GET /v1/dead-letters, POST /v1/dead-letters/{id}/retry (retry_count guard)
- CP2.8 *(bonus — moved from Phase 4)*: `src/integrations/discord_bot.py` — on_message ingestion, /search + /status slash commands, 🧠/❌ reactions, user-ID allowlist, httpx async HTTP client

**Not delivered (tracked as debt):**
- GET /v1/queue/status — listed in original plan but not implemented; dead-letters endpoint covers the primary use case
- GET /v1/memory/{id} — listed in Phase 1 plan but not implemented; search is the primary retrieval path

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

## File Structure (as-built, post-Phase 2)

```
open-brain/
├── .git/                           # git repository
├── .gitignore
├── .dockerignore
├── README.md                       # User-facing documentation
├── IMPLEMENTATION_PLAN.md          # This file (as-built)
├── PROGRESS.md                     # Task tracking and milestones
├── CLAUDE.md                       # Claude Code collaboration guidelines
├── Makefile                        # Development shortcuts
├── docker-compose.yml              # Services: api, worker, migrate + discord-bot profile
├── Dockerfile                      # Multi-stage build
├── pyproject.toml                  # Python project config + dependencies
├── uv.lock                         # Locked dependencies
├── .env.example                    # Environment variables template
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 0001_initial_schema.py  # MANUAL DDL: 11 tables, HNSW+GIN indexes
│       └── 0002_add_content_hash.py # content_hash VARCHAR(64) + B-tree index
├── src/
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app factory
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── memory.py           # POST /v1/memory (202, SHA-256 dedup, supersedes)
│   │   │   ├── search.py           # GET /v1/search, GET /v1/search/context
│   │   │   ├── entities.py         # GET list/id, POST merge, POST aliases
│   │   │   ├── tasks.py            # GET list, POST create, PATCH status
│   │   │   ├── decisions.py        # GET list, POST create
│   │   │   ├── queue.py            # GET /v1/dead-letters, POST /v1/dead-letters/{id}/retry
│   │   │   └── health.py           # GET /health (liveness), GET /ready (readiness)
│   │   └── middleware/
│   │       ├── __init__.py
│   │       ├── auth.py             # X-API-Key header check (lazy singleton)
│   │       └── logging.py          # structlog middleware
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py               # pydantic-settings + validation (lazy singleton)
│   │   ├── database.py             # async engine + session factory (pool_size=3)
│   │   └── models.py               # 11 SQLAlchemy ORM models (Vector/JSON variant)
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── worker.py               # Polling loop: claim → normalize → extract → embed → store
│   │   ├── normalizer.py           # Unicode NFC + tiktoken chunking (2000 tok max)
│   │   ├── extractor.py            # Claude Haiku extraction (markdown fence fix)
│   │   ├── validator.py            # Pydantic validation + entity name normalization
│   │   ├── embedder.py             # Voyage AI voyage-3 (tenacity retry)
│   │   └── entity_resolver.py      # exact alias → pg_trgm fuzzy (0.92) → new entity
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── search.py               # Hybrid SQL (HNSW+GIN FULL OUTER JOIN), dedup, event log
│   │   ├── ranking.py              # recency_score + combined_score (settings-based weights)
│   │   └── context_builder.py      # Token-budgeted LLM context (8192 default)
│   ├── jobs/                       # Phase 3 — DIRECTORY NOT YET CREATED
│   ├── integrations/
│   │   ├── __init__.py
│   │   └── discord_bot.py          # Discord client: on_message, /search, /status
│   └── llm/
│       ├── __init__.py
│       ├── client.py               # AnthropicClient + VoyageEmbeddingClient singletons
│       └── prompts.py              # 3 escalating prompts + <user_input> injection defense
├── cli/
│   ├── __init__.py
│   └── ob.py                       # ob ingest | search | context | worker --sync | health
└── tests/
    ├── __init__.py
    ├── conftest.py                 # Async SQLite fixtures, mock clients, test_client
    ├── test_config.py              # Settings validation, SecretStr
    ├── test_database.py            # Health check, session management
    ├── test_models.py              # UUID PKs, composite PKs, FKs
    ├── test_llm.py                 # AnthropicClient, VoyageClient, prompt injection
    ├── test_pipeline.py            # normalizer, extractor, validator, embedder, entity_resolver
    ├── test_worker.py              # Stale lock reclaim (FIX-2), 3-failure dead letter (FIX-3)
    ├── test_ingestion.py           # POST /v1/memory: auth, 202, dedup
    ├── test_ranking.py             # recency_score, combined_score, weight validation
    ├── test_search.py              # Hybrid search, filters, retrieval event logging
    ├── test_context_builder.py     # Token budget, truncation, item inclusion
    ├── test_entities.py            # Merge (conflict resolution), aliases, listing
    ├── test_tasks.py               # CRUD, status validation
    ├── test_decisions.py           # CRUD, memory_id filtering
    ├── test_queue.py               # Dead-letter listing, retry guard
    ├── test_cli.py                 # ingest, search, worker --sync, context
    └── test_discord_bot.py         # Message ingestion, search command, status command
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

## Next Steps (as of 2026-03-15)

Phase 1 and Phase 2 are complete. Phase 3 begins now.

1. **Phase 3.1**: Implement `src/jobs/importance.py` — aggregate `retrieval_events`, update `dynamic_importance` on `memory_items` (daily at 3 AM)
2. **Phase 3.2**: Implement `src/jobs/synthesis.py` — cluster memories by entities, call Claude for weekly report, store as `memory_item` with `source="synthesis"`
3. **Phase 3.3**: Synthesis prompt engineering in `src/llm/prompts.py`
4. **Phase 3.4**: Observability — structlog events for ingestion rate, error rate, queue depth
5. **Phase 4**: Docker Compose production config, Caddy reverse proxy, rate limiting, pg_dump backups, automated integration tests, API docs

**Known technical debt (Phase 2 gaps):**
- GET /v1/memory/{id} — not implemented; search is the primary path
- GET /v1/queue/status — not implemented; GET /v1/dead-letters covers the use case
- No automated integration test against real Supabase (smoke test is manual)

---

## References

- Original spec: `open-brain-implementation-plan.docx`
- Architectural review: Lead Architect + Senior Architect critique
- Plan file: `/home/shu/.claude/plans/atomic-puzzling-zephyr.md`
