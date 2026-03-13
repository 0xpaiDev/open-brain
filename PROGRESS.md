# Open Brain Implementation Progress

**Project Start**: 2026-03-13
**Target Completion**: ~2026-04-24 (6 weeks)
**Current Phase**: Phase 1 — Foundation (Checkpoints 0–3 complete)
**Overall Progress**: ~30% (Checkpoints 0–3 complete, 14 tests passing)

---

## Phase 1: Foundation (30% → target 100%)

**Status**: In progress (Checkpoints 0–3 complete, 4–9 remaining)
**Est. Duration**: 44 hours + 15 hours (tests integrated) = ~59h
**Start Date**: 2026-03-13
**Target Completion**: ~2026-03-20 (7 days, ~8h/day pace)
**Approach**: Test-first self-confirm loop — each checkpoint includes paired test file(s)

---

### Checkpoint 0: Test Infrastructure (FIRST — before any source code) ✅
- [x] 0.1: Create `tests/__init__.py`
- [x] 0.2: Create `tests/conftest.py` — complete test infrastructure
  - Async SQLite test DB (`create_async_engine`)
  - Fixtures: `async_session`, `mock_anthropic_client`, `mock_voyage_client`
  - FastAPI test client fixture + override_get_db dependency
  - API key headers fixture: `{"X-API-Key": "test-secret-key"}`

**Verification**: `python -c "import pytest; from tests.conftest import *"` — imports cleanly ✅

---

### Checkpoint 1: Project Scaffold ✅ (COMPLETE)
- [x] 1.0a: Create `.gitignore` (Python + environment) — updated to exclude .dockerignore tracking
- [x] 1.0b: Create `.dockerignore` — excludes .env, __pycache__, .pytest_cache, etc.
- [x] 1.0c: Create `Makefile` with shortcuts (make up, down, migrate, test, lint, format, logs-*)
- [x] 1.0d: Create `pyproject.toml` with dependencies — uv-managed, 50+ packages
- [x] 1.0e: Create `Dockerfile` (multi-stage: builder + runtime)
- [x] 1.0f: Create `docker-compose.yml` (db, migrate, api, worker services + profiles)
- [x] 1.0g: Create `.env.example` template — 25 env vars with defaults

**Verification**: All files exist, `pyproject.toml` valid TOML ✅
**Commit**: `feat(phase-1): add project scaffold and Docker configuration`

---

### Checkpoint 2: Core Infrastructure + Tests ✅ (COMPLETE)

**Tests written & implemented:**
- [x] 1.1a: `tests/test_config.py` (4 tests passing)
  - `test_settings_loads_from_env` ✅
  - `test_secret_str_not_logged` ✅
  - `test_embedding_dimensions_validator` ✅
  - `test_default_values` ✅

- [x] 1.2a: `tests/test_database.py` (3 tests passing)
  - `test_health_check_fails_when_engine_none` ✅
  - `test_health_check_fails_on_connection_error` ✅
  - `test_get_db_requires_initialization` ✅

**Implementation complete:**
- [x] 1.1b: `src/core/config.py` — pydantic-settings with SecretStr
  - Settings class with 25 env vars (database, API, LLM, search weights, etc.)
  - `ConfigDict` for Pydantic v2
  - Validators for `embedding_dimensions` (only 1024) and search weights (0–1)
  - Module-level lazy singleton: handles missing env vars gracefully

- [x] 1.2b: `src/core/database.py` — async engine setup
  - `create_async_engine()` with pool_pre_ping=True, pool_size=5, max_overflow=5
  - `AsyncSessionLocal` factory
  - `get_db()` async generator dependency
  - `health_check()` function (SELECT 1 connectivity test)
  - `init_db()` and `close_db()` for lifespan management

**Verification**: `pytest tests/test_config.py tests/test_database.py -v` → **7/7 tests green** ✅
**Commit**: `feat(phase-1): implement core infrastructure (config, database) with tests`

---

### Checkpoint 3: Models + Alembic Migration ✅ (COMPLETE)

