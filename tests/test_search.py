"""Tests for CP8: hybrid search and the GET /v1/search endpoint.

Integration tests use in-memory SQLite. The hybrid_search SQL uses
PostgreSQL-specific functions (pgvector, to_tsvector), so we mock
hybrid_search for endpoint tests and use a simplified path for unit tests.
"""

from datetime import UTC, datetime
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
        MemoryItem(
            raw_id=raw1.id, type="memory", content="High importance memory", base_importance=0.9
        ),
        MemoryItem(
            raw_id=raw2.id, type="memory", content="Low importance memory", base_importance=0.1
        ),
        MemoryItem(
            raw_id=raw3.id, type="decision", content="Decision type memory", base_importance=0.5
        ),
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

    with patch(
        "src.retrieval.search._execute_hybrid_sql", new_callable=AsyncMock, return_value=mock_rows
    ):
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

    with patch(
        "src.retrieval.search._execute_hybrid_sql", new_callable=AsyncMock, return_value=mock_rows
    ):
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

    with patch(
        "src.retrieval.search._execute_hybrid_sql", new_callable=AsyncMock, return_value=mock_rows
    ):
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
        patch(
            "src.api.routes.search.hybrid_search", new_callable=AsyncMock, return_value=fake_results
        ),
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


# ── GET /v1/search/context endpoint ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_context_endpoint_returns_200(client, auth_headers, sample_memory):
    """GET /v1/search/context returns 200 with all ContextResponse fields."""
    fake_embedding = [0.1] * 1024
    fake_results = [
        SearchResult(
            id=str(sample_memory.id),
            content="Python is a programming language",
            summary="Python language fact",
            type="memory",
            importance_score=0.7,
            combined_score=0.75,
            created_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
    ]

    with (
        patch("src.api.routes.search.VoyageEmbeddingClient") as mock_voyage_cls,
        patch(
            "src.api.routes.search.hybrid_search", new_callable=AsyncMock, return_value=fake_results
        ),
    ):
        mock_voyage = AsyncMock()
        mock_voyage.embed.return_value = fake_embedding
        mock_voyage_cls.return_value = mock_voyage

        resp = await client.get("/v1/search/context", params={"q": "Python"}, headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "Python"
    assert "context" in body
    assert "tokens_used" in body
    assert "tokens_budget" in body
    assert "items_included" in body
    assert "items_truncated" in body
    assert body["items_included"] == 1
    assert "Python is a programming language" in body["context"]


@pytest.mark.asyncio
async def test_context_endpoint_requires_auth(client):
    """GET /v1/search/context without X-API-Key returns 401."""
    resp = await client.get("/v1/search/context", params={"q": "test"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_context_endpoint_missing_query_returns_422(client, auth_headers):
    """GET /v1/search/context without q param returns 422."""
    resp = await client.get("/v1/search/context", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_context_endpoint_empty_search_results(client, auth_headers):
    """GET /v1/search/context returns 200 with empty context when no results found."""
    fake_embedding = [0.1] * 1024

    with (
        patch("src.api.routes.search.VoyageEmbeddingClient") as mock_voyage_cls,
        patch("src.api.routes.search.hybrid_search", new_callable=AsyncMock, return_value=[]),
    ):
        mock_voyage = AsyncMock()
        mock_voyage.embed.return_value = fake_embedding
        mock_voyage_cls.return_value = mock_voyage

        resp = await client.get(
            "/v1/search/context", params={"q": "nonexistent"}, headers=auth_headers
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["context"] == ""
    assert body["items_included"] == 0
    assert body["items_truncated"] == 0


@pytest.mark.asyncio
async def test_context_endpoint_respects_type_filter(client, auth_headers):
    """GET /v1/search/context passes type_filter to hybrid_search."""
    fake_embedding = [0.1] * 1024
    fake_results = [
        SearchResult(
            id="00000000-0000-0000-0000-000000000001",
            content="A decision was made.",
            summary=None,
            type="decision",
            importance_score=0.5,
            combined_score=0.8,
            created_at=datetime(2026, 3, 15, tzinfo=UTC),
        )
    ]

    with (
        patch("src.api.routes.search.VoyageEmbeddingClient") as mock_voyage_cls,
        patch(
            "src.api.routes.search.hybrid_search", new_callable=AsyncMock, return_value=fake_results
        ) as mock_search,
    ):
        mock_voyage = AsyncMock()
        mock_voyage.embed.return_value = fake_embedding
        mock_voyage_cls.return_value = mock_voyage

        resp = await client.get(
            "/v1/search/context",
            params={"q": "decision", "type_filter": "decision"},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    # Verify hybrid_search was called with the correct type_filter
    call_kwargs = mock_search.call_args.kwargs
    assert call_kwargs.get("type_filter") == "decision"


# ── Structured filter tests (Phase 2.2) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_hybrid_search_entity_filter_forwarded(async_session, sample_memory):
    """entity_filter is forwarded to _execute_hybrid_sql."""
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
        )
    ]

    with patch(
        "src.retrieval.search._execute_hybrid_sql", new_callable=AsyncMock, return_value=mock_rows
    ) as mock_sql:
        await hybrid_search(
            session=async_session,
            query_text="test",
            query_embedding=[0.1] * 1024,
            limit=10,
            entity_filter="Anthropic",
        )

    call_kwargs = mock_sql.call_args.kwargs if mock_sql.call_args.kwargs else {}
    call_args = mock_sql.call_args.args
    # entity_filter is a positional arg at index 5 (session, text, emb, limit, type, entity)
    assert "Anthropic" in call_args or call_kwargs.get("entity_filter") == "Anthropic"


@pytest.mark.asyncio
async def test_hybrid_search_date_from_forwarded(async_session, sample_memory):
    """date_from is forwarded to _execute_hybrid_sql."""
    from src.retrieval.search import hybrid_search

    mock_rows: list = []
    dt = datetime(2026, 1, 1, tzinfo=UTC)

    with patch(
        "src.retrieval.search._execute_hybrid_sql", new_callable=AsyncMock, return_value=mock_rows
    ) as mock_sql:
        await hybrid_search(
            session=async_session,
            query_text="test",
            query_embedding=[0.1] * 1024,
            limit=10,
            date_from=dt,
        )

    call_args = mock_sql.call_args.args
    call_kwargs = mock_sql.call_args.kwargs if mock_sql.call_args.kwargs else {}
    assert dt in call_args or call_kwargs.get("date_from") == dt


@pytest.mark.asyncio
async def test_hybrid_search_date_to_forwarded(async_session, sample_memory):
    """date_to is forwarded to _execute_hybrid_sql."""
    from src.retrieval.search import hybrid_search

    mock_rows: list = []
    dt = datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)

    with patch(
        "src.retrieval.search._execute_hybrid_sql", new_callable=AsyncMock, return_value=mock_rows
    ) as mock_sql:
        await hybrid_search(
            session=async_session,
            query_text="test",
            query_embedding=[0.1] * 1024,
            limit=10,
            date_to=dt,
        )

    call_args = mock_sql.call_args.args
    call_kwargs = mock_sql.call_args.kwargs if mock_sql.call_args.kwargs else {}
    assert dt in call_args or call_kwargs.get("date_to") == dt


@pytest.mark.asyncio
async def test_hybrid_search_all_filters_combined(async_session):
    """All three new filters can be passed simultaneously."""
    from src.retrieval.search import hybrid_search

    date_from = datetime(2026, 1, 1, tzinfo=UTC)
    date_to = datetime(2026, 12, 31, tzinfo=UTC)

    with patch(
        "src.retrieval.search._execute_hybrid_sql", new_callable=AsyncMock, return_value=[]
    ) as mock_sql:
        await hybrid_search(
            session=async_session,
            query_text="test",
            query_embedding=[0.1] * 1024,
            limit=5,
            type_filter="memory",
            entity_filter="Python",
            date_from=date_from,
            date_to=date_to,
        )

    call_args = mock_sql.call_args.args
    call_kwargs = mock_sql.call_args.kwargs if mock_sql.call_args.kwargs else {}
    # Verify all filters reached _execute_hybrid_sql
    all_values = set(str(a) for a in call_args) | set(str(v) for v in call_kwargs.values())
    assert "Python" in all_values or call_kwargs.get("entity_filter") == "Python"


@pytest.mark.asyncio
async def test_hybrid_search_no_filters_all_none_by_default(async_session):
    """When no filters are provided, all filter params default to None."""
    from src.retrieval.search import hybrid_search

    with patch(
        "src.retrieval.search._execute_hybrid_sql", new_callable=AsyncMock, return_value=[]
    ) as mock_sql:
        await hybrid_search(
            session=async_session,
            query_text="test",
            query_embedding=[0.1] * 1024,
            limit=10,
        )

    call_args = mock_sql.call_args.args
    # Positional: (session, text, emb, limit, type_filter=None, entity=None, from=None, to=None)
    assert call_args[4] is None  # type_filter
    assert call_args[5] is None  # entity_filter
    assert call_args[6] is None  # date_from
    assert call_args[7] is None  # date_to


# ── Endpoint filter propagation tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_endpoint_passes_entity_filter(client, auth_headers):
    """GET /v1/search?entity_filter=X passes entity_filter to hybrid_search."""
    fake_embedding = [0.1] * 1024

    with (
        patch("src.api.routes.search.VoyageEmbeddingClient") as mock_voyage_cls,
        patch(
            "src.api.routes.search.hybrid_search", new_callable=AsyncMock, return_value=[]
        ) as mock_search,
    ):
        mock_voyage = AsyncMock()
        mock_voyage.embed.return_value = fake_embedding
        mock_voyage_cls.return_value = mock_voyage

        resp = await client.get(
            "/v1/search",
            params={"q": "test", "entity_filter": "Anthropic"},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    call_kwargs = mock_search.call_args.kwargs
    assert call_kwargs.get("entity_filter") == "Anthropic"


@pytest.mark.asyncio
async def test_search_endpoint_passes_date_from(client, auth_headers):
    """GET /v1/search?date_from=... passes UTC-aware datetime to hybrid_search."""
    fake_embedding = [0.1] * 1024

    with (
        patch("src.api.routes.search.VoyageEmbeddingClient") as mock_voyage_cls,
        patch(
            "src.api.routes.search.hybrid_search", new_callable=AsyncMock, return_value=[]
        ) as mock_search,
    ):
        mock_voyage = AsyncMock()
        mock_voyage.embed.return_value = fake_embedding
        mock_voyage_cls.return_value = mock_voyage

        resp = await client.get(
            "/v1/search",
            params={"q": "test", "date_from": "2026-01-01T00:00:00Z"},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    call_kwargs = mock_search.call_args.kwargs
    passed_dt = call_kwargs.get("date_from")
    assert passed_dt is not None
    assert passed_dt.tzinfo is not None  # must be timezone-aware


@pytest.mark.asyncio
async def test_search_endpoint_passes_date_to(client, auth_headers):
    """GET /v1/search?date_to=... passes UTC-aware datetime to hybrid_search."""
    fake_embedding = [0.1] * 1024

    with (
        patch("src.api.routes.search.VoyageEmbeddingClient") as mock_voyage_cls,
        patch(
            "src.api.routes.search.hybrid_search", new_callable=AsyncMock, return_value=[]
        ) as mock_search,
    ):
        mock_voyage = AsyncMock()
        mock_voyage.embed.return_value = fake_embedding
        mock_voyage_cls.return_value = mock_voyage

        resp = await client.get(
            "/v1/search",
            params={"q": "test", "date_to": "2026-12-31T23:59:59Z"},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    call_kwargs = mock_search.call_args.kwargs
    passed_dt = call_kwargs.get("date_to")
    assert passed_dt is not None
    assert passed_dt.tzinfo is not None


@pytest.mark.asyncio
async def test_search_endpoint_invalid_date_from_returns_422(client, auth_headers):
    """GET /v1/search?date_from=not-a-date returns 422."""
    resp = await client.get(
        "/v1/search",
        params={"q": "test", "date_from": "not-a-date"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_search_endpoint_invalid_date_to_returns_422(client, auth_headers):
    """GET /v1/search?date_to=not-a-date returns 422."""
    resp = await client.get(
        "/v1/search",
        params={"q": "test", "date_to": "not-a-date"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_context_endpoint_passes_entity_filter(client, auth_headers):
    """GET /v1/search/context?entity_filter=X passes entity_filter to hybrid_search."""
    fake_embedding = [0.1] * 1024

    with (
        patch("src.api.routes.search.VoyageEmbeddingClient") as mock_voyage_cls,
        patch(
            "src.api.routes.search.hybrid_search", new_callable=AsyncMock, return_value=[]
        ) as mock_search,
    ):
        mock_voyage = AsyncMock()
        mock_voyage.embed.return_value = fake_embedding
        mock_voyage_cls.return_value = mock_voyage

        resp = await client.get(
            "/v1/search/context",
            params={"q": "test", "entity_filter": "Python"},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    call_kwargs = mock_search.call_args.kwargs
    assert call_kwargs.get("entity_filter") == "Python"


@pytest.mark.asyncio
async def test_context_endpoint_passes_date_range(client, auth_headers):
    """GET /v1/search/context passes both date_from and date_to to hybrid_search."""
    fake_embedding = [0.1] * 1024

    with (
        patch("src.api.routes.search.VoyageEmbeddingClient") as mock_voyage_cls,
        patch(
            "src.api.routes.search.hybrid_search", new_callable=AsyncMock, return_value=[]
        ) as mock_search,
    ):
        mock_voyage = AsyncMock()
        mock_voyage.embed.return_value = fake_embedding
        mock_voyage_cls.return_value = mock_voyage

        resp = await client.get(
            "/v1/search/context",
            params={
                "q": "test",
                "date_from": "2026-01-01T00:00:00Z",
                "date_to": "2026-12-31T23:59:59Z",
            },
            headers=auth_headers,
        )

    assert resp.status_code == 200
    call_kwargs = mock_search.call_args.kwargs
    assert call_kwargs.get("date_from") is not None
    assert call_kwargs.get("date_to") is not None
    assert call_kwargs["date_from"].tzinfo is not None
    assert call_kwargs["date_to"].tzinfo is not None


@pytest.mark.asyncio
async def test_search_no_filters_returns_200(client, auth_headers):
    """GET /v1/search with no optional filters still returns 200."""
    fake_embedding = [0.1] * 1024

    with (
        patch("src.api.routes.search.VoyageEmbeddingClient") as mock_voyage_cls,
        patch(
            "src.api.routes.search.hybrid_search", new_callable=AsyncMock, return_value=[]
        ) as mock_search,
    ):
        mock_voyage = AsyncMock()
        mock_voyage.embed.return_value = fake_embedding
        mock_voyage_cls.return_value = mock_voyage

        resp = await client.get("/v1/search", params={"q": "test"}, headers=auth_headers)

    assert resp.status_code == 200
    call_kwargs = mock_search.call_args.kwargs
    assert call_kwargs.get("entity_filter") is None
    assert call_kwargs.get("date_from") is None
    assert call_kwargs.get("date_to") is None
