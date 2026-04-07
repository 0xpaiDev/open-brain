# Open Brain — System Documentation

**Version**: 1.0 (Post-Phase 5)
**Deployment**: GCP e2-medium · `34.118.55.10` · Supabase (session-mode pooler, port 5432)
**Status**: Production · 410 tests passing · All 5 phases complete

---

## What It Is

Open Brain is an async, durable personal memory system. It captures natural language input — from an API, CLI, Discord, or Claude Code sessions — extracts structured knowledge using Claude, embeds it with Voyage AI, and stores it in PostgreSQL. The stored memory can then be searched semantically and injected as context into any LLM session.

The system is append-only and query-first: raw input is never mutated, corrections create superseding records, and retrieval is driven by a hybrid ranking formula that combines semantic similarity, keyword relevance, usage frequency, and recency. Every component is async, stateless, and queue-decoupled.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ Ingestion Layer                                                  │
│   REST API  ·  CLI (ob ingest)  ·  Discord bot  ·  Stop hook   │
└────────────────────┬────────────────────────────────────────────┘
                     │  POST /v1/memory
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ raw_memory (append-only)                                         │
│   SHA-256 content-hash dedup · source tag · chunk metadata      │
└────────────────────┬────────────────────────────────────────────┘
                     │  enqueue
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ refinement_queue (durable job queue)                             │
│   pending → processing → done / failed                          │
│   stale lock reclaim: locked_at < now() − 5 min                 │
└────────────────────┬────────────────────────────────────────────┘
                     │  SELECT FOR UPDATE SKIP LOCKED
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ Worker Pipeline (async, idempotent)                              │
│   1. Normalize   — unicode NFC + tiktoken chunking (2000 tok)   │
│   2. Extract     — Claude Haiku, 3 escalating prompts           │
│   3. Validate    — Pydantic v2, entity name normalization        │
│   4. Embed       — Voyage AI voyage-3 (1024 dims), tenacity     │
│   5. Resolve     — exact alias → pg_trgm fuzzy (0.92) → new    │
│   6. Store       — memory_items + entities + links (tx)         │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ Structured Memory (12 tables)                                    │
│   memory_items · entities · entity_aliases · entity_relations   │
│   decisions · tasks · retrieval_events · refinement_queue       │
│   failed_refinements · raw_memory · memory_entity_links         │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ Retrieval Layer                                                  │
│   Hybrid rank: 0.50×vector + 0.20×keyword +                     │
│                0.20×importance + 0.10×recency                   │
│   Token-budgeted context builder (default 8 192 tokens)         │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ Access Layer                                                     │
│   MCP server (fastmcp) · ob chat CLI · REST API                 │
└─────────────────────────────────────────────────────────────────┘
```

**Nightly/weekly background jobs (external cron, not in-process)**:
- 3 AM daily: `src/jobs/importance.py` — aggregates retrieval_events, updates `dynamic_importance`
- 2 AM Sunday: `src/jobs/synthesis.py` — Claude synthesis of past 7 days, stored as MemoryItem

---

## Tech Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Language | Python 3.12 | Async, typed, FastAPI ecosystem |
| API framework | FastAPI + uvicorn | Async HTTP, auto-docs, dependency injection |
| Database | Supabase (PostgreSQL 15/16) | Managed; pgvector + pg_trgm pre-installed; free tier covers MVP |
| Vector extension | pgvector (HNSW, cosine) | Native PostgreSQL vector search |
| Fuzzy match | pg_trgm | Entity resolution without external NLP service |
| ORM | SQLAlchemy 2.0 (async) | Full async, Pydantic v2 integration |
| Migrations | Alembic (manual DDL) | Required for custom HNSW/GIN index definitions |
| Async driver | asyncpg | PostgreSQL native async protocol |
| LLM (extraction) | Claude Haiku (`claude-haiku-4-5`) | Cost-effective, strong JSON output |
| LLM (synthesis) | Claude Haiku (→ Opus in production) | Weekly digest; configurable via `SYNTHESIS_MODEL` |
| Embeddings | Voyage AI voyage-3 (1024 dims) | Single vendor, 200M tokens/month free tier |
| Job queue | PostgreSQL `SELECT FOR UPDATE SKIP LOCKED` | No external dependencies at MVP scale |
| CLI | typer | Simple, reuses API client |
| Config | pydantic-settings | Env-based, `SecretStr` for keys |
| Logging | structlog | Structured, machine-parseable |
| Retry | tenacity | Embedding retries (3×, exponential backoff) |
| Rate limiting | slowapi | Per-IP limits; configurable via env vars |
| Reverse proxy | Caddy | Auto-TLS, gzip, security headers |
| MCP | fastmcp | Exposes 3 tools for Claude Code integration |
| Testing | pytest + pytest-asyncio + SQLite | Full suite without external dependencies |
| Package manager | uv | Fast, lockfile-based |
| Containerization | Docker + Docker Compose (profiles) | api, worker, discord-bot, caddy profiles |

---

## Key Features

### Async Ingestion Pipeline
Every ingested text goes through a 6-stage pipeline: normalize (unicode + chunking) → extract (Claude, structured JSON) → validate (Pydantic schema + entity normalization) → embed (Voyage AI 1024-dim vector) → resolve (entity knowledge graph) → store (transactional). The pipeline runs in a separate worker process, decoupled from the API via a PostgreSQL queue.

**Failure handling**: Extraction failures retry with escalating prompts (3 attempts). After 3 failures, the job moves to `failed_refinements` (dead letter queue), reviewable via `GET /v1/dead-letters`. Stale locks (crashed workers) are reclaimed after 5 minutes by the next poll cycle.

**Content-hash deduplication**: `POST /v1/memory` computes a SHA-256 hash of normalized text and rejects duplicates within a 24-hour window, returning `status: "duplicate"` with the original `raw_id`.

### Hybrid Search & Ranking
Retrieval combines four signals:

```
combined_score = 0.50 × vector_similarity   (HNSW cosine distance)
              + 0.20 × keyword_relevance    (FTS via GIN index)
              + 0.20 × importance_score     (GENERATED: 0.6×base + 0.4×dynamic)
              + 0.10 × recency_score        (exponential decay, 30-day half-life)
