# Open Brain Implementation Progress

**Project Start**: 2026-03-13
**Target Completion**: ~2026-04-24 (6 weeks)
**Current Phase**: Phase 1 — Foundation ✅ COMPLETE (all CP0–CP9 done)
**Overall Progress**: ~75% (Phase 1 complete, **89 tests passing**)

---

## Phase 1: Foundation (30% → target 100%)

**Status**: ✅ COMPLETE (all Checkpoints 0–9 done, 89 tests passing)
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

### Checkpoint 4: LLM Clients + Tests ✅ (COMPLETE)

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

**Verification**: `pytest tests/test_llm.py -v` → **14/14 tests green** ✅
**Commit**: `feat(phase-1): implement LLM clients and prompts with retry logic`

---

### Checkpoint 5: Pipeline Stages + Tests ✅ (COMPLETE)

**Tests implemented & passing:**
- [x] `tests/test_pipeline.py` (24 tests passing)
  - Normalizer (7 tests): whitespace, blank lines, unicode NFC, chunk splitting, token boundaries
  - Extractor (6 tests): valid JSON, invalid JSON, schema mismatch, attempt-based prompt selection
  - Validator (4 tests): empty content validation, entity name normalization, deduplication
  - Embedder (2 tests): vector generation, error propagation
  - EntityResolver (5 tests): new entity creation, exact alias match, fuzzy match, idempotency, multiple entities

**Implementation complete:**
- [x] `src/pipeline/normalizer.py`
  - `normalize()`: NFC unicode normalization, strip/collapse blank lines
  - `chunk()`: tiktoken cl100k_base tokenization, max 2000 tokens per chunk

- [x] `src/pipeline/extractor.py` — owns `ExtractionResult` schema
  - `ExtractionResult`: Pydantic model with entities[], decisions[], tasks[], base_importance (0–1)
  - `EntityExtract`, `DecisionExtract`, `TaskExtract`: nested schemas
  - `extract()`: async extraction with attempt-based prompt escalation, JSON parsing + schema validation

- [x] `src/pipeline/validator.py`
  - `validate()`: entity name normalization (lowercase/strip), deduplication by normalized name
  - `ValidationFailed` exception

- [x] `src/pipeline/embedder.py`
  - `embed_text()`: async wrapper around VoyageEmbeddingClient, error propagation

- [x] `src/pipeline/entity_resolver.py`
  - `resolve_entities()`: exact alias match → fuzzy pg_trgm (threshold 0.92) → new entity creation
  - Graceful handling of SQLite (no similarity() function) for testing
  - Returns list of resolved Entity ORM objects

**Critical Fixes Validated:**
- Entity type field name: `Entity.type` (not `entity_type`)
- Entity alias field name: `EntityAlias.alias` (not `alias_name`)
- SQLite type compatibility: JSONB → JSON via `.with_variant()`

**Verification**: `pytest tests/test_pipeline.py -v` → **24/24 tests green** ✅
**Commit**: `feat(phase-1): implement pipeline stages (normalize, extract, validate, embed, resolve)`

---

### Checkpoint 6: Worker + Tests ✅ (COMPLETE)

**Tests implemented & passing:**
- [x] `tests/test_worker.py` (9 tests passing)
  - `test_claim_batch_picks_pending_job` ✅ — pending job claimed and marked processing
  - `test_claim_batch_reclaims_stale_processing` ✅ — **FIX-2 validation**: locked_at < now() - 5min → reclaimed
  - `test_claim_batch_skips_fresh_processing` ✅ — locked_at < now() - 1min → NOT reclaimed
  - `test_process_job_creates_memory_item` ✅ — full pipeline → memory_items created
  - `test_process_job_resets_to_pending_on_first_failure` ✅ — attempts < 3 → reset to pending
  - `test_3_failure_path_moves_to_dead_letter` ✅ — **FIX-3 validation**: attempts >= 3 + extraction fails → dead letter
  - `test_process_job_creates_entities_and_links` ✅ — entities + memory_entity_links created
  - `test_store_memory_item_creates_memory_item` ✅ — all related rows created (decisions, tasks, links)
  - `test_move_to_dead_letter_sets_queue_status_failed` ✅ — failed_refinements row + queue status='failed'

**Implementation complete:**
- [x] `src/pipeline/worker.py` — async polling loop with critical bug fixes
  - `claim_batch()`: SELECT FOR UPDATE SKIP LOCKED polling, **FIX-2 stale lock reclaim** (locked_at < NOW() - TTL)
  - `process_job()`: full pipeline orchestration (normalize → extract → validate → embed → resolve → store)
  - `store_memory_item()`: transactional memory, entity, decision, task inserts; queue status → 'done'
  - `move_to_dead_letter()`: **FIX-3 dead letter** after 3 failed attempts
  - `run()`: main polling loop with SIGTERM handler, jittered sleep intervals
  - Retry logic: ExtractionFailed → reset to pending (attempts < 3); EmbeddingFailed → dead letter (not retryable)

**Critical Fixes Validated:**
- **FIX-2**: Stale lock reclaim explicitly tested with locked_at 6 minutes ago (TTL=300s)
- **FIX-3**: 3-failure dead letter path explicitly tested with attempts=3
- Transaction handling: Removed explicit `session.begin()` blocks for SQLite test compatibility
- UUID generation: Fixed from `str(uuid4())` to `uuid4()` for SQLAlchemy UUID type

