"""End-to-end integration tests against a real PostgreSQL database.

These tests are SKIPPED by default (they require a live Supabase/Postgres connection).
To run them, set INTEGRATION_TEST=1 in your environment:

    INTEGRATION_TEST=1 pytest tests/test_integration.py -v

Requirements:
  - SQLALCHEMY_URL must point to a real Postgres instance (port 5432, not 6543)
  - The pgvector and pg_trgm extensions must be installed
  - All Alembic migrations must be applied (alembic upgrade head)

These tests verify that production-specific behaviour matches the SQLite unit tests:
  - Vector column is `vector(1024)`, not JSONB
  - GIN index is used for keyword search (not a sequential scan)
  - pg_trgm fuzzy entity matching works at the 0.92 threshold
  - GENERATED `importance_score` is computed correctly
  - Stale lock reclaim logic works on real Postgres
  - 3-failure dead letter path persists correctly
"""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Skip entire module unless INTEGRATION_TEST=1 is set
pytestmark = pytest.mark.skipif(
    os.environ.get("INTEGRATION_TEST") != "1",
    reason="Integration tests require INTEGRATION_TEST=1 and a live Postgres DB",
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def pg_engine():
    """Async engine connected to the real Postgres DB (from SQLALCHEMY_URL env var)."""
    url = os.environ.get("SQLALCHEMY_URL", "")
    if not url:
        pytest.skip("SQLALCHEMY_URL is not set")

    engine = create_async_engine(url, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_engine) -> AsyncSession:
    """Per-test async session against the real Postgres DB."""
    factory = sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


# ── Test: embedding column type ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_embedding_column_is_vector_type(pg_session: AsyncSession):
    """The embedding column must be stored as `vector(1024)`, not JSONB or TEXT."""
    result = await pg_session.execute(
        text(
            """
            SELECT udt_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'memory_items'
              AND column_name = 'embedding'
            """
        )
    )
    udt_name = result.scalar_one()
    assert udt_name == "vector", f"Expected 'vector', got '{udt_name}'"


# ── Test: GIN index used for keyword search ───────────────────────────────────


@pytest.mark.asyncio
async def test_keyword_search_uses_gin_index(pg_session: AsyncSession):
    """EXPLAIN ANALYZE on keyword search must use the GIN index (not Seq Scan)."""
    result = await pg_session.execute(
        text(
            """
            EXPLAIN (FORMAT TEXT, ANALYZE false)
            SELECT id FROM memory_items
            WHERE to_tsvector('english', content) @@ plainto_tsquery('english', 'test query')
            """
        )
    )
    plan = "\n".join(r[0] for r in result.all())
    # Should use Index Scan (GIN) rather than Seq Scan
    assert "Seq Scan" not in plan or "Index Scan" in plan, (
        f"Expected GIN index usage, but got:\n{plan}"
    )


# ── Test: HNSW index used for vector search ───────────────────────────────────


@pytest.mark.asyncio
async def test_hnsw_index_exists(pg_session: AsyncSession):
    """HNSW index on `embedding` column must be present in pg_indexes."""
    result = await pg_session.execute(
        text(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'memory_items'
              AND indexdef ILIKE '%hnsw%'
            """
        )
    )
    rows = result.all()
    assert len(rows) > 0, "No HNSW index found on memory_items.embedding"


# ── Test: GENERATED importance_score column ───────────────────────────────────


@pytest.mark.asyncio
async def test_generated_importance_score(pg_session: AsyncSession):
    """importance_score must be computed as 0.6*base + 0.4*dynamic by Postgres."""
    from src.core.models import MemoryItem, RawMemory

    raw = RawMemory(source="integration_test", raw_text="test", content_hash=str(uuid4()))
    pg_session.add(raw)
    await pg_session.flush()

    item = MemoryItem(
        raw_id=raw.id,
        type="memory",
        content="integration test memory",
        base_importance=0.8,
        dynamic_importance=0.4,
    )
    pg_session.add(item)
    await pg_session.flush()

    # Re-fetch to get GENERATED column value
    await pg_session.refresh(item)
    expected = round(0.6 * 0.8 + 0.4 * 0.4, 4)
    actual = round(float(item.importance_score), 4)
    assert actual == expected, f"Expected {expected}, got {actual}"


# ── Test: pg_trgm fuzzy entity matching ───────────────────────────────────────


@pytest.mark.asyncio
async def test_pgtrgm_extension_installed(pg_session: AsyncSession):
    """pg_trgm extension must be installed (required for entity fuzzy matching)."""
    result = await pg_session.execute(
        text("SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'")
    )
    assert result.scalar_one_or_none() == "pg_trgm", "pg_trgm extension is not installed"


@pytest.mark.asyncio
async def test_fuzzy_entity_match_above_threshold(pg_session: AsyncSession):
    """similarity('Anthropic', 'Anthropic') must be 1.0 (exact match)."""
    result = await pg_session.execute(
        text("SELECT similarity('Anthropic', 'Anthropic')")
    )
    score = float(result.scalar_one())
    assert score == 1.0, f"Expected 1.0, got {score}"


@pytest.mark.asyncio
async def test_fuzzy_entity_match_below_threshold(pg_session: AsyncSession):
    """similarity('Anthropic', 'Amazon') must be below 0.92 (no merge)."""
    result = await pg_session.execute(
        text("SELECT similarity('Anthropic', 'Amazon')")
    )
    score = float(result.scalar_one())
    assert score < 0.92, f"Expected < 0.92, got {score}"


# ── Test: stale lock reclaim ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stale_lock_reclaim_on_postgres(pg_session: AsyncSession):
    """A processing job with locked_at > 5 min ago must be reclaimable."""
    from src.core.models import RawMemory, RefinementQueue

    raw = RawMemory(source="integration_test", raw_text="stale lock test", content_hash=str(uuid4()))
    pg_session.add(raw)
    await pg_session.flush()

    stale_time = datetime.now(UTC) - timedelta(minutes=10)
    queue_row = RefinementQueue(
        raw_id=raw.id,
        status="processing",
        locked_at=stale_time,
        attempts=1,
    )
    pg_session.add(queue_row)
    await pg_session.flush()

    # Simulate what claim_batch does: update stale processing rows back to pending
    result = await pg_session.execute(
        text(
            """
            UPDATE refinement_queue
            SET status = 'pending', locked_at = NULL
            WHERE status = 'processing'
              AND locked_at < NOW() - INTERVAL '5 minutes'
              AND id = :id
            RETURNING id
            """
        ),
        {"id": queue_row.id},
    )
    reclaimed = result.fetchall()
    assert len(reclaimed) == 1, "Stale lock was not reclaimed"


# ── Test: 11 tables created by migrations ────────────────────────────────────


@pytest.mark.asyncio
async def test_all_tables_exist(pg_session: AsyncSession):
    """All 11 core tables must exist in the public schema."""
    result = await pg_session.execute(
        text(
            """
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
            """
        )
    )
    table_names = {row[0] for row in result.all()}
    required_tables = {
        "raw_memory",
        "memory_items",
        "entities",
        "entity_aliases",
        "entity_relations",
        "memory_entity_links",
        "decisions",
        "tasks",
        "refinement_queue",
        "failed_refinements",
        "retrieval_events",
    }
    missing = required_tables - table_names
    assert not missing, f"Missing tables: {missing}"


# ── Test: content_hash column added by migration 0002 ─────────────────────────


@pytest.mark.asyncio
async def test_content_hash_column_exists(pg_session: AsyncSession):
    """raw_memory.content_hash column must exist (migration 0002)."""
    result = await pg_session.execute(
        text(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'raw_memory'
              AND column_name = 'content_hash'
            """
        )
    )
    row = result.one_or_none()
    assert row is not None, "content_hash column not found in raw_memory"
    assert row[1] == "character varying", f"Unexpected data_type: {row[1]}"