**Tests written & implemented:**
- [x] 1.3a: `tests/test_models.py` (7 tests passing)
  - `test_all_tables_exist` ✅ (11 tables)
  - `test_uuid_pk_on_simple_tables` ✅ (FIX-1 validation)
  - `test_entity_relations_composite_pk` ✅ (FIX-5 validation)
  - `test_memory_entity_links_composite_pk` ✅ (FIX-5 validation)
  - `test_refinement_queue_has_required_columns` ✅
  - `test_failed_refinements_has_queue_id_fk` ✅
  - `test_foreign_key_types_match_references` ✅

**Implementation complete:**
- [x] 1.3b: `src/core/models.py` — 11 SQLAlchemy ORM tables
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

- [x] 1.4a: `alembic/env.py` — async support
  - Configured with `from src.core.models import Base`
  - `target_metadata = Base.metadata` for autogenerate

- [x] 1.4b: `alembic/versions/0001_initial_schema.py` — **MANUAL DDL** (FIX-4 compliant)
  - All 11 tables with UUID PKs and composite PKs
  - **HNSW index**: `CREATE INDEX ... USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)` (FIX-4)
  - **GIN index**: `CREATE INDEX ... USING GIN (to_tsvector('english', content))` — exact expression for FIX-4 compliance
  - B-tree indexes: type, created_at, importance_score, status, locked_at for query optimization
  - `importance_score GENERATED ALWAYS AS (0.6 * base_importance + 0.4 * dynamic_importance) STORED`
  - pgvector and pg_trgm extensions

- [x] 1.4c: Alembic CLI configured
  - `alembic.ini` updated with postgres URL
  - Ready for `alembic upgrade head` and `alembic downgrade -1`

**Verification**: `pytest tests/test_models.py -v` → **7/7 tests green** ✅
**Verification**: `from src.core.models import Base; print(Base.metadata.tables.keys())` → 11 tables ✅
**Commit**: `feat(phase-1): implement ORM models and Alembic migration`

---

### Checkpoint 3 (cont'd): Alembic & Migration (1.4) — CRITICAL
- [ ] 1.4a: `alembic/env.py` — async engine, imports all models for autogenerate
  - Configure async execution
  - Import all models from src.core.models
  - Use sqlalchemy.inspect for autogenerate

- [ ] 1.4b: `alembic/versions/0001_initial_schema.py` — MANUAL DDL (not autogenerated)
  - Run `alembic revision --autogenerate -m "Initial schema"` to get skeleton
  - **MANUAL ADDITIONS**:
    - HNSW index: `CREATE INDEX ... USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)`
    - GIN index: `CREATE INDEX ... USING GIN (to_tsvector('english', content))`
    - B-tree indexes on type, created_at, status, due_date, entity names
  - Check: all 12 tables with correct types (UUID, not BIGINT)
  - Check: composite PKs on entity_relations and memory_entity_links
  - Check: GENERATED column for importance_score

- [ ] 1.4c: Alembic CLI working
  - `alembic current` — show current revision
  - `alembic upgrade head` — apply migrations
  - `alembic downgrade -1` — test rollback

**Verification**:
```bash
# Set SQLALCHEMY_URL in .env from Supabase project dashboard (direct connection, port 5432)
alembic upgrade head
psql $SQLALCHEMY_URL -c "SELECT COUNT(*) FROM pg_tables WHERE schemaname='public'"
# Should show 11 tables (public schema)
```

**Note**: Tests are already written in Checkpoint 2 (test_models.py) to catch UUID/composite PK issues before migration

---

### Checkpoint 4: LLM Clients + Tests (1.7)

**Write tests first:**
- [ ] 1.7a-test: `tests/test_llm_clients.py`
  - `test_anthropic_client_returns_string` — mock Anthropic, verify response is str
  - `test_voyage_client_returns_vector` — mock Voyage, verify list[float] len 1024
  - `test_extraction_failed_raised_on_bad_response` — bad JSON → ExtractionFailed
  - `test_embedding_failed_after_retries` — RateLimitError 3x → EmbeddingFailed

- [ ] 1.7b-test: `tests/test_prompts.py`
  - `test_user_input_wrapped_in_delimiters` — `<user_input>` in all prompts
  - `test_prompts_are_strings` — all constants are non-empty strings

