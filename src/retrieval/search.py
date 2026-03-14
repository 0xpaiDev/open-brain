"""Hybrid search: vector similarity + full-text search + ranking.

The main entry point is hybrid_search(). It:
1. Delegates to _execute_hybrid_sql() for the DB query (mockable in tests)
2. Computes combined_score for each result using ranking.py
3. Logs a RetrievalEvent for every result returned (FIX-3)
4. Returns results sorted by combined_score descending

FIX-4: The GIN full-text query uses to_tsvector('english', content) which
must match the index definition in alembic/versions/0001_initial_schema.py
exactly. Any deviation causes a full table scan.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import RetrievalEvent
from src.retrieval.ranking import combined_score, recency_score

logger = structlog.get_logger(__name__)


@dataclass
class SearchResult:
    """A single ranked search result."""

    id: str
    content: str
    summary: str | None
    type: str
    importance_score: float
    combined_score: float
    created_at: datetime


async def _execute_hybrid_sql(
    session: AsyncSession,
    query_text: str,
    query_embedding: list[float],
    limit: int,
    type_filter: str | None,
) -> list:
    """Execute the hybrid search SQL and return raw rows.

    Separated from hybrid_search() to allow mocking in tests.
    In production (PostgreSQL), uses pgvector cosine distance + GIN FTS.

    SQL structure:
        WITH vector_results AS (
            SELECT id, 1 - (embedding <=> :embedding) AS vector_score
            FROM memory_items
            ORDER BY embedding <=> :embedding
            LIMIT 100
        ),
        keyword_results AS (
            SELECT id, ts_rank(to_tsvector('english', content),
                               plainto_tsquery('english', :q)) AS keyword_score
            FROM memory_items
            WHERE to_tsvector('english', content) @@ plainto_tsquery('english', :q)
            LIMIT 100
        )
        SELECT m.id, m.content, m.summary, m.type, m.importance_score, m.created_at,
               COALESCE(v.vector_score, 0.0) AS vector_score,
               COALESCE(k.keyword_score, 0.0) AS keyword_score
        FROM memory_items m
        FULL OUTER JOIN vector_results v ON m.id = v.id
        FULL OUTER JOIN keyword_results k ON m.id = k.id
        WHERE (v.id IS NOT NULL OR k.id IS NOT NULL)
          [AND m.type = :type_filter]
        LIMIT :limit * 2

    Args:
        session: Async database session.
        query_text: The user's search query (for FTS).
        query_embedding: Pre-computed embedding vector for the query.
        limit: Maximum results to fetch (before re-ranking).
        type_filter: Optional memory type to restrict results.

    Returns:
        List of Row objects with id, content, summary, type,
        importance_score, created_at, vector_score, keyword_score.
    """
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    type_clause = "AND m.type = :type_filter" if type_filter else ""

    sql = text(f"""
        WITH vector_results AS (
            SELECT id, 1 - (embedding <=> :embedding ::vector) AS vector_score
            FROM memory_items
            ORDER BY embedding <=> :embedding ::vector
            LIMIT 100
        ),
        keyword_results AS (
            SELECT id,
                   ts_rank(
                       to_tsvector('english', content),
                       plainto_tsquery('english', :q)
                   ) AS keyword_score
            FROM memory_items
            WHERE to_tsvector('english', content) @@ plainto_tsquery('english', :q)
            LIMIT 100
        )
        SELECT
            m.id,
            m.content,
            m.summary,
            m.type,
            COALESCE(m.importance_score, 0.5) AS importance_score,
            m.created_at,
            COALESCE(v.vector_score, 0.0) AS vector_score,
            COALESCE(k.keyword_score, 0.0) AS keyword_score
        FROM memory_items m
        FULL OUTER JOIN vector_results v ON m.id = v.id
        FULL OUTER JOIN keyword_results k ON m.id = k.id
        WHERE (v.id IS NOT NULL OR k.id IS NOT NULL)
          {type_clause}
        LIMIT :fetch_limit
    """)

    params: dict = {
        "embedding": embedding_str,
        "q": query_text,
        "fetch_limit": limit * 2,
    }
    if type_filter:
        params["type_filter"] = type_filter

    result = await session.execute(sql, params)
    return result.fetchall()


async def hybrid_search(
    session: AsyncSession,
    query_text: str,
    query_embedding: list[float],
    limit: int = 10,
    type_filter: str | None = None,
) -> list[SearchResult]:
    """Run hybrid search and return ranked results.

    Combines vector similarity and full-text search scores with importance
    and recency to produce a combined_score. Logs a RetrievalEvent for
    every result (FIX-3: feeds dynamic_importance daily aggregation job).

    Args:
        session: Async database session.
        query_text: User's search query string.
        query_embedding: Pre-computed embedding for query_text (1024-dim).
        limit: Maximum number of results to return.
        type_filter: Optional type filter ('memory', 'decision', 'task').

    Returns:
        List of SearchResult, sorted by combined_score descending.
    """
    rows = await _execute_hybrid_sql(session, query_text, query_embedding, limit, type_filter)

    now = datetime.now(tz=timezone.utc)
    results: list[SearchResult] = []

    for row in rows:
        # Compute age in days for recency scoring
        created_at = row.created_at
        if created_at is not None and hasattr(created_at, "tzinfo"):
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            age_days = (now - created_at).total_seconds() / 86400
        else:
            age_days = 0.0

        recency = recency_score(age_days)

        # Normalise keyword score (ts_rank returns 0.0–1.0 in practice but can exceed 1)
        raw_keyword = float(row.keyword_score or 0.0)
        keyword = min(raw_keyword, 1.0)

        score = combined_score(
            vector_score=float(row.vector_score or 0.0),
            keyword_score=keyword,
            importance_score=float(row.importance_score or 0.0),
            recency_score_val=recency,
        )

        results.append(
            SearchResult(
                id=str(row.id),
                content=row.content,
                summary=row.summary,
                type=row.type,
                importance_score=float(row.importance_score or 0.0),
                combined_score=score,
                created_at=row.created_at,
            )
        )

    # Sort descending by combined_score
    results.sort(key=lambda r: r.combined_score, reverse=True)
    results = results[:limit]

    # Log retrieval events for dynamic importance (FIX-3)
    # UUID(as_uuid=True) columns expect a UUID object, not a string
    if results:
        events = [RetrievalEvent(memory_id=UUID(r.id)) for r in results]
        session.add_all(events)
        await session.flush()

    logger.info(
        "hybrid_search_complete",
        query=query_text,
        result_count=len(results),
        type_filter=type_filter,
    )
    return results
