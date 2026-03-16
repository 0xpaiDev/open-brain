# Technical Debt Register — Open Brain

**Date**: 2026-03-16
**Status**: Post Phase 5 audit (410 tests passing, all phases complete)
**Auditor**: Automated codebase scan + architectural review

---

## Summary

| Priority | Count | Action Required |
|----------|-------|-----------------|
| Critical | 0 | — |
| High | 0 | — |
| Medium | 4 | Address before adding new routes or scaling |
| Low | 9 | Address opportunistically or when touching related code |

The codebase is in strong shape. No security issues, no broken async patterns, no data integrity risks. The debt is structural: four duplicated helper patterns and a few missing guardrails. All medium items can be resolved in a single refactor session without touching schema or API contracts.

---

## Medium Priority

### M1 — `_parse_uuid()` duplicated across 4 route modules

**Files**:
- `src/api/routes/entities.py:82–87`
- `src/api/routes/tasks.py:74–79`
- `src/api/routes/decisions.py:51–56`
- `src/api/routes/queue.py:67–72`
- `src/api/routes/memory.py:111–113` (inline variant)

**Impact**: Every new route that takes a UUID path parameter requires copy-pasting the same 5-line validation block. One divergent copy (e.g., different error message or missing `ValueError` catch) will create inconsistent 422 behavior across endpoints.

**Fix path**: Extract to `src/api/deps.py` as a shared FastAPI dependency or a standalone `parse_uuid(value: str, field_name: str) -> UUID` utility. Import from all route modules.

```python
# src/api/deps.py
from uuid import UUID

def parse_uuid(value: str, field_name: str = "id") -> UUID:
    try:
        return UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail=f"Invalid UUID for {field_name}: {value!r}")
```

---

### M2 — `_get_settings()` lazy-init helper duplicated 8+ times

**Files**:
- `src/retrieval/ranking.py:11–23`
- `src/retrieval/context_builder.py:32–44`
- `src/jobs/importance.py:41–46`
- `src/jobs/synthesis.py:47–52`
- `src/pipeline/worker.py:88–92`
- `src/api/middleware/auth.py:15–26`
- `src/api/routes/search.py:92–96`
- `src/api/middleware/rate_limit.py:30–54`
- `src/api/routes/queue.py:89–93`

**Impact**: The pattern is intentional (see Not-Debt section below), but nine copies are a drift risk. If the singleton initialization logic needs to change — e.g., to add a fallback env file path or a validation override — it must be updated in nine places. One missed update breaks the test isolation guarantee.

**Fix path**: Extract to `src/core/settings_utils.py`:

```python
# src/core/settings_utils.py
from src.core import config

def get_settings() -> "config.Settings":
    if config.settings is None:
        config.settings = config.Settings()
    return config.settings
```

Replace all nine `_get_settings()` implementations with `from src.core.settings_utils import get_settings`.

> **Note**: This refactor must preserve the lazy-init behavior. Do not replace with a module-level `from src.core.config import settings` import — that breaks test isolation. See Not-Debt section M2 for why.

---

### M3 — `merge_entities()` is 162 lines doing 6 distinct operations

**File**: `src/api/routes/entities.py:145–306`

**Impact**: The merge operation is correct but untestable at the unit level. All six steps (validate, move aliases, move memory links, move relations forward, move relations reverse, alias the source name) run inside a single function. A bug in step 4 requires running the full merge to reproduce. Atomic rollback makes this acceptable for correctness but not for maintainability.

**Fix path**: Extract each move operation into a private async helper that takes `session, source_uuid, target_uuid` and returns nothing (raises on failure):

```python
async def _move_aliases(session, source_uuid, target_uuid): ...
async def _move_memory_links(session, source_uuid, target_uuid): ...
async def _move_entity_relations(session, source_uuid, target_uuid): ...
async def _alias_source_name(session, source_entity_name, target_uuid): ...
```