**Then implement:**
- [ ] 1.7c: `src/llm/client.py` — module-level singletons
  - AnthropicClient (async): `complete_anthropic(system, user, model, max_tokens)` → string response
  - VoyageEmbeddingClient: `embed(text, model)` → list[float], wrapped in asyncio.to_thread()
  - Both use tenacity for retry (3 attempts, 2/4/8s backoff)
  - Error handling: raise structured exceptions (ExtractionFailed, EmbeddingFailed)

- [ ] 1.7d: `src/llm/prompts.py` — typed prompt constants
  - EXTRACTION_SYSTEM: main extraction prompt with `<user_input>{text}</user_input>` delimiters
  - EXTRACTION_RETRY_1, EXTRACTION_RETRY_2: escalating prompts
  - SYNTHESIS_SYSTEM: weekly report generation
  - All prompts use structured markers for user input (prompt injection defense)

**Run tests**: `pytest tests/test_llm_clients.py tests/test_prompts.py -v` → all green

**Verification**:
```python
from src.llm.client import anthropic_client, embedding_client
# Should not raise, modules load
```

---

### Checkpoint 5: Pipeline Stages + Tests (1.8–1.12) — HIGH PRIORITY, IN ORDER

**Write tests first (HIGH PRIORITY):**
- [ ] 1.8a-test: `tests/test_normalizer.py`
  - `test_normalize_strips_whitespace`
  - `test_normalize_fixes_unicode`
  - `test_chunk_splits_long_text` — > 2000 tokens → multiple chunks
  - `test_chunk_returns_single_for_short_text`

- [ ] 1.9a-test: `tests/test_extractor.py`
  - `test_extract_attempt_0_uses_full_prompt` — mock LLM, valid JSON → ExtractionResult
  - `test_extract_attempt_1_uses_retry_prompt`
  - `test_extract_raises_on_invalid_json` → ExtractionFailed

- [ ] 1.10a-test: `tests/test_validator.py`
  - `test_validate_normalizes_entity_names` — " Claude AI " → "claude ai"
  - `test_validate_deduplicates_entities` — duplicates become one
  - `test_validate_raises_on_missing_content` → ValidationFailed

- [ ] 1.11a-test: `tests/test_embedder.py`
  - `test_embed_returns_1024_floats` — mock Voyage → list[float] len 1024
  - `test_embed_retries_on_rate_limit` — fails 2x, succeeds 3rd → vector
  - `test_embed_raises_after_3_failures` → EmbeddingFailed

**Then implement (in order, one at a time):**
- [ ] 1.8b: `src/pipeline/normalizer.py`
  - `normalize(text: str) -> str`: strip whitespace, fix unicode, dedent
  - `chunk(text: str, max_tokens=2000) -> list[str]`: split long text into chunks
  - Uses `tiktoken` to count tokens

- [ ] 1.9b: `src/pipeline/extractor.py`
  - Pydantic schemas for ExtractionResult, EntityExtract, DecisionExtract, TaskExtract
  - `extract(normalized_text: str, attempt: int) -> ExtractionResult`
  - Attempt 0: full prompt; Attempt 1: stricter; Attempt 2: fallback minimal
  - Raises ExtractionFailed if JSON parse fails

- [ ] 1.10b: `src/pipeline/validator.py`
  - `validate(extraction: ExtractionResult) -> ExtractionResult`
  - Schema validation (already done by Pydantic)
  - Entity name normalization (lowercase, strip, fuzzy dedup)
  - Returns validated extraction or raises ValidationFailed

- [ ] 1.11b: `src/pipeline/embedder.py`
  - EmbeddingProvider protocol: `async def embed(text: str) -> list[float]`
  - VoyageEmbeddingProvider: uses `voyageai.Client().embed()` via asyncio.to_thread()
  - Tenacity retry on rate limit / 5xx
  - Raises EmbeddingFailed after 3 attempts

- [ ] 1.12a-test: `tests/test_entity_resolver.py`
  - `test_resolves_exact_match_via_alias` — existing entity returned
  - `test_creates_new_entity_when_no_match`
  - `test_fuzzy_match_at_threshold` — "Anthropic" vs "Anthropoic" → merged
  - `test_no_merge_below_threshold` — "Anthropic" vs "Amazon" → separate