```

All weights are configurable via environment variables. The recency and importance weights can be tuned without redeployment.

### Dynamic Importance
Every search result access is logged to `retrieval_events`. A nightly cron job aggregates these events with exponential decay (older accesses count less) and updates `dynamic_importance` on each `memory_item`. Memories that are searched frequently float to the top of future results.

### Entity Knowledge Graph
The pipeline extracts named entities (people, orgs, projects, concepts, tools, places) from every memory and resolves them against a canonical entity graph using three-step logic:
1. Exact alias match (fastest, idempotent)
2. pg_trgm fuzzy match at 0.92 similarity threshold (handles typos, abbreviations)
3. Create new canonical entity

Entities support aliases, typed relations (`works_on`, `owns`, `related_to`, `decided_by`), and merging (`POST /v1/entities/merge`) — which atomically migrates all links, aliases, and relations from a source entity to a target entity.

### Weekly Synthesis
A Sunday cron job fetches the past 7 days of memories, groups them by entity, and calls Claude to produce a structured digest: themes, key decisions, open tasks, and entity mentions. The digest is stored as a `MemoryItem` with `type="context"` and `base_importance=0.8`, making it surfaceable in future searches.

### Multi-Client Access
| Client | How |
|--------|-----|
| REST API | `X-API-Key` authenticated endpoints on `/v1/*` |
| CLI (`ob`) | `ob ingest`, `ob search`, `ob context`, `ob chat`, `ob worker`, `ob health` |
| MCP server | `search_memory`, `get_context`, `ingest_memory` tools — auto-loaded by Claude Code |
| Discord bot | `on_message` auto-capture (DMs from allowlisted users) + `/search`, `/digest`, `/status` slash commands |
| Claude Code stop hook | `scripts/capture_claude_code.py` — auto-ingests every Claude Code session on completion |

### Superseding (Append-Only Corrections)
Corrections never overwrite existing memories. The API accepts an optional `supersedes_id`: the original `memory_item` is marked `is_superseded=true`, and the new item links to it via `supersedes_memory_id`. Full audit trail is preserved.

---

## Installation & Setup

### Prerequisites
- Docker + Docker Compose
- Supabase account (free tier sufficient)
- Anthropic API key
- Voyage AI API key

### 1. Clone and configure

```bash
git clone <repo>
cd open-brain
cp .env.example .env
# Edit .env with your keys — see Configuration Reference below
```

### 2. Run database migrations

```bash
docker compose run --rm migrate
# Runs: alembic upgrade head
# Creates all 12 tables, HNSW index, GIN index, pg_trgm extension
```

### 3. Start services

```bash
# API + worker (production)
docker compose up -d api worker

# With Discord bot
docker compose --profile discord up -d

# With Caddy (HTTPS — requires DOMAIN env var)
docker compose --profile caddy up -d
```

### 4. Verify

```bash
curl http://localhost:8000/health          # → {"status": "ok"}
curl http://localhost:8000/ready           # → {"status": "ready"}

ob health                                  # CLI equivalent
ob ingest "test memory"                    # Ingest via CLI
ob search "test"                           # Search
```

### 5. Register cron jobs (production)

```bash
# Edit crontab on host
crontab -e

# Add:
0 3 * * * docker compose -f /path/to/docker-compose.yml run --rm api python -m src.jobs.importance
0 2 * * 0 docker compose -f /path/to/docker-compose.yml run --rm api python -m src.jobs.synthesis
30 3 * * * /path/to/scripts/backup.sh
```

### 6. MCP server (Claude Code integration)

Create `.mcp.json` in the project root (gitignored — contains API key):
```json
{
  "mcpServers": {
    "open-brain": {
      "command": "python",
      "args": ["-m", "src.mcp_server"],
      "env": {
        "OPENBRAIN_API_URL": "http://localhost:8000",
        "OPENBRAIN_API_KEY": "<your-api-key>"
      }
    }
  }
}
```

---

## API Reference

All `/v1/*` endpoints require `X-API-Key: <api_key>` header.

### Memory

| Method | Path | Description | Response |
|--------|------|-------------|----------|
| `POST` | `/v1/memory` | Ingest raw text (async). Returns immediately. | `202` `{raw_id, status, supersedes_id}` |
| `GET` | `/v1/memory/{id}` | Fetch a processed MemoryItem by ID. | `200` MemoryItemResponse |

**Request body** (`POST /v1/memory`):
```json
{
  "text": "...",
  "source": "api",
  "metadata": {},
  "supersedes_id": null
}
```

### Search

| Method | Path | Description | Response |
|--------|------|-------------|----------|
| `GET` | `/v1/search` | Hybrid search, ranked results. | `200` `{results[], query}` |
| `GET` | `/v1/search/context` | Token-budgeted LLM context string. | `200` `{context, tokens_used, tokens_budget, items_included, items_truncated, query}` |

**Query parameters** (both endpoints):
- `q` (required) — search query
- `limit` — max results (default 10)
- `type_filter` — filter by memory type
- `entity_filter` — filter by entity name (case-insensitive)
- `date_from` / `date_to` — ISO 8601 datetime range

### Entities

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/entities` | List entities (filter by `q`, paginate) |
| `GET` | `/v1/entities/{id}` | Get entity with aliases and relations |
| `POST` | `/v1/entities/{id}/aliases` | Add alias to entity |
| `POST` | `/v1/entities/merge` | Atomically merge source → target entity |

### Tasks & Decisions

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/tasks` | List tasks (filter by status, entity) |
| `POST` | `/v1/tasks` | Create task |
| `PATCH` | `/v1/tasks/{id}` | Update task status |
| `GET` | `/v1/decisions` | List decisions (filter by memory_id) |
| `POST` | `/v1/decisions` | Create decision |

### Queue & Operations

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/queue/status` | Queue depth by status + oldest locked_at |
| `GET` | `/v1/dead-letters` | List failed refinement jobs |
| `POST` | `/v1/dead-letters/{id}/retry` | Re-enqueue failed job (max 3 retries) |
| `POST` | `/v1/synthesis/run` | Trigger weekly synthesis job immediately |

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness probe — always 200 |
| `GET` | `/ready` | Readiness probe — 200 if DB reachable, 503 otherwise |

---

## Data Flow

### Ingestion Flow

```
POST /v1/memory {text, source}
  │
  ├── Normalize text: lowercase, collapse whitespace
  ├── SHA-256 hash → check raw_memory for duplicate within 24h
  │   └── If found: return 200 {status: "duplicate", raw_id: existing_id}
  │
  ├── INSERT raw_memory (raw_text, source, content_hash, metadata)
  ├── INSERT refinement_queue (raw_id, status="pending")
  └── Return 202 {status: "queued", raw_id}

Worker (polls every 5s + jitter):
  SELECT id, raw_id, attempts FROM refinement_queue
  WHERE status='pending'
     OR (status='processing' AND locked_at < now() - interval '5 minutes')
  FOR UPDATE SKIP LOCKED
  LIMIT 5

  For each job:
    UPDATE refinement_queue SET status='processing', locked_at=now(), attempts+=1

    pipeline.normalize(raw_text)  →  chunks[]
    pipeline.extract(chunk)       →  ExtractionResult {type, content, entities[], decisions[], tasks[], base_importance}
    pipeline.validate(result)     →  normalized entities, deduped
    pipeline.embed(content)       →  vector[1024]
    pipeline.resolve(entities)    →  Entity[] (from DB or new)
    pipeline.store(...)           →  memory_item + entity links + decisions + tasks

    UPDATE refinement_queue SET status='done'
    COMMIT

  On failure (attempts < 3):
    UPDATE refinement_queue SET status='pending'  # retry with escalating prompt

  On failure (attempts >= 3):
    INSERT failed_refinements (queue_id, error_reason, raw_output)
    UPDATE refinement_queue SET status='failed'
    COMMIT
```

### Retrieval Flow

```
GET /v1/search?q=<query>&limit=10

  1. VoyageEmbeddingClient.embed(query)  →  query_vector[1024]

  2. SQL: two CTEs + FULL OUTER JOIN
     ├── vector_cte: ORDER BY embedding <=> query_vector LIMIT 100
     └── kw_cte:     WHERE to_tsvector('english', content) @@ plainto_tsquery(query) LIMIT 100

  3. Hybrid score per result:
     combined = 0.50 * vector_score
              + 0.20 * keyword_score
              + 0.20 * importance_score
              + 0.10 * recency_score

  4. Deduplicate by content_hash, sort by combined DESC, LIMIT limit

  5. INSERT retrieval_events (memory_id, query_text, accessed_at) for each result

  6. Return {results: [...], query}
```

---

## Configuration Reference

All settings are read from environment variables. `.env` file is supported (loaded by pydantic-settings).

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | — | asyncpg URL (`postgresql+asyncpg://...`). **Must be Supabase direct connection (port 5432), not pooler (port 6543).** |

### API & Auth

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | — | Bearer key for `X-API-Key` header |
| `RATE_LIMIT_MEMORY` | `50/minute` | Rate limit for `POST /v1/memory` per IP |
| `RATE_LIMIT_SEARCH` | `100/minute` | Rate limit for `GET /v1/search*` per IP |
| `RATE_LIMIT_DEAD_LETTERS` | `5/minute` | Rate limit for dead-letter operations |

### LLM & Embeddings

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Anthropic API key (`SecretStr`) |
| `EXTRACTION_MODEL` | `claude-haiku-4-5-20251001` | Claude model for extraction pipeline |
| `SYNTHESIS_MODEL` | `claude-haiku-4-5-20251001` | Claude model for weekly synthesis. **Set to `claude-opus-4-6` in production.** |
| `VOYAGE_API_KEY` | — | Voyage AI API key (`SecretStr`) |
| `EMBEDDING_MODEL` | `voyage-3` | Voyage AI embedding model |
| `EMBEDDING_DIMENSIONS` | `1024` | Must be 1024 (only supported value) |

### Search Weights

| Variable | Default | Description |
|----------|---------|-------------|
| `VECTOR_WEIGHT` | `0.50` | Weight for vector similarity score |
| `KEYWORD_WEIGHT` | `0.20` | Weight for keyword/FTS score |
| `IMPORTANCE_WEIGHT` | `0.20` | Weight for importance_score |
| `RECENCY_WEIGHT` | `0.10` | Weight for recency decay score |
| `RECENCY_HALF_LIFE_DAYS` | `30` | Days until recency score halves |

### Worker

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKER_POLL_INTERVAL` | `5` | Seconds between queue polls |
| `WORKER_BATCH_SIZE` | `5` | Jobs claimed per poll cycle |
| `WORKER_LOCK_TTL_SECONDS` | `300` | Stale lock reclaim threshold (5 min) |

### Intelligence Jobs

| Variable | Default | Description |
|----------|---------|-------------|
| `IMPORTANCE_HALF_LIFE_DAYS` | `30` | Decay rate for retrieval event scoring |
| `IMPORTANCE_NORMALIZATION_FACTOR` | `5` | Divides raw event sum to normalize 0–1 |
| `SYNTHESIS_MAX_MEMORIES_PER_REPORT` | `50` | Max memories passed to synthesis LLM |

### Discord

| Variable | Default | Description |
|----------|---------|-------------|
| `DISCORD_BOT_TOKEN` | — | Discord bot token |
| `DISCORD_ALLOWED_USER_IDS` | — | Comma-separated list of Discord user IDs that can auto-ingest |
| `OPENBRAIN_API_URL` | `http://localhost:8000` | Base URL for the Open Brain API |
| `OPENBRAIN_API_KEY` | — | API key for the Discord bot to use |

### Deployment

| Variable | Default | Description |
|----------|---------|-------------|
| `DOMAIN` | — | Domain name for Caddy TLS provisioning |
| `LOG_LEVEL` | `info` | structlog level |

---

## Deployment Notes

### GCP + Supabase Setup

The production deployment runs on a GCP e2-small VM with Docker Compose. The database is Supabase-managed PostgreSQL.

**Critical**: Supabase's direct connection URL is IPv6-only. GCP VMs do not have IPv6 by default. Use the **session-mode pooler** (`aws-X-region.pooler.supabase.com:5432`) — it has IPv4 and supports `SELECT FOR UPDATE SKIP LOCKED`. The transaction-mode pooler (port 6543) does not support `SKIP LOCKED` and will break the worker.

**Alembic stamp**: If the database schema was created outside Alembic (e.g., via `create_all()`), synchronize the version table without re-running migrations:
```bash
alembic stamp head
```

**pgvector note**: Do not use `Base.metadata.create_all()` against Supabase. The `embedding` column is defined in the ORM as a placeholder type; Alembic's DDL sets it to `vector(1024)` at migration time. `create_all()` leaves it as `JSONB`, breaking all vector operations.

### Backup & Restore

```bash
# Backup (excludes asyncpg driver prefix)
./scripts/backup.sh

# Restore (prompts confirmation, runs verify query)
./scripts/restore.sh <backup_file.sql.gz>
```

Backups are retained for 30 days. The backup script strips the `+asyncpg` driver prefix from `DATABASE_URL` before calling `pg_dump`.

### pytest-asyncio Configuration

Tests require `asyncio_default_test_loop_scope = "module"` in `pyproject.toml` to avoid event loop scope mismatches between the engine fixture (module-scoped) and individual tests (function-scoped by default).

---

## Future Implementation Plan

The following items are not blocking but represent the next logical upgrade cycle.

### Code Quality (from tech-debt.md)
- **Extract `_parse_uuid()`** to `src/api/deps.py` — eliminates 4 duplicate implementations
- **Extract `_get_settings()`** to `src/core/settings_utils.py` — eliminates 8+ duplicate lazy-init helpers
- **Split `merge_entities()`** into focused sub-functions — improves testability of the merge operation
- **Use module-level `embedding_client`** in search routes — eliminates per-request object allocation

### Production Configuration
- **Switch `SYNTHESIS_MODEL` to `claude-opus-4-6`** — weekly digest quality requires stronger reasoning
- **Enable Caddy** (`--profile caddy`) with a domain for HTTPS

### Scaling & Multi-User
- **PgBouncer** (transaction mode) — deferred from Phase 4; requires replacing `SELECT FOR UPDATE SKIP LOCKED` with a different queue mechanism (e.g., Redis or explicit row-locking with application-level coordination)
- **Row-level security** — per-user memory isolation for multi-tenant deployments
- **Webhook / streaming ingestion** — real-time ingestion from external services without polling

### Observability
- **Metrics endpoint** — expose queue depth, processing latency, error rates via `/metrics` (Prometheus format)
- **Alerting** — notify on dead letter accumulation or worker silence beyond 2× poll interval
