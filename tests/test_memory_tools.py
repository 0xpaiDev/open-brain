"""Tests for memory service filtered search and memory tool handlers."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest


def _make_search_result(
    id="abc",
    content="test content",
    type="learning",
    importance_score=0.7,
    project=None,
):
    from src.retrieval.search import SearchResult

    return SearchResult(
        id=id,
        content=content,
        summary="summary",
        type=type,
        importance_score=importance_score,
        combined_score=0.8,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        project=project,
    )


# ── search_memory_filtered service tests ─────────────────────────────────────


@pytest.mark.asyncio
async def test_search_memory_filtered_no_filters(async_session):
    from src.api.services.memory_service import search_memory_filtered

    results = [
        _make_search_result(),
        _make_search_result(id="def", content="other"),
    ]
    with patch(
        "src.api.services.memory_service.hybrid_search",
        new=AsyncMock(return_value=results),
    ):
        with patch("src.api.services.memory_service.embedding_client") as mock_embed:
            mock_embed.embed = AsyncMock(return_value=[0.1] * 1024)
            out = await search_memory_filtered(async_session, query="test")

    assert len(out) == 2


@pytest.mark.asyncio
async def test_search_memory_filtered_by_type(async_session):
    from src.api.services.memory_service import search_memory_filtered

    with patch(
        "src.api.services.memory_service.hybrid_search",
        new=AsyncMock(return_value=[]),
    ) as mock_search:
        with patch("src.api.services.memory_service.embedding_client") as mock_embed:
            mock_embed.embed = AsyncMock(return_value=[0.1] * 1024)
            await search_memory_filtered(async_session, query="test", type="learning")

    assert mock_search.call_args.kwargs["type_filter"] == "learning"


@pytest.mark.asyncio
async def test_search_memory_filtered_importance_min(async_session):
    from src.api.services.memory_service import search_memory_filtered

    results = [
        _make_search_result(id="high", importance_score=0.8),
        _make_search_result(id="low", importance_score=0.3),
    ]
    with patch(
        "src.api.services.memory_service.hybrid_search",
        new=AsyncMock(return_value=results),
    ):
        with patch("src.api.services.memory_service.embedding_client") as mock_embed:
            mock_embed.embed = AsyncMock(return_value=[0.1] * 1024)
            out = await search_memory_filtered(
                async_session, query="test", importance_min=0.5
            )

    assert len(out) == 1
    assert out[0].id == "high"


# ── Memory tool handler tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_search_memory_filtered(async_session):
    from src.api.services.memory_tools import handle_search_memory_filtered

    results = [_make_search_result(id="abc", content="I learned about async")]
    with patch(
        "src.api.services.memory_tools.search_memory_filtered",
        new=AsyncMock(return_value=results),
    ):
        out = await handle_search_memory_filtered(
            "search_memory_filtered",
            {"query": "async patterns"},
            async_session,
            uuid.UUID(int=0),
        )

    data = json.loads(out)
    assert len(data) == 1
    assert data[0]["id"] == "abc"


@pytest.mark.asyncio
async def test_handle_expand_memory(async_session):
    from src.api.services.memory_service import ExpandResult, NeighborEntry
    from src.api.services.memory_tools import handle_expand_memory

    expand_result = ExpandResult(
        memory_id="abc-123",
        content="Full content here",
        raw_text="Original input",
        neighbors=[],
        metadata={
            "source": "api",
            "project": None,
            "tags": [],
            "importance_score": 0.7,
            "created_at": "2026-05-01T00:00:00",
        },
    )
    with patch(
        "src.api.services.memory_tools.expand_memory",
        new=AsyncMock(return_value=expand_result),
    ):
        out = await handle_expand_memory(
            "expand_memory",
            {"memory_id": "abc-123"},
            async_session,
            uuid.UUID(int=0),
        )

    data = json.loads(out)
    assert data["memory_id"] == "abc-123"
    assert data["content"] == "Full content here"