`merge_entities()` becomes a coordinator: validate → call helpers → expunge → delete source → commit.

---

### M4 — `VoyageEmbeddingClient` instantiated per request in search routes

**File**: `src/api/routes/search.py:98–101` and `179–182`

**Impact**: A new `VoyageEmbeddingClient` object is created on every call to `GET /v1/search` and `GET /v1/search/context`. The object is lightweight (no connection pool), so the performance cost is negligible at current scale. However, if the Voyage client ever gains connection pooling or requires initialization overhead, this will silently become a bottleneck.

**Current code**:
```python
settings = _get_settings()
voyage_client = VoyageEmbeddingClient(
    api_key=settings.voyage_api_key.get_secret_value(),
    model=settings.embedding_model,
)
```

**Fix path**: Use the module-level `embedding_client` singleton already defined in `src/llm/client.py`. Add a null-guard at startup (the existing `lifespan` in `main.py` is the right place):

```python
from src.llm.client import embedding_client
# In route handler:
if embedding_client is None:
    raise HTTPException(status_code=503, detail="Embedding service not configured")
```

---

## Low Priority

### L1 — Overly broad `except Exception` in entity resolver

**File**: `src/pipeline/entity_resolver.py:95–102`

**Issue**: The broad catch is intentional (pg_trgm may not be installed in SQLite test environments), but it will also swallow legitimate runtime errors like connection timeouts or permission errors.

**Fix**: Narrow to `except (ProgrammingError, OperationalError) as e` from SQLAlchemy. These are the specific exceptions raised when a function (`similarity()`) doesn't exist or a query fails structurally.

---

### L2 — Missing response shape validation in LLM clients

**Files**:
- `src/llm/client.py:89` — `response.content[0].text` (IndexError if empty)
- `src/llm/client.py:155` — `result.embeddings[0]` (IndexError if empty)

**Issue**: The Anthropic and Voyage SDKs guarantee non-empty responses in their contracts, but there is no explicit guard. A future SDK version or rate-limit response could break silently with an `IndexError` instead of a meaningful `ExtractionFailed` / `EmbeddingFailed`.

**Fix**: Add explicit length checks before indexing, raising the appropriate named exception:

```python
if not response.content:
    raise ExtractionFailed("Anthropic returned empty content array")
```

---

### L3 — Hardcoded `LIMIT 100` in search CTEs

**File**: `src/retrieval/search.py:125, 135, 160`

**Issue**: The vector and keyword CTEs each fetch a maximum of 100 candidates before the hybrid ranking join. If a user requests `limit=50` and the top 50 by combined score all come from a narrow semantic cluster, candidates outside the top 100 by individual signal are never considered.

**Impact**: Currently sufficient. Becomes a problem if the corpus grows large (>50k memories) or if recency/importance weights heavily favor items outside the top 100 by raw vector/keyword score.

**Fix**: Make the CTE limit a multiplier of the requested `limit`: `LIMIT :candidate_limit` with `candidate_limit = limit * 4` (capped at a reasonable ceiling like 500).

---

### L4 — Comment-style type hint in worker.py

**File**: `src/pipeline/worker.py:312`

**Issue**: `extraction,  # ExtractionResult` uses a comment instead of an actual type annotation. mypy won't catch a type mismatch here.

**Fix**: Change to `extraction: ExtractionResult` in the function signature.

---

### L5 — Missing worker edge case tests

**File**: `tests/test_worker.py`

**Missing scenarios**:
- `get_db()` raises during `claim_batch()` — worker should log and sleep, not crash
- `store_memory_item()` raises after successful extraction — job should retry, not silently disappear
- Stale lock reclaim when `locked_at` is exactly at the TTL boundary (race condition)

---

### L6 — Undocumented deduplication logic in search

**File**: `src/retrieval/search.py:245–258`

**Issue**: The content-hash deduplication step (sort → deduplicate → limit) is correct but has no comment explaining why deduplication happens after ranking rather than before. A future contributor could reasonably move it before ranking for "efficiency" and inadvertently change result ordering.