- [ ] 1.12b: `src/pipeline/entity_resolver.py`
  - `async def resolve_entities(session, entities: list[EntityExtract]) -> list[Entity]`
  - For each entity:
    - Check aliases for canonical match
    - Fuzzy match with pg_trgm at 0.92 threshold (auto-merge, same type only)
    - Flag 0.70–0.92 matches for human review (future phase)
    - Insert or update entity + aliases
  - Use `INSERT ... ON CONFLICT DO NOTHING`

**Run tests**: `pytest tests/test_normalizer.py tests/test_extractor.py tests/test_validator.py tests/test_embedder.py tests/test_entity_resolver.py -v` → all green

**Verification**: All pipeline modules import cleanly, no circular deps

---

### Checkpoint 6: Worker + Tests (1.13) — CRITICAL (highest risk)

**Write tests first (HIGHEST PRIORITY):**
- [ ] 1.13a-test: `tests/test_worker.py` — CRITICAL TESTS
  - `test_claim_batch_picks_pending_job` — pending row reclaimed
  - `test_claim_batch_reclaims_stale_processing` — locked_at < now() - 6min, status='processing' → reclaimed (FIX-2 validation)
  - `test_claim_batch_skips_fresh_processing` — locked_at < now() - 1min → NOT reclaimed
  - `test_process_job_creates_memory_item` — mock Anthropic + Voyage, full pipeline → memory_items created
  - `test_process_job_creates_entities_and_links` — same → entities + memory_entity_links created
  - `test_process_job_sets_embedding` — memory_items.embedding is not None
  - `test_3_failure_path_moves_to_dead_letter` — attempts=2, mock fails → failed_refinements row, queue status='failed' (FIX-3 validation)
  - `test_process_job_succeeds_after_retry` — attempts=1, fail then succeed → memory_items created

**Then implement:**
- [ ] 1.13b: `src/pipeline/worker.py` — async polling loop
  - `claim_batch()`: UPDATE ... WHERE status = 'pending' OR (status = 'processing' AND locked_at < now() - interval '5 minutes') FOR UPDATE SKIP LOCKED
  - Sets: status='processing', locked_at=now(), updated_at=now(), attempts += 1
  - `process_job()`: normalize → extract → validate → embed → store + entity resolution
  - Each job gets its own session (no session sharing across tasks)
  - Retry logic: on ExtractionFailed, if attempts < 3, reset to pending; else write to dead letter
  - Embedding failures: write to failed_refinements with error_reason='embedding_failure'
  - Polling loop: `await asyncio.sleep(poll_interval + random.uniform(0, 2.0))` (jitter)

- [ ] 1.13c: Memory write function
  - `async def store_memory_item(session, raw, extraction, embedding)`
  - Insert memory_items row with computed base_importance
  - Create entity_relations rows
  - Update memory_entity_links with ON CONFLICT DO NOTHING
  - All in one transaction: `async with session.begin():`
  - Handle superseding: if extraction has supersedes_id, set old.is_superseded=true

- [ ] 1.13d: Dead letter handling
  - `async def move_to_dead_letter(session, queue_row)`
  - Insert failed_refinements row with error_reason
  - Set refinement_queue row status='failed'

**Run tests**: `pytest tests/test_worker.py -v` → all green (validates FIX-2 + FIX-3)

**Verification**:
```bash
# All test_worker.py tests pass, confirming:
# - Stale lock reclaim logic (FIX-2)
# - 3-failure dead letter path (FIX-3)
# - Full pipeline end-to-end
```

---

### Checkpoint 7: API Ingestion + Tests (1.6) — HIGH PRIORITY

**Write tests first (HIGH PRIORITY):**
- [ ] 1.6a-test: `tests/test_ingestion.py`
  - `test_post_memory_returns_202` — POST /v1/memory + auth key → 202, body has raw_id (UUID)
  - `test_post_memory_creates_raw_memory_row` — after POST, raw_memory row in DB
  - `test_post_memory_creates_refinement_queue_row` — after POST, refinement_queue row with status='pending'
  - `test_post_memory_no_auth_returns_401` — no X-API-Key → 401
  - `test_post_memory_wrong_key_returns_401` — wrong key → 401
  - `test_post_memory_bad_json_returns_422` → 422
  - `test_health_endpoint_returns_200` — GET /health → 200 (no auth)
  - `test_ready_endpoint_passes_with_db` — GET /ready → 200 if DB up, else 503

