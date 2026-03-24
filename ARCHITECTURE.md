# Open Brain Architecture

**Version**: 1.2
**Date**: 2026-03-24
**Status**: Phase 6 complete. All modules implemented: Foundation, Todo, RAG Chat, Morning Pulse.

## Phase 6 Module System (complete)

Three modules added in Phase 6, each gated by a feature flag in settings:

### Discord Bot Module Architecture (`src/integrations/modules/`)
The Discord bot is refactored into a thin loader (`discord_bot.py`) + conditionally-registered cog modules:

| Module | Flag | Cog File | Responsibilities |
|---|---|---|---|
| Core | always on | `core_cog.py` | `/search`, `/digest`, `/status` slash commands |
| Todo | `module_todo_enabled` | `todo_cog.py` | `/todo` subcommand group + interactive buttons/modals |
| RAG Chat | `module_rag_chat_enabled` | `rag_cog.py` | `on_message` handler for RAG-grounded LLM chat in designated channels |
| Morning Pulse | `module_pulse_enabled` | `pulse_cog.py` | `on_message` handler for DM reply parsing + wellness tracking |

**DM guard order** (in `discord_bot.py on_message`):
1. Own messages → skip
2. Unauthorized users → skip
3. Empty content → skip
4. RAG guard (trigger prefix in RAG channel) → route to RAG cog
5. **Pulse guard** (DM from `discord_pulse_user_id` within reply window) → route to pulse cog
6. Default → memory ingest

### Morning Pulse (`src/jobs/pulse.py` + `src/integrations/calendar.py`)
Cron-triggered morning check-in:
1. `send_morning_pulse()` — fetches calendar events + todos, generates Haiku question, sends DM via Discord REST API (not gateway), creates `daily_pulse` record
2. User replies in DM → `PulseCog.handle_reply()` intercepts, calls `parse_pulse_reply()`, stores structured data
3. Calendar integration is fully optional: google libs guarded with `try/except ImportError`, empty `CalendarState` returned on any error

### New Tables (Phase 6)
- `todo_items` — todo tasks with priority/status/due_date
- `todo_history` — append-only state change log for todos
- `daily_pulse` — one row per calendar day; unique constraint on `pulse_date`; statuses: sent/replied/parsed/parse_failed/skipped
- `rag_conversations` — persisted conversation buffer for RAG chat; unique on (channel_id, user_id)

---

## System Overview

Open Brain is an **async, durable organizational memory system** that ingests natural language into a PostgreSQL database with Claude-powered refinement and Voyage AI vector embeddings.

Core principles:
- **Append-only**: Corrections supersede originals, never overwrite
- **Queue-based**: Async ingestion decoupled from refinement processing
- **Hybrid retrieval**: Combines semantic, keyword, entity, and importance signals
- **Stateless**: All state in PostgreSQL; no in-process caches across requests

---

## Core Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ User Input (API or CLI)                                          │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     v
┌─────────────────────────────────────────────────────────────────┐
│ raw_memory table (append-only)                                   │
│ - stores original text, source, metadata, chunking info          │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     v
┌─────────────────────────────────────────────────────────────────┐
│ refinement_queue (durable job queue)                             │
│ - status: pending → processing → done / failed                  │
│ - stale lock reclaim: locked_at < now() - 5 min                 │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     v
┌─────────────────────────────────────────────────────────────────┐
│ Worker Pipeline (async, idempotent)                              │
│   1. Normalize (text cleanup + chunking)                         │
│   2. Extract (Claude Haiku with escalating prompts)              │
│   3. Validate (Pydantic schema + entity name normalization)      │
│   4. Embed (Voyage AI 1024-dim vectors)                          │
│   5. Resolve (pg_trgm fuzzy entity matching)                     │
│   6. Store (memory_items + entities + links, in transaction)     │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     v
┌─────────────────────────────────────────────────────────────────┐
│ Structured Memory (12 tables)                                    │
│ - memory_items (extracted knowledge, ranked)                     │
│ - entities, entity_aliases, entity_relations (knowledge graph)   │
│ - decisions, tasks (specialized memory types)                    │
│ - retrieval_events (audit trail for dynamic importance)          │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     v
┌─────────────────────────────────────────────────────────────────┐
│ Retrieval (hybrid ranking)                                       │
│ 1. Compute query embedding (Voyage AI)                           │
│ 2. Vector search (HNSW index, cosine distance)                   │
│ 3. Keyword search (FTS with GIN index)                           │
│ 4. Hybrid rank: 0.50×vector + 0.20×keyword +                     │
│                 0.20×importance + 0.10×recency                   │
│ 5. Log retrieval event (feeds dynamic importance)                │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     v
┌─────────────────────────────────────────────────────────────────┐
│ Context Builder                                                  │
│ - Format results for LLM consumption                             │
│ - Apply token budget (default 8k)                                │
│ - Return structured JSON                                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Stack Decisions