**Fix**: Add a comment block:
```python
# Deduplicate after ranking, not before. The same content can appear from both
# the vector CTE and the keyword CTE (FULL OUTER JOIN). Deduplicating before
# ranking would require ranking twice; deduplicating after preserves the
# highest combined_score for duplicate content entries.
```

---

### L7 — Extraction failure logs raw JSON data

**File**: `src/pipeline/extractor.py:144`

**Issue**: On schema validation failure, `"json_data": json_data` is included in the structlog event. This may contain user-provided text (wrapped in `<user_input>` tags, which mitigates injection risk) but raw content could be large or sensitive.

**Fix**: Log `"json_keys": list(json_data.keys())` instead of the full payload, preserving debuggability without logging content.

---

### L8 — Synthesis model still set to Haiku

**File**: `src/core/config.py:27`, `src/jobs/synthesis.py`

**Issue**: `synthesis_model` defaults to `claude-haiku-4-5-20251001`. Weekly synthesis reports need nuanced reasoning — Haiku is a cost shortcut taken during development.

**Fix**: Change default to `claude-opus-4-6` or document in `.env.example` that production deployments must set `SYNTHESIS_MODEL=claude-opus-4-6`. This is a configuration change, not a code change.

---

### L9 — Missing entity merge edge case tests

**File**: `tests/test_entities.py`

**Missing scenarios**:
- Merge when source and target share an alias (unique constraint conflict)
- Merge of an entity with zero aliases and zero memory links (empty-set edge case)
- Merging into self (source_id == target_id should return 400)

---

## Not-Debt: Intentional Patterns

The following patterns may look like debt but are intentional solutions to documented problems. Do not "fix" them without reading the linked rationale.

| Pattern | File(s) | Why It's Intentional |
|---------|---------|----------------------|
| `_get_settings()` lazy-init | 9 files | `config.settings` is `None` at module load when no `.env` exists (CI/tests). A module-level import captures `None` permanently. The lazy helper re-creates `Settings()` on first call, by which point test env vars are set. See CLAUDE.md "Settings Singleton is None in Full Test Suite". |
| No `register_vector(conn)` | `src/core/database.py` | `pgvector.sqlalchemy.Vector.process_bind_param` returns a text string. The asyncpg `register_vector` codec expects `list[float]` — calling it causes `TypeError`. PostgreSQL casts the text string to `vector` natively without the codec. See CLAUDE.md "pgvector asyncpg Codec Conflicts". |
| `await session.flush()` instead of `session.begin()` in worker | `src/pipeline/worker.py` | Test fixtures create `async_session` with an active outer transaction. Nested `session.begin()` conflicts with the outer transaction. `flush()` persists changes within the outer transaction; rollback on test teardown remains clean. See CLAUDE.md "Transaction Boundaries in Async Tests". |
| `session.expunge(entity)` before Core SQL in merge | `src/api/routes/entities.py` | After raw SQL `UPDATE` operations, `session.delete(entity)` causes SQLAlchemy's unit-of-work processor to find stale FK references in the identity map and attempt to blank them out — failing on composite PK columns. `expunge()` removes the entity from ORM tracking entirely. See CLAUDE.md "ORM Identity Map Conflict". |
| `JSONB().with_variant(JSON(), "sqlite")` on all JSON columns | `src/core/models.py` | Tests run on SQLite (no JSONB support). Production uses PostgreSQL. The variant ensures `CREATE TABLE` succeeds in both dialects. The production DDL (via Alembic) uses the real `JSONB` type. See CLAUDE.md "JSONB Incompatibility with SQLite". |
| `Vector(1024).with_variant(JSON(), "sqlite")` on embedding | `src/core/models.py` | Same as above — pgvector's `Vector` type has no SQLite driver. The ORM type uses the variant for test compatibility; the actual Alembic DDL creates the column as `vector(1024)` in production. |
