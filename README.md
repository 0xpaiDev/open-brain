# Open Brain

An AI-native organizational memory system that captures thoughts, decisions, and context into a structured PostgreSQL database with Claude-powered refinement.

## Quick Start

### Prerequisites
- Python 3.12+
- Supabase account (free tier: https://supabase.com)
- Anthropic API key (Claude Haiku credits)
- Voyage AI API key (free tier: 200M tokens/month)

### Setup

```bash
# Clone and navigate
cd open-brain

# Copy environment template
cp .env.example .env
# Edit .env with your API keys and database URL

# Install dependencies
pip install -e .  # or: uv sync

# Start services (Docker)
docker compose up -d

# Run migrations
alembic upgrade head

# Start the worker
python -m src.pipeline.worker &

# Try the CLI
ob add "My first memory"
ob search "first"
```

### Running Tests

```bash
pytest tests/ -v --cov=src
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
- **12 tables**: raw_memory, memory_items, entities, entity_aliases, entity_relations, memory_entity_links, decisions, tasks, refinement_queue, failed_refinements, retrieval_events
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

All endpoints require `X-API-Key` header. Prefix: `/v1/`

### Memory
- `POST /memory` — Ingest text
- `GET /memory/{id}` — Get memory with entity links

### Search
- `GET /search?q=...` — Hybrid search
- `GET /search/context` — Search + context builder (for LLM consumption)

### Entities
- `GET /entities` — List entities
- `GET /entity/{id}` — Entity with aliases
- `POST /entity/{id}/alias` — Add alias
- `POST /entity/merge` — Merge two entities

### Tasks & Decisions
- `GET /tasks` — List tasks
- `PATCH /tasks/{id}` — Update task status
- `GET /decisions` — List decisions

### Operations
- `GET /queue/status` — Queue health
- `GET /dead-letters` — Failed refinements
- `POST /dead-letters/{id}/retry` — Reprocess
- `GET /health` — Liveness check
- `GET /ready` — Readiness (DB + queue)

---

## CLI Commands

```bash
ob add "text"                                    # Ingest memory
ob add "text" --sync                             # Ingest + wait for completion
ob search "query" [--type insight|decision|task]  # Search memories
ob task "description" --owner name --due 2026-04-01  # Create task
ob decision "decision" [--reasoning "why"]        # Create decision
ob tasks [--status open|done]                     # List tasks
ob entities [--type person|org|project]           # List entities
ob status                                         # Queue health
```

---

## Configuration

Environment variables (`.env`):

```bash
# Database (Supabase direct connection)
# Find this in Supabase dashboard: Settings → Database → Connection pooler
# Use direct connection (port 5432), NOT the pooler (port 6543)
SQLALCHEMY_URL=postgresql+asyncpg://postgres.YOUR_REF:YOUR_PASSWORD@aws-0-us-east-1.pooler.supabase.com:5432/postgres

# API
API_KEY=your-secret-api-key-here

# LLM
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-haiku-4-5-20251001

# Embeddings
VOYAGE_API_KEY=pa-...
VOYAGE_MODEL=voyage-3
EMBEDDING_DIMENSIONS=1024

# Search weights (sum to 1.0)
SEARCH_VECTOR_WEIGHT=0.5
SEARCH_KEYWORD_WEIGHT=0.2
SEARCH_IMPORTANCE_WEIGHT=0.2
SEARCH_RECENCY_WEIGHT=0.1

# Importance scoring
IMPORTANCE_BASE_DEFAULT=0.5
IMPORTANCE_RECENCY_HALF_LIFE_DAYS=30

# Worker
WORKER_POLL_INTERVAL=5
WORKER_LOCK_TTL_SECONDS=300

# Application
LOG_LEVEL=info
ENVIRONMENT=development
```

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
ob add "Hello, Open Brain!"
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

1. **Postgres on managed service** (AWS RDS, Heroku, etc.)
   - PostgreSQL 16, pgvector, pg_trgm extensions enabled
   - Daily automated backups

2. **Docker Compose on VPS**
   - Update `.env` with production secrets (use `.env` file, not plaintext)
   - Use Caddy for TLS termination and reverse proxy
   - API bound to localhost, Caddy handles external traffic

3. **Scheduled jobs**
   - Add to host cron:
     ```bash
     0 3 * * * docker compose -f /path/to/docker-compose.yml run --rm importance python -m src.jobs.importance
     0 2 * * 0 docker compose -f /path/to/docker-compose.yml run --rm synthesis python -m src.jobs.synthesis
     ```

4. **Backups**
   - Daily: `pg_dump` to S3 or external storage
   - Test restore quarterly

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

---

## Contributing

See `IMPLEMENTATION_PLAN.md` for architecture. See `CLAUDE.md` for collaboration guidelines.

---

## License

(To be determined)

---

## Support

For bugs, feature requests, or questions: Open an issue or contact the team.
