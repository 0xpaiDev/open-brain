# Open Brain Architecture

**Version**: 2.6
**Date**: 2026-05-19
**Status**: All phases + Training & Commitments V1 + multi-exercise commitments (routine + plan kinds) + Learning Library V2 backend (bulk import + materials API) complete. Discord integration removed. **Claude Code Memory Flywheel V1 — SessionEnd/Start hooks, local memory cron, memory_expand tier-2 endpoint.** **Exercise Library + Per-Day Schedule + Import Wizard + Plan CRUD (Spec B).** Modules: Foundation, Todo, Morning Pulse, Training, Learning.

## Phase 6 Module System (complete)

Three modules added in Phase 6, each gated by a feature flag in settings:

### Morning Pulse (`src/jobs/pulse.py` + `src/integrations/calendar.py`)
Cron-triggered morning check-in:
1. `trigger_morning_pulse()` — calls `POST /v1/pulse/start` on the local API
2. API generates question using signal-driven pipeline (`focus`, `opportunity`, `open` detectors) or legacy `_generate_ai_question()` fallback
3. Calendar integration is fully optional: google libs guarded with `try/except ImportError`, empty `CalendarState` returned on any error

### New Tables (Phase 6)
- `todo_items` — todo tasks with priority/status/due_date
- `todo_history` — append-only state change log for todos
- `daily_pulse` — one row per calendar day; unique constraint on `pulse_date`; statuses: sent/replied/parsed/parse_failed/skipped

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
│ Structured Memory (25 tables)                                    │
│ - memory_items (extracted knowledge, ranked)                     │
│ - entities, entity_aliases, entity_relations (knowledge graph)   │
│ - decisions, tasks (specialized memory types)                    │
│ - todos, todo_history (task management)                          │
│ - daily_pulse (daily wellness check-in)                          │
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

### Progressive Disclosure (`GET /v1/memory/{id}/expand`)

Tier-2 endpoint for callers that already have a memory_id from search and need the **full** content + provenance + nearby siblings:

1. Resolve `MemoryItem` by UUID; 404 if missing or `is_superseded=True`.
2. Fetch parent `RawMemory.raw_text` (full original input).
3. Query up to 3 older + 3 newer non-superseded `MemoryItem` rows from the **same source**, merge in Python, sort by absolute `created_at` distance, take top 3. This avoids Postgres-only `EXTRACT(EPOCH FROM ...)` so SQLite tests pass.
4. Return `{memory_id, content, raw_text, neighbors[], metadata}`.

Surfaced as the `memory_expand` MCP tool (`src/mcp_server.py`). Memory retrieval contract documented in `CLAUDE.md`: tier-0 (in-context markdown) → tier-1 `search_memory` → tier-2 `memory_expand` → tier-3 `get_context`.

### Claude Code Memory Flywheel (local hooks + local cron)

Per-machine layer that feeds the vector DB and curates a markdown snapshot for tier-0 free recall:

- **SessionEnd hook** (`scripts/claude-code/session-end-ingest.sh` + `session_end_ingest.py`) — fires on every CC session exit; Haiku-summarises the JSONL transcript; appends to `context/sessions/{date}.md`; POSTs to `/v1/memory` with `source="claude-code-session"` and `metadata.project` (resolved via hardcoded `REPO_PROJECT_MAP`). Backend pluggable via `OB_SESSION_END_BACKEND` (`cli` = `claude --print` subscription, `api` = REST + `ANTHROPIC_API_KEY`, `auto`).
- **SessionStart hook** (`session-start-distill.sh`) — self-scopes by `cwd`-vs-script-repo match; opportunistically fires the daily distill in background on `source=startup`, throttled to once per `OB_SESSION_START_MIN_HOURS` (default 6h).
- **Local cron** (`scripts/memory/install-anacron.sh`) — writes `/etc/cron.d/ob-memory-flywheel` (daily 23:00 + Sun 09:00) and `/etc/anacrontab` catch-up entries. Sentinel files (`context/.last-distill`, `.last-curate`) make the daily job idempotent across missed runs.

Crons run **locally** because they read `~/.claude/projects/.../memory/*.md` and `context/sessions/*.md` — paths neither the prod VM nor a remote scheduler can see.

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

**27 tables**, all with UUID PKs (not BigInteger). Exception: `commitment_exercise_logs` uses soft-delete via `deleted_at` column.

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

### Module: Todo
- **todo_items**: Todo tasks with priority/status/due_date/label/project (soft reference to project_labels.name, nullable), learning_item_id FK
- **todo_history**: Append-only state change log for todos
- **todo_labels**: User-defined labels with name (unique) and hex color