| Component | Technology | Why |
|---|---|---|
| Language | Python 3.12 | Async, type-safe, FastAPI ecosystem |
| Framework | FastAPI | Async HTTP, auto-docs, dependency injection |
| Database | Supabase (managed PostgreSQL 15/16) + pgvector + pg_trgm | Vector + relational + fuzzy matching; pgvector/pg_trgm pre-installed; SSL mandatory; free tier with 200M token embeddings |
| LLM (extraction) | Claude Haiku (claude-haiku-4-5) | Cost-effective, strong JSON output, on Anthropic credits |
| Embeddings | Voyage AI voyage-3 (1024 dims) | Single vendor, Anthropic-integrated, free tier 200M tokens/mo |
| Queue | PostgreSQL SELECT FOR UPDATE SKIP LOCKED | No external dependencies at MVP scale; proven at scale. **Must use direct connection (port 5432), not PgBouncer pooler** |
| CLI | typer | Simple, reuses API client, minimal new deps |
| Settings | pydantic-settings | Env-based config with validation, SecretStr for keys |
| Logging | structlog | Structured, machine-parseable, no logging.basicConfig() |
| Migrations | Alembic + manual DDL | Async SQLAlchemy support, control over custom indexes |
| Testing | pytest + pytest-asyncio | Standard async testing, no new framework deps |

---

## Ingestion Pipeline Design

### Queue-based Processing

```
POST /v1/memory  →  raw_memory  →  refinement_queue (status='pending')  →  HTTP 202
                                            ↓
                          Worker polls every 5s + jitter
                                            ↓
                    SELECT ... FOR UPDATE SKIP LOCKED
                    (status='pending' OR stale processing)
                                            ↓
       normalize → extract → validate → embed → resolve → store
                                            ↓
                    memory_items + entities + links
                                            ↓
                      refinement_queue (status='done')
```

### Failure Handling

On extraction failure (bad JSON, malformed response):
- If attempt < 3: reset to pending, try escalating prompt next
- If attempt = 3: write to failed_refinements table (dead letter queue)

On embedding failure (rate limit, timeout):
- Tenacity retry: 3 attempts with exponential backoff (2s, 4s, 8s)
- After 3 failures: write to failed_refinements with error_reason

Dead letters reviewable via `GET /v1/dead-letters` for manual intervention or replay.

---

## Retrieval Design

### Hybrid Ranking Formula

```
combined_score(memory_item) =
  0.50 × vector_similarity(query_embedding, item_embedding)
  + 0.20 × keyword_relevance(query_text, item_content)
  + 0.20 × importance_score(item)
  + 0.10 × recency_score(item.created_at)
```

**Weights** stored in `settings.py` (not hardcoded). Adjustable without code change.

**Recency score** uses exponential decay with half-life from settings (default 30 days):
```
recency_score = e^(-ln(2) / half_life * days_elapsed)
```

**Importance score** is a GENERATED column in Postgres:
```
importance_score = 0.6 × base_importance + 0.4 × dynamic_importance
```

