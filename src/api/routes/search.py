"""Search endpoint.

GET /v1/search — hybrid search over memory_items.

Embeds the query via Voyage AI, runs hybrid_search (vector + FTS + ranking),
logs retrieval events (FIX-3), and returns ranked results.
"""

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.llm.client import VoyageEmbeddingClient
from src.retrieval.search import SearchResult, hybrid_search

logger = structlog.get_logger(__name__)

router = APIRouter()


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


@router.get("/v1/search", response_model=SearchResponse)
async def search_memories(
    q: str = Query(..., description="Search query text"),
    limit: int = Query(default=10, ge=1, le=100, description="Maximum results to return"),
    type_filter: str | None = Query(default=None, description="Filter by type: memory, decision, task"),
    session: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """Hybrid search over memory_items using vector + full-text ranking.

    Embeds the query, runs hybrid search (pgvector + GIN FTS), applies
    combined scoring, logs retrieval events, and returns ranked results.

    Raises:
        422: missing required 'q' parameter
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

    logger.info("search_request", query=q, result_count=len(items), type_filter=type_filter)
    return SearchResponse(results=items, query=q)