### Module: Project Tagging
- **project_labels**: User-defined project labels with name (unique, max 100 chars) and hex color; both `todo_items.project` and `memory_items.project` are soft references (no FKs). Includes idempotent "Personal" seed row (color: #7b8fc7). Rename via `PATCH /v1/project-labels/{name}` cascades atomically to both tables; delete cascades to NULL on both.

### Module: Daily Pulse
- **daily_pulse**: One row per calendar day; unique on `pulse_date`; statuses: sent/replied/parsed/parse_failed/skipped/completed

### Module: Training & Commitments
- **commitments**: Challenge definitions with `kind` ("single"|"routine"|"plan"), `exercise` (nullable for multi-exercise kinds), `daily_target`, `metric`, `cadence` ("daily"|"aggregate"), date range, status (active/completed/abandoned). Aggregate has `targets`/`progress` JSONB. `import_hash` (SHA-256, indexed) used for plan import idempotency.
- **commitment_entries**: One row per commitment per day, pre-generated on creation (daily cadence; plan kind: workout days only — rest days have no entry). `logged_count` incremented by log actions; status: pending→hit (auto when target/all-exercises met) or pending→miss (nightly cron)
- **commitment_exercises** (migration 0017+0018): Per-exercise definition for routine/plan kinds. Columns: `name`, `sets` (nullable — target set count), `target`, `metric`, `progression_metric`, `position`. `exercise_id` FK → `exercises.id` (nullable, migration 0020). Unique on `(commitment_id, name, sets)`.
- **commitment_exercise_logs** (migration 0017): Per-exercise log entry. Soft-deleted via `deleted_at`. Columns: `sets`, `reps`, `weight_kg`, `duration_minutes`, `notes`. A day is "hit" when every exercise has ≥1 active (non-deleted) log for that date. Plan kind: only exercises in `commitment_entry_exercises` for today's entry count.
- **exercises** (migration 0020): Global exercise library. `name` is normalised (`strip().lower()`), UNIQUE. `display_name` preserves original casing (first-insert wins). Linked from `commitment_exercises.exercise_id` (nullable FK ON DELETE SET NULL).
- **commitment_entry_exercises** (migration 0021): Junction table linking a specific `CommitmentEntry` (workout day) to the `CommitmentExercise` rows scheduled for it. Unique on `(entry_id, exercise_id)`. Indexed on `(commitment_id, entry_id)`. Created at import time; editable via PATCH schedule endpoints.
- **commitment_activities**: Junction table linking aggregate commitments to Strava activities for dedup and audit; unique constraint on (commitment_id, strava_activity_id); progress recalculated from all linked activities on every change
- **strava_activities**: Cached Strava activity data ingested via webhook; strava_id UNIQUE prevents duplicate inserts from retries; raw_data JSON stores full API response; TSS computed from NP and FTP on ingest
- **strava_tokens**: Single-row OAuth token store; bootstrapped from env vars on first webhook; auto-refreshed via `_get_valid_access_token()` when expired

### Module: Learning Library
- **learning_topics**: Top-level learning subjects with `depth` (`foundational`|`deep`), `is_active` flag (cron draws only from active topics; deactivation preserves all progress), `position` for ordering
- **learning_sections**: Grouping of items under a topic; FK to `learning_topics` with `ON DELETE CASCADE`
- **learning_items**: Leaf units with `status` (`pending`|`done`), `feedback` (free text; calibration signal for LLM selector), `notes` (personal reference), `completed_at`; FK to `learning_sections` with `ON DELETE CASCADE`
- **learning_materials** (migration 0016): Source material stored one-to-one with a topic (unique constraint on `topic_id`, FK CASCADE). Columns: `content` TEXT (markdown body, unlimited), `source_type` VARCHAR(40), `source_url`, `source_title`, `metadata_json` JSONB. RLS enabled. Full material is NOT returned in the tree view — only `has_material: bool` flag. Bulk import at `POST /v1/learning/import` (schemas in `src/api/schemas/learning_import.py`). Material does NOT sync to `memory_items`.
- **todo_items.learning_item_id**: FK column added by migration 0013 (`ON DELETE SET NULL`); distinguishes cron-generated learning todos from regular ones. Learning items DO NOT sync to `memory_items`; the derived todos DO, via existing `todo_sync.py`.

### Job monitoring
- **job_runs**: Execution log for scheduled jobs (pulse, importance, synthesis, commitment_miss); used by `/v1/jobs/status`

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
- ✅ TLS termination via Caddy reverse proxy
- ✅ Rate limiting on all `/v1/*` routes (`@limiter.limit()` decorator)
- ✅ Structured request/response logging with structlog
- ✅ Audit trail of schema changes (Alembic versioning)
- ✅ Data encryption at rest (Supabase infrastructure-level)
- ✅ Managed backups via Supabase + daily pg_dump cron (3:30 AM)
- ✅ Row-Level Security on all tables (migration 0009) — deny-all for PostgREST anon/authenticated roles; app bypasses via superuser connection

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

- **Implementation plan**: `./IMPLEMENTATION_PLAN.md` (task breakdown, phases, file structure)
- **Collaboration rules**: `./CLAUDE.md` (code style, escalation, common pitfalls)
- **Progress tracking**: `./PROGRESS.md` (checkpoint tracking, verification gates)
- **Original spec**: `open-brain-implementation-plan.docx` (high-level requirements)
