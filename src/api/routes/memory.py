"""Memory ingestion endpoint.

POST /v1/memory — accept raw text, enqueue for async processing.

The route is stateless: it inserts a raw_memory row and a refinement_queue
row, then returns immediately with the raw_id so the caller can track the job.
The worker picks up the queue row independently.

Content-hash dedup: before creating any rows, SHA-256 hash the normalized
text and query for an existing raw_memory with the same hash within the last
24 hours. If found, return the existing raw_id with status="duplicate" — no
new rows are created and no LLM call is wasted.
"""

import json
import uuid as _uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import limiter, memory_limit
from src.api.services.memory_service import (
    SupersedesInvalidUUID,
    SupersedesNotFound,
)
from src.api.services.memory_service import (
    content_hash as _content_hash,  # re-exported for backward compat with tests
)
from src.api.services.memory_service import (
    ingest_memory as _ingest_memory,
)
from src.core.database import get_db
from src.core.models import MemoryItem

logger = structlog.get_logger(__name__)

router = APIRouter()

_MAX_METADATA_BYTES = 8192  # 8 KB limit on serialized metadata

__all__ = ["router", "_content_hash"]


class MemoryCreate(BaseModel):
    """Request body for POST /v1/memory."""

    text: str = Field(..., min_length=1, max_length=50000)
    source: str = Field("api", max_length=200)
    metadata: dict[str, Any] | None = None
    supersedes_id: str | None = None

    @field_validator("metadata")
    @classmethod
    def validate_metadata_size(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """Reject metadata payloads that exceed the serialized byte limit."""
        if v is None:
            return v
        serialized = json.dumps(v, separators=(",", ":"))
        if len(serialized.encode()) > _MAX_METADATA_BYTES:
            raise ValueError(
                f"metadata exceeds maximum allowed size of {_MAX_METADATA_BYTES} bytes"
            )
        return v


class MemoryResponse(BaseModel):
    """Response body for POST /v1/memory."""

    raw_id: str
    status: str
    supersedes_id: str | None = None


class MemoryItemResponse(BaseModel):
    """Response body for GET /v1/memory/{memory_id}."""

    id: str
    raw_id: str
    type: str
    content: str
    summary: str | None
    base_importance: float
    dynamic_importance: float
    importance_score: float | None
    is_superseded: bool
    supersedes_id: str | None
    project: str | None = None
    created_at: datetime


class MemoryRecentResponse(BaseModel):
    """Response body for GET /v1/memory/recent."""

    items: list[MemoryItemResponse]
    total: int


@router.post("/v1/memory", status_code=status.HTTP_202_ACCEPTED, response_model=MemoryResponse)
@limiter.limit(memory_limit)
async def ingest_memory_route(
    request: Request,
    body: MemoryCreate,
    session: AsyncSession = Depends(get_db),
) -> MemoryResponse:
    """Ingest raw text and enqueue it for async pipeline processing.

    Checks for duplicate content (SHA-256 hash match) within a 24h window.
    If a duplicate is found, returns the existing raw_id with status="duplicate"
    without creating any new rows.

    Otherwise, inserts a raw_memory row (immutable log) and a refinement_queue
    row (status=pending, attempts=0). Returns 202 Accepted with the raw_id.

    Raises:
        422: body validation failure (missing required fields)
        401: missing or invalid X-API-Key (handled by middleware)
    """
    try:
        result = await _ingest_memory(
            session,
            text=body.text,
            source=body.source,
            metadata=body.metadata,
            supersedes_id=body.supersedes_id,
        )
    except SupersedesInvalidUUID:
        raise HTTPException(
            status_code=422, detail="supersedes_id is not a valid UUID"
        ) from None
    except SupersedesNotFound:
        raise HTTPException(status_code=404, detail="supersedes_id not found") from None

    return MemoryResponse(
        raw_id=result.raw_id,
        status=result.status,
        supersedes_id=result.supersedes_id,
    )


def _memory_item_to_response(item: MemoryItem) -> MemoryItemResponse:
    """Convert an ORM MemoryItem to an API response model."""
    return MemoryItemResponse(
        id=str(item.id),
        raw_id=str(item.raw_id),
        type=item.type,
        content=item.content,
        summary=item.summary,
        base_importance=float(item.base_importance),
        dynamic_importance=float(item.dynamic_importance),
        importance_score=(
            float(item.importance_score) if item.importance_score is not None else None
        ),
        is_superseded=item.is_superseded,
        supersedes_id=str(item.supersedes_id) if item.supersedes_id is not None else None,
        project=item.project,
        created_at=item.created_at,
    )


@router.get("/v1/memory/recent", response_model=MemoryRecentResponse)
@limiter.limit(memory_limit)
async def list_recent_memories(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    type_filter: str | None = Query(default=None),
    project_filter: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> MemoryRecentResponse:
    """List recent non-superseded memory items, newest first.

    Args:
        limit: Maximum items to return (1–100, default 20).
        offset: Pagination offset (default 0).
        type_filter: Optional type filter ("memory", "decision", "task").
        project_filter: Optional project name filter.

    Returns:
        MemoryRecentResponse with items list and total count.

    Raises:
        401: Missing or invalid X-API-Key (handled by middleware).
    """
    base = select(MemoryItem).where(MemoryItem.is_superseded == False)  # noqa: E712
    count_base = select(func.count()).select_from(MemoryItem).where(
        MemoryItem.is_superseded == False  # noqa: E712
    )

    if type_filter is not None:
        base = base.where(MemoryItem.type == type_filter)
        count_base = count_base.where(MemoryItem.type == type_filter)

    if project_filter is not None:
        base = base.where(MemoryItem.project == project_filter)
        count_base = count_base.where(MemoryItem.project == project_filter)

    total_result = await session.execute(count_base)
    total = total_result.scalar_one()

    stmt = base.order_by(MemoryItem.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    items = list(result.scalars().all())

    logger.info("memory_recent_listed", total=total, returned=len(items), type_filter=type_filter)
    return MemoryRecentResponse(
        items=[_memory_item_to_response(i) for i in items],
        total=total,
    )


@router.get("/v1/memory/{memory_id}", response_model=MemoryItemResponse)
@limiter.limit(memory_limit)
async def get_memory_item(
    request: Request,
    memory_id: str,
    session: AsyncSession = Depends(get_db),
) -> MemoryItemResponse:
    """Fetch a single processed MemoryItem by its UUID.

    Args:
        memory_id: UUID of the MemoryItem to retrieve.

    Returns:
        MemoryItemResponse with all fields.

    Raises:
        404: If memory_id does not match any MemoryItem.
        422: If memory_id is not a valid UUID.
        401: Missing or invalid X-API-Key (handled by middleware).
    """
    try:
        target_uuid = _uuid.UUID(memory_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="memory_id is not a valid UUID") from None

    item = await session.get(MemoryItem, target_uuid)
    if item is None:
        raise HTTPException(status_code=404, detail=f"MemoryItem {memory_id} not found")

    logger.info("memory_item_fetched", memory_id=memory_id)
    return _memory_item_to_response(item)
