"""Tests for CP8: hybrid search and the GET /v1/search endpoint.

Integration tests use in-memory SQLite. The hybrid_search SQL uses
PostgreSQL-specific functions (pgvector, to_tsvector), so we mock
hybrid_search for endpoint tests and use a simplified path for unit tests.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.core.models import MemoryItem, RawMemory, RetrievalEvent
from src.retrieval.search import SearchResult


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(async_session, monkeypatch):
    """Test client with DB overridden to use in-memory SQLite session."""
    monkeypatch.setenv("SQLALCHEMY_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("API_KEY", "test-secret-key")

    from src.api.main import app
    from src.core.database import get_db

    async def override_get_db():
        yield async_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers() -> dict:
    return {"X-API-Key": "test-secret-key"}


@pytest_asyncio.fixture
async def sample_memory(async_session) -> MemoryItem:
    """Insert a raw_memory + memory_item for search tests."""
    raw = RawMemory(source="api", raw_text="Python is a programming language")
    async_session.add(raw)
    await async_session.flush()

    item = MemoryItem(
        raw_id=raw.id,
        type="memory",
        content="Python is a programming language",
        summary="Python language fact",
        base_importance=0.7,
        dynamic_importance=0.3,
    )
    async_session.add(item)
    await async_session.flush()
    await async_session.commit()
    return item


@pytest_asyncio.fixture
async def multiple_memories(async_session) -> list[MemoryItem]:
    """Insert multiple memory items with varying importance for ranking tests."""
    raw1 = RawMemory(source="api", raw_text="High importance memory")
    raw2 = RawMemory(source="api", raw_text="Low importance memory")
    raw3 = RawMemory(source="api", raw_text="Decision type memory")
    async_session.add_all([raw1, raw2, raw3])
    await async_session.flush()

    items = [
        MemoryItem(raw_id=raw1.id, type="memory", content="High importance memory", base_importance=0.9),
        MemoryItem(raw_id=raw2.id, type="memory", content="Low importance memory", base_importance=0.1),
        MemoryItem(raw_id=raw3.id, type="decision", content="Decision type memory", base_importance=0.5),
    ]
    async_session.add_all(items)
    await async_session.flush()
    await async_session.commit()
    return items


# ── hybrid_search unit tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hybrid_search_returns_ranked_results(async_session, multiple_memories):
    """hybrid_search returns SearchResult objects sorted by combined_score desc.

    Since SQLite lacks pgvector/FTS, we mock the SQL execution and verify
    the function correctly applies ranking and returns sorted results.
    """
    from src.retrieval.search import hybrid_search

    item_high = multiple_memories[0]
    item_low = multiple_memories[1]

    # Mock raw results: high importance item has higher scores
    mock_rows = [
        MagicMock(
            id=str(item_high.id),
            content=item_high.content,
            summary=item_high.summary,
            type=item_high.type,
            importance_score=0.9,
            created_at=item_high.created_at,
            vector_score=0.9,
            keyword_score=0.8,
        ),
        MagicMock(
            id=str(item_low.id),
            content=item_low.content,
            summary=item_low.summary,
            type=item_low.type,
            importance_score=0.1,
            created_at=item_low.created_at,
            vector_score=0.2,
            keyword_score=0.1,
        ),
    ]

    with patch("src.retrieval.search._execute_hybrid_sql", new_callable=AsyncMock, return_value=mock_rows):
        results = await hybrid_search(
            session=async_session,
            query_text="test",
            query_embedding=[0.1] * 1024,
            limit=10,
        )

    assert len(results) == 2
    assert isinstance(results[0], SearchResult)
    # Higher combined_score should come first
    assert results[0].combined_score > results[1].combined_score
    assert results[0].id == str(item_high.id)


@pytest.mark.asyncio
async def test_hybrid_search_respects_type_filter(async_session, multiple_memories):
    """hybrid_search with type_filter only returns items of that type."""
    from src.retrieval.search import hybrid_search

    item_decision = multiple_memories[2]

    mock_rows = [
        MagicMock(
            id=str(item_decision.id),
            content=item_decision.content,
            summary=item_decision.summary,
            type="decision",
            importance_score=0.5,
            created_at=item_decision.created_at,
            vector_score=0.5,
            keyword_score=0.5,
        ),
    ]

    with patch("src.retrieval.search._execute_hybrid_sql", new_callable=AsyncMock, return_value=mock_rows):
        results = await hybrid_search(
            session=async_session,
            query_text="test",
            query_embedding=[0.1] * 1024,
            limit=10,
            type_filter="decision",
        )

    assert all(r.type == "decision" for r in results)


@pytest.mark.asyncio
async def test_hybrid_search_logs_retrieval_events(async_session, sample_memory):
    """hybrid_search logs a RetrievalEvent for each result returned (FIX-3)."""
    from src.retrieval.search import hybrid_search

    mock_rows = [
        MagicMock(
            id=str(sample_memory.id),
            content=sample_memory.content,
            summary=sample_memory.summary,
            type=sample_memory.type,
            importance_score=0.7,
            created_at=sample_memory.created_at,
            vector_score=0.8,
            keyword_score=0.6,
        ),
    ]

    with patch("src.retrieval.search._execute_hybrid_sql", new_callable=AsyncMock, return_value=mock_rows):
        results = await hybrid_search(
            session=async_session,
            query_text="Python",
            query_embedding=[0.1] * 1024,
            limit=10,
        )

    assert len(results) == 1

    # Verify retrieval_events row was inserted (FIX-3 validation)
    await async_session.flush()
    event_result = await async_session.execute(
        select(RetrievalEvent).where(RetrievalEvent.memory_id == sample_memory.id)
    )
    events = event_result.scalars().all()
    assert len(events) == 1


# ── GET /v1/search endpoint ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_endpoint_returns_200(client, auth_headers, sample_memory):
    """GET /v1/search?q=... returns 200 with results list."""
    fake_embedding = [0.1] * 1024
    fake_results = [
        SearchResult(
            id=str(sample_memory.id),
            content="Python is a programming language",
            summary="Python language fact",
            type="memory",
            importance_score=0.7,
            combined_score=0.75,
            created_at=sample_memory.created_at,
        )
    ]

    with (
        patch("src.api.routes.search.VoyageEmbeddingClient") as mock_voyage_cls,
        patch("src.api.routes.search.hybrid_search", new_callable=AsyncMock, return_value=fake_results),
    ):
        mock_voyage = AsyncMock()
        mock_voyage.embed.return_value = fake_embedding
        mock_voyage_cls.return_value = mock_voyage

        resp = await client.get("/v1/search", params={"q": "Python"}, headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
    assert body["query"] == "Python"
    assert len(body["results"]) == 1
    assert body["results"][0]["content"] == "Python is a programming language"


@pytest.mark.asyncio
async def test_search_endpoint_requires_auth(client):
    """GET /v1/search without X-API-Key returns 401."""
    resp = await client.get("/v1/search", params={"q": "test"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_search_endpoint_missing_query_returns_422(client, auth_headers):
    """GET /v1/search without q param returns 422."""
    resp = await client.get("/v1/search", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_search_endpoint_empty_results(client, auth_headers):
    """GET /v1/search returns 200 with empty list when no results found."""
    fake_embedding = [0.1] * 1024

    with (
        patch("src.api.routes.search.VoyageEmbeddingClient") as mock_voyage_cls,
        patch("src.api.routes.search.hybrid_search", new_callable=AsyncMock, return_value=[]),
    ):
        mock_voyage = AsyncMock()
        mock_voyage.embed.return_value = fake_embedding
        mock_voyage_cls.return_value = mock_voyage

        resp = await client.get("/v1/search", params={"q": "nonexistent"}, headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["results"] == []