`base_importance` set during extraction (0.0–1.0 scale).
`dynamic_importance` updated nightly by aggregating retrieval_events (how often the memory is accessed).

### Search Execution

1. Compute query embedding via Voyage AI
2. Vector search CTE: cosine distance, LIMIT 100
3. Keyword search CTE: FTS using GIN index, LIMIT 100
4. Full outer join on CTE results, rescores
5. Sort by combined_score, LIMIT limit
6. Insert one row per result into retrieval_events table

**Critical**: GIN index query must use identical `to_tsvector('english', content)` expression as the index definition, else query optimizer skips the index → sequential scan.

---

## Intelligence Layer Design

### Daily Importance Aggregation

External cron job (not in-process):
```
Every night (3 AM):
  - Count retrieval_events by memory_id for past 24 hours
  - Compute moving average with decay (older accesses count less)
  - UPDATE memory_items SET dynamic_importance = ...
  - TRUNCATE retrieval_events for archival (optional: move to archive table)
```

Rationale: Prevents blocking the async event loop. Runs in separate process.

### Weekly Synthesis

External cron job (separate Docker service):
```
Every Sunday (2 AM):
  - Fetch memory_items from past 7 days
  - Group by entities (who, what, why)
  - Call Claude to synthesize themes, decisions, status
  - Insert as new memory_item with type='weekly_report'
  - Log to retrieval_events as synthetic retrieval
```

Rationale: Weekly rollup captures patterns without storing raw observations. Long-lived.

---

## Database Schema Design

**12 tables**, all with UUID PKs (not BigInteger). No soft deletes.

### Append-only logs
- **raw_memory**: Original input text, source, metadata, chunk indices
- **retrieval_events**: Every search result accessed (feeds dynamic_importance)

### Refined knowledge
- **memory_items**: Extracted, ranked knowledge with GENERATED importance_score
- **decisions**: Structured decision records with alternatives (jsonb)
- **tasks**: Task items with owner, due date, status

### Entity knowledge graph
- **entities**: Canonical entity names with types (person, org, project, concept, tool, place)
- **entity_aliases**: Variant names → canonical (auto-populated by resolver)
- **entity_relations**: Edges (works_on, owns, related_to, decided_by) with memory_id context
- **memory_entity_links**: M2M junction (memory_id, entity_id) — composite PK

### Processing state
- **refinement_queue**: Durable job queue with SELECT FOR UPDATE SKIP LOCKED polling
- **failed_refinements**: Dead letter queue with error reasons, retry count, last output

### Key design patterns

**Composite PKs prevent duplicate inserts on reprocessing:**
```
entity_relations(from_entity, to_entity, relation_type, memory_id)
memory_entity_links(memory_id, entity_id)
```

Paired with `INSERT ... ON CONFLICT DO NOTHING` in worker → idempotent.

**GENERATED column computed by Postgres:**
```sql
importance_score GENERATED ALWAYS AS (
  0.6 * base_importance + 0.4 * dynamic_importance
) STORED
```

Never write `importance_score` directly. Update `base_importance` or `dynamic_importance` only.

**Append-only with superseding:**
```
Memory_item A (is_superseded=false)
Memory_item B (supersedes_memory_id=A.id, is_superseded=false)
```

When B is created, set A.is_superseded=true. Keeps full audit trail.

---

## Key Design Decisions & Rationale

### Supabase Managed PostgreSQL
**Decision**: Use Supabase (managed PostgreSQL 15/16) with direct connection (port 5432).
**Rationale**: Removes Docker database container ops burden. pgvector and pg_trgm pre-installed. Supabase is Anthropic-backed. Free tier covers MVP (200M embedding tokens/mo). Direct connection (not PgBouncer pooler) required for `SELECT FOR UPDATE SKIP LOCKED` used by worker. SSL is mandatory.

### PostgreSQL Queue over Redis
**Decision**: Use PostgreSQL SELECT FOR UPDATE SKIP LOCKED for job queue.
**Rationale**: At MVP scale (~50 memories/day), no external dependency. SELECT FOR UPDATE is battle-tested at scale. Simplifies ops: one database, one connection pool, one backup strategy. Easily scales to 1000s of jobs/day before hitting limits. Worker must use Supabase direct connection (port 5432), not pooler (port 6543).

