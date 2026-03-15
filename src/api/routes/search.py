"""Search endpoint.

GET /v1/search — hybrid search over memory_items.

Embeds the query via Voyage AI, runs hybrid_search (vector + FTS + ranking),
logs retrieval events (FIX-3), and returns ranked results.
"""

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.llm.client import VoyageEmbeddingClient
from src.retrieval.context_builder import ContextResult, build_context
from src.retrieval.search import SearchResult, hybrid_search

logger = structlog.get_logger(__name__)

router = APIRouter()


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """Attach UTC timezone to naive datetimes; pass through None and aware datetimes."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class SearchResultItem(BaseModel):
    """Single item in the search response."""

    id: str
    content: str
    summary: str | None
    type: str
    importance_score: float
    combined_score: float


class SearchResponse(BaseModel):
    """Response body for GET /v1/search."""

    results: list[SearchResultItem]
    query: str


class ContextResponse(BaseModel):
    """Response body for GET /v1/search/context."""

    context: str
    tokens_used: int
    tokens_budget: int
    items_included: int
    items_truncated: int
    query: str


@router.get("/v1/search", response_model=SearchResponse)
async def search_memories(
    q: str = Query(..., description="Search query text"),
    limit: int = Query(default=10, ge=1, le=100, description="Maximum results to return"),
    type_filter: str | None = Query(
        default=None, description="Filter by type: memory, decision, task"
    ),
    entity_filter: str | None = Query(
        default=None, description="Filter by entity name or alias (case-insensitive)"
    ),
    date_from: datetime | None = Query(
        default=None, description="Earliest created_at (ISO 8601, e.g. 2026-01-01T00:00:00Z)"
    ),
    date_to: datetime | None = Query(
        default=None, description="Latest created_at (ISO 8601, e.g. 2026-12-31T23:59:59Z)"
    ),
    session: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """Hybrid search over memory_items using vector + full-text ranking.

    Embeds the query, runs hybrid search (pgvector + GIN FTS), applies
    combined scoring, logs retrieval events, and returns ranked results.

    Raises:
        422: missing required 'q' parameter, or unparseable date_from/date_to
        401: missing or invalid X-API-Key (handled by middleware)
    """
    from src.core import config as _config

    if _config.settings is None:
        _config.settings = _config.Settings()
    _settings = _config.settings

    voyage = VoyageEmbeddingClient(
        api_key=_settings.voyage_api_key.get_secret_value() if _settings.voyage_api_key else "",
        model=_settings.voyage_model,
    )
    query_embedding = await voyage.embed(q)

    results: list[SearchResult] = await hybrid_search(
        session=session,
        query_text=q,
        query_embedding=query_embedding,
        limit=limit,
        type_filter=type_filter,
        entity_filter=entity_filter,
        date_from=_ensure_utc(date_from),
        date_to=_ensure_utc(date_to),
    )

    await session.commit()

    items = [
        SearchResultItem(
            id=r.id,
            content=r.content,
            summary=r.summary,
            type=r.type,
            importance_score=r.importance_score,
            combined_score=r.combined_score,
        )
        for r in results
    ]

    logger.info(
        "search_request",
        query=q,
        result_count=len(items),
        type_filter=type_filter,
        entity_filter=entity_filter,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
    )
    return SearchResponse(results=items, query=q)


@router.get("/v1/search/context", response_model=ContextResponse)
async def search_context(
    q: str = Query(..., description="Search query text"),
    limit: int = Query(
        default=10, ge=1, le=100, description="Maximum results to search before building context"
    ),
    type_filter: str | None = Query(
        default=None, description="Filter by type: memory, decision, task"
    ),
    entity_filter: str | None = Query(
        default=None, description="Filter by entity name or alias (case-insensitive)"
    ),
    date_from: datetime | None = Query(
        default=None, description="Earliest created_at (ISO 8601, e.g. 2026-01-01T00:00:00Z)"
    ),
    date_to: datetime | None = Query(
        default=None, description="Latest created_at (ISO 8601, e.g. 2026-12-31T23:59:59Z)"
    ),
    session: AsyncSession = Depends(get_db),
) -> ContextResponse:
    """Build an LLM-ready context string from hybrid search results.

    Embeds the query, runs hybrid search (pgvector + GIN FTS), formats the
    ranked results into a token-budgeted context string suitable for injection
    into an LLM prompt.

    Raises:
        422: missing required 'q' parameter, or unparseable date_from/date_to
        401: missing or invalid X-API-Key (handled by middleware)
    """
    from src.core import config as _config

    if _config.settings is None:
        _config.settings = _config.Settings()
    _settings = _config.settings

    voyage = VoyageEmbeddingClient(
        api_key=_settings.voyage_api_key.get_secret_value() if _settings.voyage_api_key else "",
        model=_settings.voyage_model,
    )
    query_embedding = await voyage.embed(q)

    results: list[SearchResult] = await hybrid_search(
        session=session,
        query_text=q,
        query_embedding=query_embedding,
        limit=limit,
        type_filter=type_filter,
        entity_filter=entity_filter,
        date_from=_ensure_utc(date_from),
        date_to=_ensure_utc(date_to),
    )

    await session.commit()

    ctx: ContextResult = build_context(results)

    logger.info(
        "search_context_request",
        query=q,
        items_included=ctx.items_included,
        items_truncated=ctx.items_truncated,
        tokens_used=ctx.tokens_used,
        tokens_budget=ctx.tokens_budget,
        type_filter=type_filter,
        entity_filter=entity_filter,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
    )
    return ContextResponse(
        context=ctx.context,
        tokens_used=ctx.tokens_used,
        tokens_budget=ctx.tokens_budget,
        items_included=ctx.items_included,
        items_truncated=ctx.items_truncated,
        query=q,
    )