**Then implement:**
- [ ] 1.6b: `src/api/routes/memory.py` — POST /v1/memory endpoint
  - Input schema: { text: str, source: str (default "api"), metadata?: dict }
  - Insert raw_memory row
  - Insert refinement_queue row with status='pending'
  - Return HTTP 202 with `{"raw_id": <uuid>, "status": "queued"}`

- [ ] 1.6c: `src/api/middleware/auth.py`
  - Check X-API-Key header against settings.api_key
  - Return 401 if missing or wrong
  - Skip auth for GET /health only

- [ ] 1.6d: `src/api/routes/health.py`
  - GET /health → HTTP 200 (always passes)
  - GET /ready → HTTP 200 if DB connected and queue responding, else 503

- [ ] 1.6e: `src/api/main.py` — FastAPI app factory
  - Create app with title, description
  - Register middleware: auth, logging
  - Include routers: memory, search, health, entities, tasks, decisions, queue
  - Define lifespan (startup/shutdown)
  - Auto-generated docs at /docs

**Run tests**: `pytest tests/test_ingestion.py -v` → all green

**Verification**: `POST localhost:8000/v1/memory -H "X-API-Key: test-key" -d '{"text":"test"}'` → HTTP 202

---

### Checkpoint 8: Search & Ranking + Tests (1.14) — HIGH PRIORITY

**Write tests first (HIGH PRIORITY):**
- [ ] 1.14a-test: `tests/test_ranking.py` (pure functions, easy wins)
  - `test_combined_score_weights_sum` — 0.5 + 0.2 + 0.2 + 0.1 = 1.0
  - `test_recency_score_decreases_over_time` — 1-day-old > 30-day-old
  - `test_recency_score_is_between_0_and_1`
  - `test_combined_score_with_zero_inputs` → 0.0

- [ ] 1.14b-test: `tests/test_search.py`
  - `test_hybrid_search_returns_ranked_results` — insert 5 memories, query → correct order
  - `test_hybrid_search_respects_type_filter` — filter by type → only that type returned
  - `test_hybrid_search_logs_retrieval_events` — after search, retrieval_events rows created (FIX-3 validation)
  - `test_search_endpoint_returns_200` — GET /v1/search?q=test → 200 with results

**Then implement:**
- [ ] 1.14c: `src/retrieval/ranking.py` — pure functions
  - Constants: WEIGHT_VECTOR (0.50), WEIGHT_KEYWORD (0.20), WEIGHT_IMPORTANCE (0.20), WEIGHT_RECENCY (0.10)
  - `recency_score(created_at) -> float`: exponential decay with half-life from settings
  - `combined_score(vscore, kscore, importance, created_at) -> float`: weighted sum

- [ ] 1.14d: `src/retrieval/search.py` — hybrid search SQL + execution
  - `async def hybrid_search(session, query_text, query_embedding, limit=10, type_filter=None)`
  - Vector search CTE: cosine distance, LIMIT 100
  - Keyword search CTE: FTS with GIN index, LIMIT 100
  - FULL OUTER JOIN, rescores
  - Returns list[SearchResult] sorted by combined_score
  - **Verify**: GIN index query uses identical `to_tsvector('english', content)` expression (FIX-4 validation)

- [ ] 1.14e: `src/api/routes/search.py` — GET /v1/search
  - Input: q: str, limit: int = 10, type_filter: str = None
  - Compute query embedding via VoyageEmbeddingClient
  - Call hybrid_search
  - Log each result to retrieval_events table
  - Return ranked list with scores

**Run tests**: `pytest tests/test_ranking.py tests/test_search.py -v` → all green (validates FIX-3 + FIX-4)

**Verification**:
```bash
# Ingest a memory with extraction
# Query it back
# Verify it ranks
GET localhost:8000/v1/search?q=test
```

---

### Checkpoint 9: Full Test Suite Pass (1.15) — CONFIRMATION PHASE

All test files from Checkpoints 0-8 are complete. This checkpoint runs the full suite and confirms the self-confirm loop is working.

- [ ] 1.15a: Run full test suite
  - `pytest tests/ -v --tb=short` → all tests green
  - Confirms all modules integrate cleanly

