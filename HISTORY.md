# Open Brain — Project History

Covering **2026-03-13 to 2026-04-06** | 6 phases + dashboard update + project tagging + chat (backend + frontend), 962 tests (791 backend + 162 Vitest + 7 E2E)

---

## Session — 2026-04-06 (Chat Frontend UI)

**What changed**:
- Built full `/chat` page replacing stub: 5 components in `web/components/chat/` (model-selector, chat-sources, chat-thread, external-context-panel, chat-input)
- Created `useChat` hook (`web/hooks/use-chat.ts`) with sendMessage, resetChat, model persistence (localStorage), history truncation to 20 messages
- Added 5 chat type interfaces to `web/lib/types.ts` (ChatMessage, ChatSourceItem, ChatRequest, ChatResponse, ChatDisplayMessage)
- 20 new Vitest tests: 12 hook tests (`use-chat.test.ts`) + 8 component tests (`chat-thread.test.tsx`)

**Decisions made**:
- Frontend types match actual backend `ChatResponse.response` (not plan doc's `reply`), no `history_length` field
- Model IDs hardcoded from `.env.example` defaults (Haiku: `claude-haiku-4-5-20251001`, Sonnet: `claude-sonnet-4-6`); `null` sends default
- Client-side conversation only — resets on page leave, no DB persistence
- shadcn Select uses `@base-ui/react/select` (not radix) — `onValueChange` returns `string | null`, guarded in ModelSelector

**Gotchas found**: Pre-existing test failure in `task-list.test.tsx:716` (done section grouped collapsibles) — unrelated to chat changes
**Test count**: 962 total (791 backend + 162 Vitest + 7 E2E + 2 pre-existing skip)

---

## Session — 2026-04-06 (Chat Backend Foundation)

**What changed**:
- Extracted shared RAG prompt logic from `rag_cog.py` into `src/llm/rag_prompts.py` (system prompt, user message wrapping, query formulation)
- Created `POST /v1/chat` endpoint (`src/api/routes/chat.py`) with 10-step pipeline: validate → formulate (Haiku) → embed → hybrid search → build context → system prompt → wrap user input → synthesize → commit → respond
- Added chat rate limiter (30/min) to `src/api/middleware/rate_limit.py`, registered router in `main.py`
- 25 new tests (`tests/test_chat.py`): 10 unit (prompt utilities) + 15 integration (endpoint)

**Decisions made**:
- Client-side conversation state only — no DB schema changes, no migrations
- Query formulation uses Haiku via `complete()` (baked-in model); synthesis uses user-selected model via `complete_with_history(model=...)` override
- All user messages wrapped in `<user_input>` tags for synthesis; formulated query (system-generated) NOT wrapped
- Per-request AnthropicClient + VoyageEmbeddingClient creation (same pattern as search.py)

**Gotchas found**: None
**Test count**: 942 total (791 backend + 142 Vitest + 7 E2E + 2 pre-existing skip)

---

## Session — 2026-04-05 (Memory Project Tagging)

**What changed**:
- Added project tagging to memory system: `ProjectLabel` model + `project` column on `MemoryItem` (migration 0008)
- New CRUD API: `POST/GET/DELETE /v1/project-labels` (`src/api/routes/project_labels.py`)
- Worker pipeline reads `project` from `RawMemory.metadata_` side-channel → stores on `MemoryItem.project`
- `project_filter` query param added to `GET /v1/memory/recent`, `GET /v1/search`, `GET /v1/search/context`
- New settings page (`web/app/settings/page.tsx`) with project label CRUD (add, delete, color picker)
- SmartComposer: project dropdown between source label and submit button
- Memory cards: project badge pill; sidebar: project filter section on `/memory` route
- 14 new backend tests (`tests/test_project_labels.py`), +2 new frontend files

**Decisions made**:
- Project lives on `MemoryItem` (not `RawMemory`) — it's the queryable entity; RawMemory carries it via metadata side-channel (same pattern as `supersedes_memory_id`)
- No extraction prompt changes — project is user-asserted, not LLM-inferred (entity graph already captures project mentions separately)
- API-backed project labels (not localStorage) — follows TodoLabel pattern for consistency
- Soft reference (string, no FK) — deleting a label does NOT null out existing memories

**Gotchas found**: None
**Test count**: 917 total (766 backend + 142 Vitest + 7 E2E + 2 pre-existing skip)

---

## Session — 2026-04-04 (Dashboard Todo Update — 2/2)

**What changed**:
- Completed Steps 6+7 of `dash-update-plan.md`: filter redesign + E2E tests — all 7 steps done
- `web/hooks/use-todos.ts` — paginated done loading (`loadMoreDone`, `hasMoreDone`), `filterThisWeekTodos()`, `groupDoneTodos()` with ISO week boundaries
- `web/components/dashboard/task-list.tsx` — 3 tabs (Today/This Week/All), search bar, label filter chips, grouped done sections with Collapsible per period, "Load more" button
- `web/e2e/todos.spec.ts` — 4 new E2E tests (default date, undo toast, search, This Week tab)
- 28 new Vitest tests (14 hook + 14 component), updated existing tab tests for 3-tab layout

**Decisions made**: Search and label filter state kept in component (not hook) — presentation concern
**Gotchas found**: None
**Test count**: 901 total (752 backend + 142 Vitest + 7 E2E)

---

## Phase 1: Foundation ✅ COMPLETE (2026-03-15)

**Status**: All Checkpoints 0–9 done, 89 tests passing
**Duration**: ~59h (44h code + 15h tests)
**Approach**: Test-first self-confirm loop — each checkpoint includes paired test file(s)

---

### Checkpoint 0: Test Infrastructure ✅
- [x] 0.1: Create `tests/__init__.py`
- [x] 0.2: Create `tests/conftest.py` — complete test infrastructure
  - Async SQLite test DB (`create_async_engine`)
  - Fixtures: `async_session`, `mock_anthropic_client`, `mock_voyage_client`
  - FastAPI test client fixture + override_get_db dependency
  - API key headers fixture: `{"X-API-Key": "test-secret-key"}`

**Verification**: `python -c "import pytest; from tests.conftest import *"` — imports cleanly ✅

---

### Checkpoint 1: Project Scaffold ✅
- [x] 1.0a: Create `.gitignore` (Python + environment) — updated to exclude .dockerignore tracking
- [x] 1.0b: Create `.dockerignore` — excludes .env, __pycache__, .pytest_cache, etc.
- [x] 1.0c: Create `Makefile` with shortcuts (make up, down, migrate, test, lint, format, logs-*)
- [x] 1.0d: Create `pyproject.toml` with dependencies — uv-managed, 50+ packages
- [x] 1.0e: Create `Dockerfile` (multi-stage: builder + runtime)
- [x] 1.0f: Create `docker-compose.yml` (db, migrate, api, worker services + profiles)
- [x] 1.0g: Create `.env.example` template — 25 env vars with defaults

**Commit**: `feat(phase-1): add project scaffold and Docker configuration`

---

### Checkpoint 2: Core Infrastructure + Tests ✅

**Tests written & implemented:**
- [x] `tests/test_config.py` (4 tests passing)
  - `test_settings_loads_from_env` ✅
  - `test_secret_str_not_logged` ✅
  - `test_embedding_dimensions_validator` ✅
  - `test_default_values` ✅

- [x] `tests/test_database.py` (3 tests passing)
  - `test_health_check_fails_when_engine_none` ✅
  - `test_health_check_fails_on_connection_error` ✅
  - `test_get_db_requires_initialization` ✅

**Implementation complete:**
- [x] `src/core/config.py` — pydantic-settings with SecretStr
  - Settings class with 25 env vars (database, API, LLM, search weights, etc.)
  - `ConfigDict` for Pydantic v2
  - Validators for `embedding_dimensions` (only 1024) and search weights (0–1)
  - Module-level lazy singleton: handles missing env vars gracefully

- [x] `src/core/database.py` — async engine setup
  - `create_async_engine()` with pool_pre_ping=True, pool_size=5, max_overflow=5
  - `AsyncSessionLocal` factory
  - `get_db()` async generator dependency
  - `health_check()` function (SELECT 1 connectivity test)
  - `init_db()` and `close_db()` for lifespan management

**Commit**: `feat(phase-1): implement core infrastructure (config, database) with tests`

---

### Checkpoint 3: Models + Alembic Migration ✅

**Tests written & implemented:**
- [x] `tests/test_models.py` (7 tests passing)
  - `test_all_tables_exist` ✅ (11 tables)
  - `test_uuid_pk_on_simple_tables` ✅ (FIX-1 validation)
  - `test_entity_relations_composite_pk` ✅ (FIX-5 validation)
  - `test_memory_entity_links_composite_pk` ✅ (FIX-5 validation)
  - `test_refinement_queue_has_required_columns` ✅
  - `test_failed_refinements_has_queue_id_fk` ✅
  - `test_foreign_key_types_match_references` ✅

**Implementation complete:**
- [x] `src/core/models.py` — 11 SQLAlchemy ORM tables
  - **UUID PKs everywhere** (FIX-1) — all PKs use `UUID(as_uuid=True)`
  - `raw_memory`: id, source, raw_text, author, metadata, chunk_index/total/parent, created_at
  - `memory_items`: all required fields + `importance_score` GENERATED (0.6×base + 0.4×dynamic)
  - `entities`: id, name UNIQUE, type, created_at
  - `entity_aliases`: fuzzy match support
  - `entity_relations`: (from_entity_id, to_entity_id, relation_type, memory_id) — **composite PK** (FIX-5)
  - `memory_entity_links`: (memory_id, entity_id) — **composite PK** (FIX-5)
  - `decisions`, `tasks`: structured knowledge
  - `refinement_queue`: SELECT FOR UPDATE SKIP LOCKED support
  - `failed_refinements`: dead letter queue with queue_id FK
  - `retrieval_events`: search access log for dynamic importance (FIX-3)

- [x] `alembic/versions/0001_initial_schema.py` — **MANUAL DDL** (FIX-4 compliant)
  - All 11 tables with UUID PKs and composite PKs
  - **HNSW index**: `CREATE INDEX ... USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)` (FIX-4)
  - **GIN index**: `CREATE INDEX ... USING GIN (to_tsvector('english', content))` — exact expression for FIX-4 compliance
  - B-tree indexes: type, created_at, importance_score, status, locked_at for query optimization
  - `importance_score GENERATED ALWAYS AS (0.6 * base_importance + 0.4 * dynamic_importance) STORED`
  - pgvector and pg_trgm extensions

**Commit**: `feat(phase-1): implement ORM models and Alembic migration`

---

### Checkpoint 4: LLM Clients + Tests ✅

**Tests implemented & passing:**
- [x] `tests/test_llm.py` (14 tests passing)
  - `test_anthropic_client_complete_returns_string` ✅
  - `test_anthropic_client_raises_extraction_failed_on_sdk_error` ✅
  - `test_anthropic_client_raises_extraction_failed_on_unexpected_error` ✅
  - `test_voyage_client_embed_returns_1024_floats` ✅
  - `test_voyage_client_raises_embedding_failed_on_error` ✅
  - `test_voyage_client_retries_on_failure` ✅ (tenacity validation)
  - `test_build_extraction_user_message_wraps_in_delimiters` ✅ (prompt injection defense)
  - `test_build_extraction_user_message_preserves_special_chars` ✅
  - `test_get_extraction_prompt_returns_attempt_0` ✅
  - `test_get_extraction_prompt_returns_attempt_1` ✅
  - `test_get_extraction_prompt_returns_attempt_2` ✅
  - `test_get_extraction_prompt_different_per_attempt` ✅
  - `test_get_extraction_prompt_raises_on_invalid_attempt` ✅
  - `test_all_extraction_prompts_are_non_empty` ✅

**Implementation complete:**
- [x] `src/llm/client.py` — async clients with tenacity retry
  - `AnthropicClient(api_key, model)`: async `complete()` method, raises `ExtractionFailed` on error
  - `VoyageEmbeddingClient(api_key, model)`: async `embed()` with `asyncio.to_thread()`, tenacity retry (3 attempts, 2-8s backoff), raises `EmbeddingFailed`
  - Module-level singletons: `anthropic_client` and `embedding_client` (None if keys absent)

- [x] `src/llm/prompts.py` — extraction prompts with user input delimiters
  - `EXTRACTION_SYSTEM_PROMPT`: main prompt with `<user_input>...</user_input>` wrapping
  - `EXTRACTION_RETRY_PROMPT_1` & `EXTRACTION_RETRY_PROMPT_2`: escalating prompts
  - `build_extraction_user_message()`: wraps text in delimiters for prompt injection defense
  - `get_extraction_prompt(attempt)`: returns prompt 0/1/2 by attempt index

**Commit**: `feat(phase-1): implement LLM clients and prompts with retry logic`

---

### Checkpoint 5: Pipeline Stages + Tests ✅

**Tests implemented & passing:**
- [x] `tests/test_pipeline.py` (24 tests passing)
  - Normalizer (7 tests): whitespace, blank lines, unicode NFC, chunk splitting, token boundaries
  - Extractor (6 tests): valid JSON, invalid JSON, schema mismatch, attempt-based prompt selection
  - Validator (4 tests): empty content validation, entity name normalization, deduplication
  - Embedder (2 tests): vector generation, error propagation
  - EntityResolver (5 tests): new entity creation, exact alias match, fuzzy match, idempotency, multiple entities

**Implementation complete:**
- [x] `src/pipeline/normalizer.py` — `normalize()`: NFC unicode, `chunk()`: tiktoken cl100k_base, max 2000 tokens
- [x] `src/pipeline/extractor.py` — `ExtractionResult` Pydantic model, attempt-based prompt escalation
- [x] `src/pipeline/validator.py` — entity name normalization, deduplication
- [x] `src/pipeline/embedder.py` — async wrapper around VoyageEmbeddingClient
- [x] `src/pipeline/entity_resolver.py` — exact alias → fuzzy pg_trgm (0.92) → new entity

**Commit**: `feat(phase-1): implement pipeline stages (normalize, extract, validate, embed, resolve)`

---

### Checkpoint 6: Worker + Tests ✅

**Tests implemented & passing:**
- [x] `tests/test_worker.py` (9 tests passing)
  - `test_claim_batch_picks_pending_job` ✅
  - `test_claim_batch_reclaims_stale_processing` ✅ — **FIX-2 validation**: locked_at < now() - 5min → reclaimed
  - `test_claim_batch_skips_fresh_processing` ✅
  - `test_process_job_creates_memory_item` ✅
  - `test_process_job_resets_to_pending_on_first_failure` ✅
  - `test_3_failure_path_moves_to_dead_letter` ✅ — **FIX-3 validation**
  - `test_process_job_creates_entities_and_links` ✅
  - `test_store_memory_item_creates_memory_item` ✅
  - `test_move_to_dead_letter_sets_queue_status_failed` ✅

**Implementation complete:**
- [x] `src/pipeline/worker.py` — async polling loop
  - `claim_batch()`: SELECT FOR UPDATE SKIP LOCKED, **FIX-2 stale lock reclaim**
  - `process_job()`: normalize → extract → validate → embed → resolve → store
  - `store_memory_item()`: transactional inserts; queue status → 'done'
  - `move_to_dead_letter()`: **FIX-3 dead letter** after 3 failed attempts
  - `run()`: main polling loop with SIGTERM handler, jittered sleep

**Commit**: `feat(phase-1): implement queue worker with stale lock reclaim (FIX-2) and 3-failure dead letter (FIX-3)`

---

### Checkpoint 7: API Ingestion + Tests ✅

**Tests implemented & passing:**
- [x] `tests/test_ingestion.py` (9 tests passing)
  - `test_post_memory_returns_202` ✅
  - `test_post_memory_creates_raw_memory_row` ✅
  - `test_post_memory_creates_refinement_queue_row` ✅
  - `test_post_memory_accepts_optional_fields` ✅
  - `test_post_memory_no_auth_returns_401` ✅
  - `test_post_memory_wrong_key_returns_401` ✅
  - `test_post_memory_bad_json_returns_422` ✅
  - `test_health_endpoint_returns_200` ✅
  - `test_ready_endpoint_checks_database` ✅

**Implementation complete:**
- [x] `src/api/main.py` — FastAPI app with lifespan, middleware, routers
- [x] `src/api/routes/memory.py` — POST /v1/memory → 202, inserts raw_memory + refinement_queue
- [x] `src/api/routes/health.py` — GET /health (always 200), GET /ready (200/503 based on DB)
- [x] `src/api/middleware/auth.py` — X-API-Key validation, exempts /health + /ready

**Commit**: `feat(phase-1): checkpoint-7 — API ingestion endpoint with auth middleware`

---

### Checkpoint 8: Search & Ranking + Tests ✅

**Tests implemented & passing:**
- [x] `tests/test_ranking.py` (8 tests) + `tests/test_search.py` (7 tests)

**Implementation complete:**
- [x] `src/retrieval/ranking.py` — `recency_score()`, `combined_score()` with settings-based weights
- [x] `src/retrieval/search.py` — `hybrid_search()` with FIX-4 compliant SQL, FIX-3 event logging
- [x] `src/api/routes/search.py` — GET /v1/search endpoint

**Critical Fixes Validated:**
- **FIX-3**: `hybrid_search()` logs a `RetrievalEvent` for every result returned
- **FIX-4**: GIN query uses exact `to_tsvector('english', content)` expression matching index definition

**Commit**: `feat(phase-1): checkpoint-8 — hybrid search, ranking formula, search endpoint`

---

### Checkpoint 9: Full Test Suite Pass ✅

**Test suite breakdown (89 total):**
```
test_config.py:      7 tests  ✅
test_database.py:    3 tests  ✅
test_ingestion.py:   9 tests  ✅
test_llm.py:        14 tests  ✅
test_models.py:      8 tests  ✅
test_pipeline.py:   24 tests  ✅
test_ranking.py:     8 tests  ✅
test_search.py:      7 tests  ✅
test_worker.py:      9 tests  ✅
────────────────────────────────
Total:              89 tests  ✅
```

**Commit**: `feat(phase-1): checkpoint-7-8-9 — API ingestion, search/ranking, full suite 89 tests passing`

---

### Phase 1 Verification Gates

- [x] Gate 1: `docker compose up` → api and worker services healthy ✅ (2026-03-15)
- [x] Gate 2: embedding column `udt_name='vector'`, 20 rows all with non-null embeddings ✅ (2026-03-15)
- [x] Gate 3: `POST /v1/memory` → 202 with raw_id ✅
- [x] Gate 4: raw_memory + refinement_queue rows in DB ✅
- [x] Gate 5: Worker processes job → memory_items + entities + embedding created ✅
- [x] Gate 6: 3-failure retry path → failed_refinements row ✅
- [x] Gate 7: Stale lock reclaim works ✅
- [x] Gate 8: `GET /v1/search?q=test` → ranked results ✅

---

## Session 3 Notes (2026-03-15) — Architecture Review & Pre-Phase-2 Validation

### Root Cause: Worker "Loop" Bug
The LLM worker was not truly looping — it was making **3 Anthropic calls per job instead of 1**. Root cause: Claude's response was wrapped in markdown code fences (` ```json ... ``` `) which caused `json.loads()` to fail with `JSONDecodeError`, triggering `ExtractionFailed` and the full 3-attempt retry cycle per job.

**Fix**: Strip markdown code fences in `extractor.py` before parsing.

### ORM Fixes (no migration required)
1. `embedding` column: Changed from `JSONB` placeholder to `Vector(1024)` (pgvector-sqlalchemy). Added `.with_variant(JSON(), "sqlite")` for test compatibility.
2. `importance_score`: Added `Computed("0.6 * base_importance + 0.4 * dynamic_importance", persisted=True)`.
3. `client.py`: Fixed SecretStr handling to use `.get_secret_value()` instead of `str()`.

### Decision: Integration Platform = Discord
Switched from Slack to Discord (2026-03-15). Reasons: Slack requires paid plan for persistent history; Discord is free, developer-friendly, and has a cleaner bot API.

---

## Phase 2: Retrieval + CLI ✅ COMPLETE (2026-03-15)

**Status**: All checkpoints 2.0–2.8 done, 270 tests passing
**Actual Duration**: ~17 hours (31h estimated)
**Commits**: `69b3963` (CP2.0–2.5), `bf3bc73` (CP2.6–2.7), `c451c50` (CP2.8 Discord)

- [x] 2.0: Context builder with token budget (`src/retrieval/context_builder.py` + GET /v1/search/context)
- [x] 2.1: Structured filter endpoints (type_filter, entity_filter, date_from, date_to on /v1/search)
- [x] 2.2: Superseding chain (transactional supersedes_memory_id + is_superseded flag)
- [x] 2.3: Entity resolution (pg_trgm fuzzy match 0.92 threshold + merge endpoint)
- [x] 2.4: Entity alias + merge endpoints (POST /v1/entities/merge, POST /v1/entities/{id}/aliases)
- [x] 2.5: CLI (typer) — `ob ingest`, `ob search`, `ob context`, `ob worker --sync`, `ob health`
- [x] 2.6: Task + decision endpoints (GET/POST /v1/tasks, PATCH /v1/tasks/{id}, GET/POST /v1/decisions)
- [x] 2.7: Dead-letter retry with retry_count guard (GET /v1/dead-letters, POST /v1/dead-letters/{id}/retry)
- [x] 2.8: *(bonus — moved from Phase 4)* Discord bot (`src/integrations/discord_bot.py`) — on_message ingestion, /search + /status slash commands, 🧠/❌ reactions, user-ID allowlist

**Phase 2 bug fixes (in commit `c451c50`):**
- `extractor.py`: `DecisionExtract.reasoning` changed to `str | None` (Claude returns null)
- `worker.py`: Coerce `reasoning=None → ""` before DB insert
- `search.py`: Deduplicate results by content hash after ranking (prevents duplicate Discord embeds)

**Phase 2 test suite (270 total, all passing):**
```
test_context_builder.py ✅
test_entities.py        ✅
test_tasks.py           ✅
test_decisions.py       ✅
test_queue.py           ✅
test_cli.py             ✅
test_discord_bot.py     14 tests ✅
(+ all 89 Phase 1 tests retained)
────────────────────────────────
Total Phase 1+2:        270 tests ✅
```

---

## Session 4 Notes (2026-03-15) — Phase 2 Complete + Ground Truth Sync

### Content-Hash Dedup (moved to Phase 1)
`POST /v1/memory` now rejects duplicates within 24h using SHA-256 hash stored in `raw_memory.content_hash`. Implemented via Alembic migration `0002_add_content_hash`. Originally planned for Phase 2 but implemented during Phase 1/2 boundary to unblock Discord.

### Entity Merge: Key Implementation Pattern
`POST /v1/entities/merge` uses `session.expunge(source_entity)` before Core SQL operations to avoid ORM identity map conflicts when moving FK references. See CLAUDE.md "ORM Identity Map Conflict" gotcha.

### Architecture Decision: Discord as First-Class Integration
Discord bot runs as opt-in Docker profile (`discord-bot`). Allowlist-gated via `DISCORD_ALLOWED_USER_IDS`. All API calls go through the HTTP API (not direct DB) — maintains clean separation of concerns.

---

## Technical Debt

All pre-Phase-3 items resolved. Current technical debt tracked in `tech-debt.md` (3 Medium, 9 Low).

---

## Session 3.1 Notes (2026-03-15) — Tech Debt + Phase 3 Kickoff

### Tech Debt Cleared
- `GET /v1/memory/{id}` — returns all MemoryItem fields; 404/422 handling
- `GET /v1/queue/status` — returns per-status counts (`pending`, `processing`, `done`, `failed`, `total`) + `oldest_locked_at` as worker health signal

### Phase 3.2: Daily Importance Job
- `src/jobs/importance.py` — `run_importance_job(session)` aggregates all `retrieval_events` with exponential decay: `Σ exp(-age_days / half_life_days)`, normalized by `NORMALIZATION_FACTOR=5` and capped at 1.0
- Memories with zero events decay one step per run: `current * exp(-1 / half_life_days)`, floor at 0.0
- Invokable standalone: `python -m src.jobs.importance`
- No migration needed — `dynamic_importance` column already existed

### Test count: 270 → 287 (+17 tests, all green)

---

## Session 3.2 Notes (2026-03-15) — CP 3.1, CP 3.3, CP 3.4

### CP 3.1: Base Importance Verification
- `base_importance` confirmed dynamic — Claude assigns it per extraction (no hardcoded 0.6)
- Added 5-tier scoring rubric to `EXTRACTION_SYSTEM_PROMPT` to reduce anchoring at 0.5
- Changed JSON schema example from `0.5` → `0.6` (non-round, less anchor bias)
- Retry prompts (`EXTRACTION_RETRY_PROMPT_1/2`) intentionally unchanged — they are JSON recovery only
- New: `tests/test_extractor.py` (8 tests, all green)

### CP 3.3 + CP 3.4: Weekly Synthesis Job
- `src/jobs/synthesis.py` — `run_synthesis_job(session, client, days=7)`: fetch recent memories → bulk-load entity names → build annotated prompt → call Claude → persist as `RawMemory(source="synthesis")` + `MemoryItem(type="context", base_importance=0.8)`
- `python -m src.jobs.synthesis --days 7` — standalone cron invocation
- `src/llm/prompts.py` — `SYNTHESIS_SYSTEM_PROMPT` + `build_synthesis_user_message()` added
- `src/api/routes/queue.py` — `POST /v1/synthesis/run` endpoint (returns synthesis_id, memory_count, date range)
- `src/integrations/discord_bot.py` — `trigger_digest()` helper + `/digest` slash command
- `src/core/config.py` — `synthesis_model = "claude-haiku-4-5-20251001"` (MVP default; set `SYNTHESIS_MODEL=claude-opus-4-6` for production)
- New: `tests/test_synthesis.py` (14 tests, all green), +4 tests in `test_discord_bot.py`

### Test count: 287 → 313 (+26 tests, all green)

---

## Phase 3: Intelligence Layer ✅ COMPLETE (2026-03-15)

**Status**: All checkpoints done, 21h estimated

- [x] 3.1: Base importance scoring — verified dynamic, added scoring rubric. 8 tests. ✅
- [x] 3.2: Daily importance job (`src/jobs/importance.py`) — aggregate retrieval_events, decay dynamic_importance ✅
- [x] 3.3: Weekly synthesis job (`src/jobs/synthesis.py`) — clusters by entities, stores report as MemoryItem. Discord `/digest` command. 14 tests. ✅
- [x] 3.4: Synthesis prompt engineering — `SYNTHESIS_SYSTEM_PROMPT` + `build_synthesis_user_message()` in `src/llm/prompts.py`. ✅
- [x] 3.5: Observability logging — `worker_heartbeat`, `ingestion_complete`, `ingestion_dead_letter`, `queue_depth`. 16 tests. ✅

---

## Phase 4: Hardening + Deploy ✅ COMPLETE (2026-03-16)

- [x] 4.1: Docker Compose production config — resource limits, health checks, restart policies, json-file logging ✅
- [x] 4.2: Caddy reverse proxy — `Caddyfile` with auto-TLS, gzip, security headers; `--proxy-headers` in CMD ✅
- [x] 4.3: Rate limiting middleware — `slowapi`, configurable per-IP limits, 429+Retry-After, 5 tests ✅
- [x] 4.4: pg_dump backups — `scripts/backup.sh` (30-day retention), `scripts/restore.sh` (with verify) ✅
- [x] 4.5: End-to-end integration tests — `tests/test_integration.py`, 10 tests gated on `INTEGRATION_TEST=1` ✅
- [x] 4.6: API docs + CLI help + README — router tags, all 28 env vars documented, Phase 4 deployment guide ✅

---

## Session 5 Notes (2026-03-16) — Phase 4 Complete

### Pre-Phase-4 Debt Cleared
- `IMPLEMENTATION_PLAN.md` "Known tech debt" section updated: `GET /v1/memory/{id}` and `GET /v1/queue/status` marked as resolved (both implemented in Session 3.1)
- `.env.example` updated with synthesis model production note and `DOMAIN` variable

### Phase 4 Highlights
- **Docker Compose**: Added resource limits (api/worker 1 CPU/512M, discord 0.5 CPU/256M), `restart: unless-stopped`, json-file log driver with rotation, health checks
- **Caddy**: New `Caddyfile` for TLS termination. API port changed from `0.0.0.0:8000` to `127.0.0.1:8000` (Caddy fronts traffic). Added `--proxy-headers --forwarded-allow-ips=*` to uvicorn for correct IP passthrough to rate limiter
- **Rate limiting**: `slowapi>=0.1.9` added to dependencies. Custom 429 handler with `Retry-After: 60`. Three configurable limits: memory (50/min), search (100/min), dead-letters (5/min)
- **Backups**: `scripts/backup.sh` strips asyncpg driver from URL before `pg_dump`. `scripts/restore.sh` prompts confirmation, then runs verify query
- **Integration tests**: 10 tests in `tests/test_integration.py` skip unless `INTEGRATION_TEST=1`. Covers vector type, GIN index, HNSW index, GENERATED column, pg_trgm, stale lock, table count, content_hash column

### Test count: 329 → 334 (+5 rate limit tests, 10 integration tests skip by default)

---

## Deployment (2026-03-16)

**Server**: GCP e2-small, Ubuntu 24.04, `34.118.15.81`
**Database**: Supabase (session-mode pooler, port 5432) — migrations at head (0002)
**Services running**: API + Worker (Docker Compose), Discord bot available via `--profile discord`
**Cron jobs**: importance (3 AM daily), synthesis (2 AM Sunday), backup (3:30 AM daily)
**Integration tests**: 10/10 passing against real Supabase

### Deployment gotchas discovered

- **Supabase direct URL is IPv6-only** — GCP VMs have no IPv6. Fix: use session-mode pooler (`aws-X-region.pooler.supabase.com:5432`) — supports `SELECT FOR UPDATE SKIP LOCKED`, has IPv4
- **pytest-asyncio event loop scope mismatch** — `pg_engine` fixture is `scope="module"` but tests ran in function-scoped loops. Fix: added `asyncio_default_test_loop_scope = "module"` and `asyncio_default_fixture_loop_scope = "module"` to `pyproject.toml`
- **Integration test rollback pattern incompatible with asyncpg pooler** — `session.rollback()` in fixture teardown failed with "cannot use Connection.transaction() in a manually started transaction". Fix: removed rollback from `pg_session` fixture
- **Alembic stamp needed** — DB already had `content_hash` column from prior dev work but `alembic_version` was at 0001. Fix: `alembic stamp head` to sync version table without re-running migration
- **docker-compose `version` attribute obsolete** — warning only, no action needed

### Next steps (as of 2026-03-16)

- Add domain + enable Caddy (`--profile caddy`) for HTTPS
- Import AI conversation history (see `import-ai-memory.md`)
- Switch Discord bot on permanently once memories accumulate

---

## Phase 5: AI-Agnostic Access Layer ✅ COMPLETE (2026-03-16)

**Goal**: Make Open Brain accessible from any AI, auto-capture all conversations, enable memory-grounded chat.

### Checkpoint 5.1: MCP Server ✅
- [x] `src/mcp_server.py` — FastMCP server exposing 3 tools over stdio
  - `search_memory(query, limit)` → hybrid search, returns formatted results
  - `get_context(query, limit)` → LLM-ready token-budgeted context block
  - `ingest_memory(text, source)` → POSTs to `/v1/memory`, returns status
- [x] `.mcp.json` — Claude Code project-level MCP config (gitignored, contains API key)
- [x] `fastmcp>=3.0.0` added to `pyproject.toml` dependencies
- [x] `tests/test_mcp_server.py` — 28 tests (happy path + empty results + auth errors + timeouts + connection errors + input validation)

### Checkpoint 5.2: `ob chat` Command ✅
- [x] `cli/ob.py` — added `chat` command with interactive loop
  - Searches Open Brain context on each turn via `_fetch_ob_context()`
  - Injects context into LLM system prompt
  - Supports `--model claude|gemini|openai`, `--topic TOPIC`, `--no-ingest`
  - Auto-ingests conversation at session end (`source=ob-chat`)
  - LLM backends: `_call_claude()`, `_call_gemini()`, `_call_openai()` (optional deps, graceful error if missing)
- [x] `tests/test_ob_chat.py` — 22 tests

### Checkpoint 5.3: Auto-Capture (Claude Code Stop Hook) ✅
- [x] `scripts/capture_claude_code.py` — Stop hook script
  - Reads JSON payload from stdin, parses JSONL transcript
  - Skips sessions < 300 chars, skips `stop_hook_active=True` (loop guard)
  - POSTs to `/v1/memory` with `source=claude-code`; exits 0 always (never breaks Claude Code)
- [x] `~/.claude/settings.json` — Stop hook registered with `OPENBRAIN_API_URL`/`OPENBRAIN_API_KEY` env vars
- [x] `scripts/import_openai.py` — Import ChatGPT conversation export (follows `import_claude.py` pattern)
- [x] `tests/test_capture_claude_code.py` — 26 tests

**Tests**: 410 passing (76 new in this session), 10 skipped (integration), 0 regressions.

---

## Phase 6: Module Expansion ✅ COMPLETE (2026-03-24)

**Spec**: `new-feature-implementation-plan.md`
**Modules**: Todo System, Morning Pulse, Discord RAG Chat
**Phase order**: A (Foundation) → B (Todo) → C (RAG Chat) → D (Pulse) → E (Hardening)

### Phase A: Foundation ✅ COMPLETE (2026-03-23)
- [x] A1: Discord bot refactor → `src/integrations/kernel.py` (pure helpers + `_get_settings`) + `src/integrations/modules/` directory + `core_cog.py` (extracts /search, /digest, /status) + `discord_bot.py` refactored to thin loader with conditional module registration
- [x] A2: 4 new ORM models in `src/core/models.py` (`TodoItem`, `TodoHistory`, `DailyPulse`, `RagConversation`) + migration `alembic/versions/0003_new_modules.py` + 27 new config fields in `src/core/config.py` (feature flags + module settings)
- [x] Tests: `tests/test_bot_modules.py` (4 tests — disabled modules don't register, core always present)

### Phase B: Todo Module ✅ COMPLETE (2026-03-23)
- [x] B1: `src/api/services/todo_service.py` — `create_todo()` + `update_todo()` with atomic history writes + `session.refresh()`
- [x] B2: `src/api/routes/todos.py` — 5 REST endpoints (POST/GET list/GET single/PATCH/GET history)
- [x] B3: `src/integrations/modules/todo_cog.py` — `TodoGroup` (list/add/done/defer) + `parse_natural_date()` + `DoneButton` + `DeferButton` + `DeferModal`
- [x] Tests: `tests/test_todos.py` (20 tests) + `tests/test_todo_cog.py` (20 tests), all green
- **Gotcha**: After `session.flush()`, SQLAlchemy expires `server_default`/`onupdate` columns. Must `await session.refresh(todo)` after flush+commit.

### Phase C: Discord RAG Chat ✅ COMPLETE (2026-03-23)
- [x] C1: `src/integrations/modules/rag_cog.py` — full RAG pipeline:
  - `_parse_model_override()` — `?sonnet`/`?haiku`/bare prefix → (model_id, query)
  - `_build_system_prompt()` + `_build_rag_user_message()` — XML-wrapped context + query for injection defense
  - `_trim_buffer()` — keeps last N user+assistant pairs, drops oldest
  - `_is_conversation_expired()` — TTL check for stale conversations
  - `_load_or_create_conversation()` — fetch or create `RagConversation`, reset expired rows
  - `_handle_rag_message()` — full pipeline: rate limit → search → LLM → save → Discord reply + citations embed
  - `register_rag()` — adds `on_message` listener via `bot.add_listener()`
- [x] `src/llm/client.py` — added `complete_with_history(system, messages, model, max_tokens)` for multi-turn + dynamic model switching
- [x] Tests: `tests/test_rag_cog.py` (28 tests), all green
- **Gotcha**: `get_db()` in `_handle_rag_message` must be mocked via `@asynccontextmanager` pattern in tests.
- **Model switching**: `?sonnet` / `?haiku` prefix switches model for that conversation; `model_name` persisted in DB.

### Phase D: Morning Pulse ✅ COMPLETE (2026-03-24)
- [x] D1: `src/integrations/calendar.py` — ported from Cadence; optional Google deps; async via `asyncio.to_thread`; graceful fallback
- [x] D2: `src/jobs/pulse.py` — `send_morning_pulse()` (cron job: idempotent, fetches calendar+todos, generates Haiku question, sends Discord DM)
- [x] D2: `src/api/routes/pulse.py` — 5 REST endpoints (POST, GET today, PATCH today, GET list, GET by date)
- [x] D3: `src/integrations/modules/pulse_cog.py` — `PulseCog.handle_reply()` (window check → store raw → parse → update → react)
- [x] Tests: `tests/test_calendar.py` (11 tests) + `tests/test_pulse.py` (42 tests), all green
- **Cron setup**: `0 7 * * * docker compose run --rm worker python -m src.jobs.pulse`

### Phase E: Hardening ✅ COMPLETE (2026-03-24)
- [x] Updated `CLAUDE.md` Module Ownership table
- [x] Updated `ARCHITECTURE.md` with Phase D module system and `daily_pulse` table
- [x] 641 tests passing, no regressions

---

## Security Audit ✅ COMPLETE (2026-03-24)

Full security audit of all 15 original items (C1–C5, H1–H4, M1–M5, L1) plus 4 new findings (N1–N4).
All items resolved. 639 tests passing. Register (`security-improve-plan.md`) retired.

Key fixes applied:
- **N1**: Added `max_length` validators to Todo/Task Pydantic models (todos.py, tasks.py)
- **N2**: Added credential-rejection instruction to `EXTRACTION_RETRY_PROMPT_2` (prompts.py)
- **N3**: Added rate limits to 15 previously unprotected routes (todos, tasks, pulse, synthesis, memory GET)
- **N4**: Added rate limit to `GET /v1/memory/{id}`

Remaining manual action: Narrow `--forwarded-allow-ips` from `/8` to exact Docker subnet after Caddy reverse proxy is deployed.

---

## Tech Debt Clearance ✅ COMPLETE (2026-03-24)

All tech-debt items resolved. The register (`tech-debt.md`) has been retired. Two items deferred to CLAUDE.md:
- **L3** — Hardcoded LIMIT 100 in search CTEs. Revisit when corpus exceeds 10k memories.
- **L4** — `merge_entities()` length. Revisit if function exceeds 200 lines.

---

## Morning Pulse Modal Upgrade ✅ COMPLETE (2026-03-24)

Replaced free-text DM reply flow with Discord interactive modals for structured input.

- [x] `PulseView` (persistent, `timeout=None`) with "Log my morning" + "Skip" buttons
- [x] `PulseModal` with 5 structured fields: sleep (1-5), energy (1-5), wake time, AI question response (dynamic label), notes
- [x] Validation (1-5 range), double-submit prevention, button disabling after submit
- [x] Buttons sent via REST components JSON; persistent view re-registered on bot restart
- [x] AI question prompt upgraded: operational/reflective alternation based on yesterday's question type
- [x] Embed redesigned: AI question displayed prominently, "Log my morning" CTA replaces "Reply within 2 hours"
- [x] Free-text DM reply path gated behind `pulse_accept_freetext=False` (disabled by default)
- [x] Schema: added `ai_question_response` (Text) and `notes` (Text) columns to `daily_pulse`
- [x] Migration: `0004_pulse_modal_columns.py`
- [x] API: added `ai_question_response`, `notes` to PulseUpdate/PulseResponse, added "completed" status
- [x] 27 new tests (69 total pulse tests, 666 total suite)

**Deploy note**: Run `alembic upgrade head` to apply migration 0004 before deploying.

---

## Dashboard Enhancement ✅ COMPLETE (2026-04-03)

6-feature enhancement for web dashboard feature parity with Discord bot + new UX.

### F1: Morning AI Question on Web ✅
- [x] `POST /v1/pulse/start` endpoint — queries open todos, fetches yesterday's question for alternation, calls `_generate_ai_question()`, creates pulse with ai_question populated
- [x] Frontend `createPulse()` calls `/v1/pulse/start`; 409 fallback fetches existing pulse via `GET /v1/pulse/today`
- [x] Broadened exception catch in `_generate_ai_question()` to `except Exception` (was httpx-only)
- [x] 6 backend tests + 2 frontend tests

### F2: start_date on TodoItem ✅
- [x] Migration `0006_add_start_date.py` — nullable `DateTime(timezone=True)`
- [x] ORM model, Pydantic schemas (TodoCreate/TodoUpdate/TodoResponse), service functions (_snapshot, create_todo, update_todo)
- [x] Frontend types, AddTaskForm date range toggle, `getDueBadge()` "Active" badge for range tasks
- [x] 4 backend tests + 2 frontend tests (getDueBadge + date range toggle)

### F3: Today/All Tabs ✅
- [x] Client-side only — `filterTodayTodos()` in `use-todos.ts`: overdue, due today, active range (start_date ≤ today ≤ due_date)
- [x] `Tabs`/`TabsList`/`TabsTrigger`/`TabsContent` in `task-list.tsx` with badge counts
- [x] 8 frontend tests (filterTodayTodos) + 4 component tests (tabs)

### F4: Defer UI ✅
- [x] `DeferPopover` component with date picker + optional reason textarea
- [x] `deferTodo()` hook function with optimistic update + rollback
- [x] No backend changes — existing PATCH auto-detects event_type="deferred"
- [x] 2 frontend tests (defer dialog + reason)

### F5: Overdue Enforcement ✅
- [x] `GET /v1/todos/overdue-undeferred` endpoint — declared before `/{todo_id}`, subquery excludes deferred-today
- [x] `useOverdue` hook — fetches endpoint, re-fetches on `visibilitychange`
- [x] `OverdueModal` component — non-dismissable dialog, required reason, closes when all handled
- [x] 6 backend tests + 4 hook tests + 5 component tests

### F6: Reopened Event + Undo Toast ✅
- [x] Backend: "reopened" event_type when `status=open` and `old_status=done`
- [x] Frontend: `completeTodo()` shows Sonner toast with "Undo" action (5s), `undoComplete()` with rollback
- [x] 2 backend tests + 3 frontend tests

**Files modified**: 15 modified, 6 new (1 migration, 2 hooks, 2 components, 1 test file)
**Test delta**: +39 backend, +48 frontend (from 784 to 843 total)
**Deploy note**: Run `alembic upgrade head` to apply migration 0006 (add `start_date` column).

---

## Risk Tracking

| Risk | Impact | Mitigation | Status |
|---|---|---|---|
| UUID type mismatch in Alembic | Critical | Audit all FK types before running migration | ✅ Resolved (CP3) |
| Stale lock reclaim logic missing | Critical | Explicitly test with locked_at < now() - 5 min | ✅ Resolved (CP6) |
| GIN index expression mismatch | High | Copy exact expression from migration to query | ✅ Resolved (CP8) |
| Voyage AI rate limit not handled | High | tenacity retry + exponential backoff | ✅ Resolved (CP4) |
| Worker crashes leave jobs in processing | High | TTL reclaim + test crash recovery | ✅ Resolved (CP6) |
| pgvector ORM type mismatch (JSONB vs Vector) | High | Use `Vector(1024).with_variant(JSON(), "sqlite")` in models.py | ✅ Resolved (Session 3) |
| LLM worker cost spike from JSON parse failure | High | Strip markdown code fences before json.loads() | ✅ Resolved (Session 3) |
| Discord duplicate processing (no dedup) | High | Content-hash dedup on POST /v1/memory before Discord integration goes live | ✅ Resolved (CP1/2 boundary, migration 0002) |
| No production smoke test (embeddings unverified) | Medium | Run 5 real memories through pipeline, verify vector column | ✅ Resolved (2026-03-15: 20/20 rows non-null vectors confirmed) |
| dynamic_importance stays 0.0 (no aggregation job) | High | retrieval_events are logged but never aggregated until Phase 3.2 | ✅ Resolved (Session 3.1: `src/jobs/importance.py`) |

---

## Team Assignments (if using swarm)

- **Lead Architect**: Oversees all phases, reviews critical files (models, worker, migration)
- **Backend Engineer**: Phase 1 scaffold + core infrastructure
- **Pipeline Engineer**: Phase 1 pipeline stages + worker
- **API Engineer**: Phase 1 + 2 API routes
- **DevOps Engineer**: Docker, migrations, Phase 4 deploy