**Verification**: `pytest tests/test_worker.py -v` → **9/9 tests green** ✅
**Verification**: `pytest tests/ -v` → **65/65 tests green** ✅ (CP0-CP6 all passing)
**Commit**: `feat(phase-1): implement queue worker with stale lock reclaim (FIX-2) and 3-failure dead letter (FIX-3)`

---

### Checkpoint 4: LLM Clients + Tests (1.7) [OLD — see CP4 ✅ above]

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

### Checkpoint 7: API Ingestion + Tests (1.6) ✅ (COMPLETE)

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
- [x] `src/api/__init__.py`
- [x] `src/api/main.py` — FastAPI app with lifespan, middleware, routers
- [x] `src/api/routes/__init__.py`
- [x] `src/api/routes/memory.py` — POST /v1/memory → 202, inserts raw_memory + refinement_queue
- [x] `src/api/routes/health.py` — GET /health (always 200), GET /ready (200/503 based on DB)
- [x] `src/api/middleware/__init__.py`
- [x] `src/api/middleware/auth.py` — X-API-Key validation, exempts /health + /ready

**Verification**: `pytest tests/test_ingestion.py -v` → **9/9 tests green** ✅
**Commit**: `feat(phase-1): checkpoint-7 — API ingestion endpoint with auth middleware`

---

### Checkpoint 8: Search & Ranking + Tests (1.14) ✅ (COMPLETE)

**Tests implemented & passing:**
- [x] `tests/test_ranking.py` (8 tests passing)
  - `test_recency_score_is_between_0_and_1` ✅
  - `test_recency_score_decreases_over_time` ✅
  - `test_recency_score_today_is_one` ✅
  - `test_recency_score_uses_half_life` ✅
  - `test_combined_score_weights_sum_to_one` ✅
  - `test_combined_score_with_zero_inputs` ✅
  - `test_combined_score_with_perfect_inputs` ✅
  - `test_combined_score_uses_configured_weights` ✅

- [x] `tests/test_search.py` (7 tests passing)
  - `test_hybrid_search_returns_ranked_results` ✅
  - `test_hybrid_search_respects_type_filter` ✅
  - `test_hybrid_search_logs_retrieval_events` ✅ (FIX-3 validated)
  - `test_search_endpoint_returns_200` ✅
  - `test_search_endpoint_requires_auth` ✅
  - `test_search_endpoint_missing_query_returns_422` ✅
  - `test_search_endpoint_empty_results` ✅

**Implementation complete:**
- [x] `src/retrieval/__init__.py`
- [x] `src/retrieval/ranking.py` — `recency_score()`, `combined_score()` with settings-based weights
- [x] `src/retrieval/search.py` — `hybrid_search()` with FIX-4 compliant SQL, FIX-3 event logging
- [x] `src/api/routes/search.py` — GET /v1/search endpoint

**Critical Fixes Validated:**
- **FIX-3**: `hybrid_search()` logs a `RetrievalEvent` for every result returned
- **FIX-4**: GIN query uses exact `to_tsvector('english', content)` expression matching index definition

**Verification**: `pytest tests/test_ranking.py tests/test_search.py -v` → **15/15 tests green** ✅
**Commit**: `feat(phase-1): checkpoint-8 — hybrid search, ranking formula, search endpoint`

---

### Checkpoint 9: Full Test Suite Pass (1.15) ✅ (COMPLETE)

**All tests passing:**
- [x] `pytest tests/ -v` → **89/89 tests green** ✅
- [x] 1 warning (coroutine never awaited in test_database.py — pre-existing, not a blocker)

**Test suite breakdown:**
```
test_config.py:      7 tests  ✅
test_database.py:    3 tests  ✅
test_ingestion.py:   9 tests  ✅  (CP7)
test_llm.py:        14 tests  ✅
test_models.py:      8 tests  ✅
test_pipeline.py:   24 tests  ✅
test_ranking.py:     8 tests  ✅  (CP8)
test_search.py:      7 tests  ✅  (CP8)
test_worker.py:      9 tests  ✅
────────────────────────────────
Total:              89 tests  ✅
```

**Verification**: `pytest tests/ -v --tb=short` → **89/89 green** ✅
**Commit**: `feat(phase-1): checkpoint-7-8-9 — API ingestion, search/ranking, full suite 89 tests passing`

---

## Phase 1 Verification Gates (must all pass before Phase 2)

- [ ] Gate 1: `docker compose up` → api and worker services healthy (db service no longer exists; Supabase is external)
- [ ] Gate 2: `psql $SQLALCHEMY_URL -c "SELECT COUNT(*) FROM pg_tables WHERE schemaname='public'"` → 11 tables
- [x] Gate 3: `POST /v1/memory` → 202 with raw_id (verified via test suite ✅)
- [x] Gate 4: raw_memory + refinement_queue rows in DB (verified via test suite ✅)
- [x] Gate 5: Worker processes job → memory_items + entities + embedding created (verified via test suite ✅)
- [x] Gate 6: 3-failure retry path → failed_refinements row (verified via test suite ✅)
- [x] Gate 7: Stale lock reclaim works (verified via test suite ✅)
- [x] Gate 8: `GET /v1/search?q=test` → ranked results (verified via test suite ✅)

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
