"""Memory ingestion endpoint.

POST /v1/memory — accept raw text, enqueue for async processing.

The route is stateless: it inserts a raw_memory row and a refinement_queue
row, then returns immediately with the raw_id so the caller can track the job.
The worker picks up the queue row independently.
"""

from typing import Any

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.models import RawMemory, RefinementQueue

logger = structlog.get_logger(__name__)

router = APIRouter()


class MemoryCreate(BaseModel):
    """Request body for POST /v1/memory."""

    text: str
    source: str = "api"
    metadata: dict[str, Any] | None = None


class MemoryResponse(BaseModel):
    """Response body for POST /v1/memory."""

    raw_id: str
    status: str


@router.post("/v1/memory", status_code=status.HTTP_202_ACCEPTED, response_model=MemoryResponse)
async def ingest_memory(
    body: MemoryCreate,
    session: AsyncSession = Depends(get_db),
) -> MemoryResponse:
    """Ingest raw text and enqueue it for async pipeline processing.

    Inserts a raw_memory row (immutable log) and a refinement_queue row
    (status=pending, attempts=0). Returns 202 Accepted with the raw_id.

    Raises:
        422: body validation failure (missing required fields)
        401: missing or invalid X-API-Key (handled by middleware)
    """
    raw = RawMemory(
        source=body.source,
        raw_text=body.text,
        metadata_=body.metadata,
    )
    session.add(raw)
    await session.flush()  # populate raw.id before FK use

    queue_entry = RefinementQueue(raw_id=raw.id)
    session.add(queue_entry)
    await session.flush()
    await session.commit()

    logger.info("memory_ingested", raw_id=str(raw.id), source=body.source)
    return MemoryResponse(raw_id=str(raw.id), status="queued")