- [ ] 1.15b: Check test coverage
  - `pytest tests/ --cov=src --cov-report=term-missing`
  - Target: >80% coverage on critical modules:
    - `src/pipeline/worker.py` (stale lock reclaim, 3-failure path)
    - `src/retrieval/search.py` (hybrid ranking)
    - `src/api/routes/memory.py` (ingestion contract)

- [ ] 1.15c: Fix any remaining edge cases or slow tests
  - Each test should run in <1s (except integration tests with real async DB)
  - All mocked tests run in <100ms

**Verification**:
```bash
pytest tests/ -v --tb=short
# Expected: 50+ tests, all green, 0 warnings, 0 skipped
```

---

## Phase 1 Verification Gates (must all pass before Phase 2)

- [ ] Gate 1: `docker compose up` → api and worker services healthy (db service no longer exists; Supabase is external)
- [ ] Gate 2: `psql $SQLALCHEMY_URL -c "SELECT COUNT(*) FROM pg_tables WHERE schemaname='public'"` → 11 tables
- [ ] Gate 3: `POST /v1/memory` → 202 with raw_id
- [ ] Gate 4: raw_memory + refinement_queue rows in Supabase DB
- [ ] Gate 5: Worker processes job → memory_items + entities + embedding created
- [ ] Gate 6: 3-failure retry path → failed_refinements row
- [ ] Gate 7: Stale lock reclaim: set locked_at = now() - 6 min, worker reclaims
- [ ] Gate 8: `GET /v1/search?q=test` → ranked results

---

## Phase 2: Retrieval + CLI (0% → target 50%)

**Status**: Pending Phase 1 completion
**Est. Duration**: 31 hours

- [ ] 2.1: Context builder with token budget
- [ ] 2.2: Structured filter endpoints
- [ ] 2.3: Superseding chain (transactional)
- [ ] 2.4: Entity alias + merge endpoints
- [ ] 2.5: CLI (typer) with --sync flag
- [ ] 2.6: Task + decision endpoints
- [ ] 2.7: Dead-letter retry with retry_count guard
- [ ] 2.8: GET /v1/search/context endpoint

---

## Phase 3: Intelligence Layer (0% → target 75%)

**Status**: Pending Phase 2 completion
**Est. Duration**: 21 hours

- [ ] 3.1: Base importance scoring in extraction
- [ ] 3.2: Daily importance job
- [ ] 3.3: Weekly synthesis job
- [ ] 3.4: Synthesis prompt engineering
- [ ] 3.5: Observability logging

---

## Phase 4: Hardening + Deploy (0% → target 100%)

**Status**: Pending Phase 3 completion
**Est. Duration**: 17 hours

- [ ] 4.1: Docker Compose production config
- [ ] 4.2: VPS deploy + Caddy reverse proxy
- [ ] 4.3: Rate limiting middleware
- [ ] 4.4: pg_dump backups + restore verification
- [ ] 4.5: End-to-end integration tests
- [ ] 4.6: API docs + CLI help + README

---

## Risk Tracking

| Risk | Impact | Mitigation | Status |
|---|---|---|---|
| UUID type mismatch in Alembic | Critical | Audit all FK types before running migration | 🔴 Not started |
| Stale lock reclaim logic missing | Critical | Explicitly test with locked_at < now() - 5 min | 🔴 Not started |
| GIN index expression mismatch | High | Copy exact expression from migration to query | 🔴 Not started |
| Voyage AI rate limit not handled | High | tenacity retry + exponential backoff | 🔴 Not started |
| Worker crashes leave jobs in processing | High | TTL reclaim + test crash recovery | 🔴 Not started |

---

## Team Assignments (if using swarm)

- **Lead Architect**: Oversees all phases, reviews critical files (models, worker, migration)
- **Backend Engineer**: Phase 1 scaffold + core infrastructure
- **Pipeline Engineer**: Phase 1 pipeline stages + worker
- **API Engineer**: Phase 1 + 2 API routes
- **DevOps Engineer**: Docker, migrations, Phase 4 deploy

---

## Notes

- Each checkpoint must pass verification before moving to next
- All code uses async/await throughout (no sync blocks except via asyncio.to_thread)
- Tests mock external APIs (Anthropic, Voyage), never call production APIs in tests
- Git commits at each checkpoint with meaningful messages
- `PROGRESS.md` updated daily with blockers and completed tasks
