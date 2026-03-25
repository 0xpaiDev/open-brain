# Open Brain

An AI-native organizational memory system that captures thoughts, decisions, and context into a structured PostgreSQL database with Claude-powered refinement.

## Quick Start

### Prerequisites
- Python 3.12+
- Supabase account (free tier: https://supabase.com)
- Anthropic API key (Claude Haiku credits)
- Voyage AI API key (free tier: 200M tokens/month)
- Docker + Docker Compose

### Setup

```bash
# Clone and navigate
cd open-brain

# Copy environment template
cp .env.example .env
# Edit .env with your API keys and database URL

# Install dependencies
uv sync

# Apply migrations
SQLALCHEMY_URL=<your-supabase-url> alembic upgrade head

# Start the API
docker compose --profile api up -d

# Start the worker
docker compose --profile worker up -d

# Try the CLI
ob ingest "My first memory"
ob search "first"
```

### Running Tests

```bash
# Unit tests (SQLite — no Postgres required)
.venv/bin/pytest tests/ -v

# Integration tests (requires real Postgres)
INTEGRATION_TEST=1 pytest tests/test_integration.py -v
```

---

## What It Does

**Ingestion**: Send text via API or CLI → async pipeline extracts structure, entities, and importance

**Refinement**: Claude Haiku extracts type (insight, decision, task, context), entities, and metadata

**Search**: Hybrid ranking (vector + keyword + importance + recency) finds relevant memories

**Intelligence**: Daily importance updates + weekly summaries cluster memories by theme

---

## Architecture

### Services
- **api**: FastAPI HTTP server, routes all ingestion and search requests
- **worker**: Background process polling queue for refinement jobs
- **db**: Supabase (external managed PostgreSQL with pgvector + pg_trgm)
- **jobs**: Scheduled importance + synthesis jobs (via host cron)

### Database
- **15 tables**: raw_memory, memory_items, entities, entity_aliases, entity_relations, memory_entity_links, decisions, tasks, todo_items, todo_history, daily_pulse, rag_conversations, refinement_queue, failed_refinements, retrieval_events
- **Immutable**: raw_memory is append-only
- **Append-only**: Corrections supersede originals, never overwrite
- **Vector search**: HNSW index on 1024-dim embeddings (Voyage AI)
- **Full-text search**: GIN index on content with English tokenization

### Pipeline
```
POST /v1/memory
  → raw_memory (immutable)
  → refinement_queue (pending)
  → HTTP 202 (async)

background worker:
  1. Normalize (text cleaning, chunking)
  2. Extract (Claude Haiku → JSON)
  3. Validate (schema + entity name normalization)
  4. Embed (Voyage AI → 1024 dims)
  5. Store (memory_items + entities + relations)

On failure:
  → 3 escalating retry prompts
  → move to dead_letters after 3 failures
```

---

## API Endpoints

All endpoints require `X-API-Key` header (except `/health` and `/ready`). All endpoints use `/v1/` prefix.

### Memory
- `POST /v1/memory` — Ingest text
- `GET /v1/memory/{memory_id}` — Get memory with entity links

### Search
- `GET /v1/search?q=...` — Hybrid search
- `GET /v1/search/context` — Search + context builder (for LLM consumption)

### Entities
- `GET /v1/entities` — List entities
- `GET /v1/entities/{entity_id}` — Entity with aliases
- `POST /v1/entities/{entity_id}/aliases` — Add alias
- `POST /v1/entities/merge` — Merge two entities

### Tasks & Decisions
- `GET /v1/tasks` — List tasks
- `POST /v1/tasks` — Create task
- `PATCH /v1/tasks/{task_id}` — Update task
- `GET /v1/decisions` — List decisions
- `POST /v1/decisions` — Create decision

### Todos
- `POST /v1/todos` — Create todo
- `GET /v1/todos` — List todos
- `GET /v1/todos/{todo_id}` — Get todo
- `PATCH /v1/todos/{todo_id}` — Update todo
- `GET /v1/todos/{todo_id}/history` — Get todo history

### Pulse
- `POST /v1/pulse` — Create pulse entry
- `GET /v1/pulse/today` — Get today's pulse
- `PATCH /v1/pulse/today` — Update today's pulse
- `GET /v1/pulse/{pulse_date}` — Get pulse for date (ISO 8601)
- `GET /v1/pulse` — List pulse entries

### Operations
- `GET /v1/queue/status` — Queue health
- `GET /v1/dead-letters` — Failed refinements
- `POST /v1/dead-letters/{failed_id}/retry` — Reprocess failed item
- `POST /v1/synthesis/run` — Trigger synthesis job
- `GET /health` — Liveness check (always 200 while running)
- `GET /ready` — Readiness check (200 if DB reachable, 503 otherwise)

---

## CLI Commands

```bash
ob ingest "text"                                    # Ingest memory
ob ingest "text" --source discord                   # Ingest with source label
ob search "query"                                   # Hybrid search (10 results by default)
ob search "query" --type decision                   # Filter by type (memory/decision/task)
ob search "query" --entity "Google"                 # Filter by entity name/alias
ob search "query" --from 2026-01-01 --to 2026-12-31 # Filter by date range (ISO 8601)
ob search "query" --limit 20                        # Limit results
ob context "query"                                  # Search + LLM-ready context string
ob worker --sync                                    # Process one job inline (debug)
ob health                                           # Check API health
```

---

## Configuration

All configuration is via environment variables. Copy `.env.example` → `.env` and set values.

| Variable | Default | Description |
|---|---|---|
| `SQLALCHEMY_URL` | *(required)* | Postgres direct connection URL (port 5432, not 6543) |
| `API_KEY` | *(required)* | X-API-Key header value for auth |
| `API_HOST` | `localhost` | Bind address (use `0.0.0.0` behind a proxy) |
| `API_PORT` | `8000` | Port to bind |
| `ANTHROPIC_API_KEY` | *(required)* | Claude API key for extraction + synthesis |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | Model for pulse job (Haiku for cost; set to `claude-opus-4-6` in production) |
| `SYNTHESIS_MODEL` | `claude-haiku-4-5-20251001` | Synthesis model — **set to `claude-opus-4-6` in production** |
| `VOYAGE_API_KEY` | *(required)* | Voyage AI key for embeddings |
| `VOYAGE_MODEL` | `voyage-3` | Embedding model |
| `EMBEDDING_DIMENSIONS` | `1024` | Must match voyage-3 output (do not change after deploy) |
| `LOG_LEVEL` | `info` | Structlog level: debug, info, warning, error |
| `ENVIRONMENT` | `development` | Environment tag (development, production) |
| `WORKER_POLL_INTERVAL` | `5` | Seconds between queue polls |
| `WORKER_LOCK_TTL_SECONDS` | `300` | Stale lock reclaim threshold (5 minutes) |
| `IMPORTANCE_BASE_DEFAULT` | `0.5` | Default base_importance when not assigned by LLM |
| `IMPORTANCE_RECENCY_HALF_LIFE_DAYS` | `30` | Recency decay half-life in days |
| `SEARCH_DEFAULT_LIMIT` | `10` | Default search result count |
| `SEARCH_VECTOR_WEIGHT` | `0.5` | Weight for vector similarity score |
| `SEARCH_KEYWORD_WEIGHT` | `0.2` | Weight for full-text search score |
| `SEARCH_IMPORTANCE_WEIGHT` | `0.2` | Weight for importance score |
| `SEARCH_RECENCY_WEIGHT` | `0.1` | Weight for recency score |
| `ENTITY_FUZZY_MATCH_THRESHOLD` | `0.92` | pg_trgm similarity threshold for entity merge |
| `SYNTHESIS_MAX_MEMORIES_PER_REPORT` | `50` | Max memories to include in weekly digest |
| `RATE_LIMIT_MEMORY_PER_MINUTE` | `50` | Rate limit for POST /v1/memory per IP |
| `RATE_LIMIT_SEARCH_PER_MINUTE` | `100` | Rate limit for GET /v1/search per IP |
| `RATE_LIMIT_DEAD_LETTERS_PER_MINUTE` | `5` | Rate limit for POST /v1/dead-letters/{id}/retry per IP |
| `DISCORD_BOT_TOKEN` | *(optional)* | Discord bot token |
| `DISCORD_ALLOWED_USER_IDS` | `[]` | Allowed Discord user IDs (JSON array) |
| `DOMAIN` | *(optional)* | Domain for Caddy TLS (e.g. `openbrain.example.com`) |
| `OPEN_BRAIN_API_URL` | `http://localhost:8000` | API URL for integrations running in Docker |

---

## Development

### Project Structure
```
src/
├── api/         # FastAPI routes
├── core/        # Config, database, ORM models
├── pipeline/    # Ingestion: normalize, extract, validate, embed, resolve entities
├── retrieval/   # Hybrid search + context builder
├── jobs/        # Scheduled tasks: importance, synthesis
└── llm/         # LLM clients: Anthropic + Voyage AI
```

### Running Locally (without Docker)

Open Brain uses Supabase as its database. There is no local database to start.

```bash
# 1. Create a Supabase project at https://supabase.com (free tier is sufficient)
# 2. In Supabase SQL editor, enable required extensions:
#    CREATE EXTENSION IF NOT EXISTS vector;
#    CREATE EXTENSION IF NOT EXISTS pg_trgm;

# 3. Copy your Supabase direct connection string
#    (Settings → Database → Connection string → Direct, use port 5432)
#    Add it to your .env as SQLALCHEMY_URL

# 4. Install dependencies
uv sync

# 5. Run migrations
alembic upgrade head

# 6. Start API (in one terminal)
uvicorn src.api.main:app --reload

# 7. Start worker (in another terminal)
python -m src.pipeline.worker

# 8. Use CLI
ob ingest "Hello, Open Brain!"
```

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test
pytest tests/test_ingestion.py -v

# Debug mode
pytest tests/ -vv --tb=short
```

---

## Deployment

### VPS (Production)

1. **Prepare the VPS**
   - Clone the repo and copy `.env.example` → `.env`
   - Set production values: `API_KEY`, `SQLALCHEMY_URL`, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`
   - Set `ENVIRONMENT=production`, `LOG_LEVEL=info`
   - Set `DOMAIN=yourdomain.example` for Caddy TLS

2. **Apply migrations**
   ```bash
   docker compose --profile migrate up
   ```

3. **Start API, worker, and Caddy reverse proxy**
   ```bash
   docker compose --profile api --profile worker --profile caddy up -d
   ```
   Caddy auto-provisions TLS via Let's Encrypt. API is available at `https://yourdomain.example`.

4. **Start Discord bot** (optional)
   ```bash
   docker compose --profile discord up -d
   ```

5. **Scheduled intelligence jobs** — add to host cron:
   ```bash
   # Daily at 3 AM — update dynamic_importance from retrieval_events
   0 3 * * * cd /opt/open-brain && docker compose run --rm worker python -m src.jobs.importance >> /var/log/openbrain-jobs.log 2>&1

   # Weekly Sunday at 2 AM — generate synthesis report
   0 2 * * 0 cd /opt/open-brain && docker compose run --rm worker python -m src.jobs.synthesis >> /var/log/openbrain-jobs.log 2>&1
   ```

6. **Automated backups** — add to host cron:
   ```bash
   # Daily at 3:30 AM — pg_dump with 30-day retention
   30 3 * * * cd /opt/open-brain && ./scripts/backup.sh >> /var/log/openbrain-backup.log 2>&1
   ```
   Manual restore: `./scripts/restore.sh backups/open-brain-YYYYMMDD-HHMMSS.sql.gz`

7. **Production synthesis model** — set in `.env`:
   ```
   SYNTHESIS_MODEL=claude-opus-4-6
   ```
   (Default is Haiku for cost savings. Switch before going live.)

---

## Architecture Decisions

### Why PostgreSQL queue instead of Redis?
At MVP scale (~50 memories/day), Postgres queue eliminates a dependency. Uses `SELECT FOR UPDATE SKIP LOCKED` for distributed processing. Can migrate to Redis later if throughput demands it.

### Why Voyage AI instead of OpenAI embeddings?
Single vendor lock-in with Anthropic. Free tier is 200M tokens/month. Anthropic API credits apply.

### Why Claude Haiku for extraction?
Cost-effective (~$0.001 per request), strong instruction following, good JSON output quality.

### Why pgvector HNSW instead of exact cosine search?
HNSW index makes search O(log N) instead of O(N). Trade-off: rare misses vs practical speedup.

### Why append-only with superseding instead of updates?
Full audit trail (never lose data), correction chains (see reasoning for changes), simple concurrent access (no locking on updates).

---

## Limitations & Future Work

### Current
- Single-user only (assumes one author)
- No UI (API + CLI only)
- No real-time sync (polling-based)
- No multi-model support (hardcoded to Haiku + voyage-3)

### Roadmap
- Multi-user with role-based access
- Web UI for search + memory browser
- MCP adapter for Claude Code integration
- Slack ingestion bot
- Browser extension for web captures
- Knowledge graph visualization
- Agent write proposals (AI suggests memories, human approves)

---

## Troubleshooting

### Worker not processing jobs
- Check logs: `docker compose logs worker`
- Verify database: `SELECT COUNT(*) FROM refinement_queue WHERE status = 'pending'`
- Check for deadlocks: `SELECT * FROM pg_locks WHERE NOT granted`

### Search returns no results
- Verify embeddings exist: `SELECT COUNT(*) FROM memory_items WHERE embedding IS NOT NULL`
- Check full-text index: `SELECT * FROM pg_indexes WHERE tablename = 'memory_items'`
- Verify query parsing: `SELECT plainto_tsquery('english', 'your query')`

### API key rejected
- Verify header spelling: `X-API-Key` (not `x-api-key`)
- Check `.env` value matches header value
- Log auth middleware: set `LOG_LEVEL=DEBUG`

### 429 Too Many Requests
- Rate limit exceeded per IP per minute
- Check limits: `RATE_LIMIT_MEMORY_PER_MINUTE`, `RATE_LIMIT_SEARCH_PER_MINUTE`
- Retry after the `Retry-After` header value (seconds)

### Synthesis generating poor output
- Default model is Claude Haiku. Switch to Opus for better quality:
  `SYNTHESIS_MODEL=claude-opus-4-6`
- Increase lookback window: `POST /v1/synthesis/run` with `{"days": 14}`

### Backup verification
```bash
# Run backup manually
./scripts/backup.sh

# Test restore to a scratch database
./scripts/restore.sh backups/open-brain-YYYYMMDD-HHMMSS.sql.gz postgresql://user:pass@host/scratch_db
```

---

## Contributing

See `IMPLEMENTATION_PLAN.md` for architecture. See `CLAUDE.md` for collaboration guidelines.

---

## License

(To be determined)

---

## Support

For bugs, feature requests, or questions: Open an issue or contact the team.
