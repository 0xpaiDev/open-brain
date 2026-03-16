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

import hashlib
import uuid as _uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import limiter, memory_limit
from src.core.database import get_db
from src.core.models import MemoryItem, RawMemory, RefinementQueue

logger = structlog.get_logger(__name__)

router = APIRouter()


def _content_hash(text: str) -> str:
    """SHA-256 hash of normalized text (lowercase + collapsed whitespace)."""
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()


class MemoryCreate(BaseModel):
    """Request body for POST /v1/memory."""

    text: str
    source: str = "api"
    metadata: dict[str, Any] | None = None
    supersedes_id: str | None = None


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
    created_at: datetime


@router.post("/v1/memory", status_code=status.HTTP_202_ACCEPTED, response_model=MemoryResponse)
@limiter.limit(memory_limit)
async def ingest_memory(
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
    content_hash = _content_hash(body.text)
    window_start = datetime.now(UTC) - timedelta(hours=24)

    result = await session.execute(
        select(RawMemory)
        .where(RawMemory.content_hash == content_hash)
        .where(RawMemory.created_at >= window_start)
        .limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        logger.info("memory_duplicate_skipped", raw_id=str(existing.id), content_hash=content_hash)
        return MemoryResponse(raw_id=str(existing.id), status="duplicate")

    # Validate supersedes_id and mark original as superseded
    superseded_item: MemoryItem | None = None
    if body.supersedes_id is not None:
        try:
            target_uuid = _uuid.UUID(body.supersedes_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="supersedes_id is not a valid UUID") from None
        superseded_item = await session.get(MemoryItem, target_uuid)
        if superseded_item is None:
            raise HTTPException(status_code=404, detail="supersedes_id not found")

    # Build metadata: merge caller metadata with side-channel key for worker
    merged_metadata: dict[str, Any] | None = body.metadata
    if body.supersedes_id is not None:
        merged_metadata = dict(body.metadata or {})
        merged_metadata["supersedes_memory_id"] = body.supersedes_id

    raw = RawMemory(
        source=body.source,
        raw_text=body.text,
        metadata_=merged_metadata,
        content_hash=content_hash,
    )
    session.add(raw)
    await session.flush()  # populate raw.id before FK use

    if superseded_item is not None:
        superseded_item.is_superseded = True
        await session.flush()

    queue_entry = RefinementQueue(raw_id=raw.id)
    session.add(queue_entry)
    await session.flush()
    await session.commit()

    logger.info(
        "memory_ingested",
        raw_id=str(raw.id),
        source=body.source,
        supersedes_id=body.supersedes_id,
    )
    return MemoryResponse(raw_id=str(raw.id), status="queued", supersedes_id=body.supersedes_id)


@router.get("/v1/memory/{memory_id}", response_model=MemoryItemResponse)
async def get_memory_item(
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
    return MemoryItemResponse(
        id=str(item.id),
        raw_id=str(item.raw_id),
        type=item.type,
        content=item.content,
        summary=item.summary,
        base_importance=float(item.base_importance),
        dynamic_importance=float(item.dynamic_importance),
        importance_score=float(item.importance_score) if item.importance_score is not None else None,
        is_superseded=item.is_superseded,
        supersedes_id=str(item.supersedes_id) if item.supersedes_id is not None else None,
        created_at=item.created_at,
    )