### Voyage AI over OpenAI Embeddings
**Decision**: Use Voyage AI voyage-3 (1024 dims).
**Rationale**: Single vendor (Anthropic-backed), free tier covers MVP (200M tokens/mo ≈ 300k tokens/month at 50 memories/day). More efficient than ada-002. Token efficiency → lower cost at scale.

### Append-only + Superseding over Soft Deletes
**Decision**: No soft deletes. Corrections create new records with `supersedes_memory_id`.
**Rationale**: Audit trail preserved. No risk of silent data loss from "delete + re-add" cycle. Schema simpler (no `is_deleted` flag bloat). Makes correcting extraction errors cheap and obvious.

### GENERATED Column for Importance
**Decision**: Compute `importance_score = 0.6 × base + 0.4 × dynamic` in Postgres as GENERATED ALWAYS STORED.
**Rationale**: Single source of truth. No risk of stale computed values from app-layer caching. Always consistent. Weights adjustable in Postgres without app redeploy.

### Composite PKs on Junctions
**Decision**: Use (memory_id, entity_id) on `memory_entity_links` and (from, to, relation_type, memory_id) on `entity_relations` as composite PKs.
**Rationale**: Prevents duplicate rows on reprocessing. Paired with `ON CONFLICT DO NOTHING`, worker is fully idempotent even if the same raw_memory is processed twice.

### External Cron for Intelligence Jobs
**Decision**: Daily importance + weekly synthesis run in separate Docker services via host cron, not in-process FastAPI.
**Rationale**: Prevents blocking the async event loop. Long-running jobs (Claude synthesis can take minutes) won't hold up request handling. Easier to debug, retry, or pause independently. Scales horizontally without API threads.

---

## Security Posture

### Phase 1 (MVP)
- ✅ X-API-Key header auth on all `/v1/*` routes (middleware)
- ✅ API keys in `SecretStr` (never logged raw)
- ✅ `.env` excluded from git, `.dockerignore` excludes .env from image
- ✅ User input wrapped in `<user_input>...</user_input>` delimiters in all prompts
- ✅ API bound to localhost:8000 (no external network until reverse proxy)

### Phase 4 (Hardening)
- TLS termination via Caddy/nginx reverse proxy
- Rate limiting middleware (requests/IP/key)
- Request/response logging with structlog
- Audit trail of schema changes (via Alembic versioning)
- Data encryption at rest (Supabase handles at infrastructure level; pgcrypto available for column-level encryption if needed)
- Row-level security for multi-user support
- Managed backups via Supabase (Pro tier) or manual pg_dump via direct connection

---

## Maintenance Rule

**If any architectural decision above changes, ARCHITECTURE.md must be updated before the change is merged.**

Examples of changes requiring ARCHITECTURE.md update:
- Switch embedding provider (Voyage → OpenAI)
- Move job queue (PostgreSQL → Redis)
- Change importance formula weights significantly
- Switch LLM model family (Haiku → Sonnet)
- Add new service (e.g., separate API + worker deployment)
- Change data retention policy (e.g., archive > 1 year)

Minor changes that do NOT require updates:
- Bug fixes in pipeline stages
- Prompt refinements (covered by CLAUDE.md)
- Config constant adjustments (weights within ARCHITECTURE.md formula)
- Dependency version bumps

---

## References

- **Implementation plan**: `/home/shu/projects/open-brain/IMPLEMENTATION_PLAN.md` (task breakdown, phases, file structure)
- **Collaboration rules**: `/home/shu/projects/open-brain/CLAUDE.md` (code style, escalation, common pitfalls)
- **Progress tracking**: `/home/shu/projects/open-brain/PROGRESS.md` (checkpoint tracking, verification gates)
- **Original spec**: `open-brain-implementation-plan.docx` (high-level requirements)
