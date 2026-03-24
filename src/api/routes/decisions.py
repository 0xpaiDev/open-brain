"""Decision management endpoints.

GET  /v1/decisions   — list decisions with optional memory_id filter
POST /v1/decisions   — create a decision linked to a memory item
"""

import uuid as _uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import decisions_limit, limiter
from src.core.database import get_db
from src.core.models import Decision, MemoryItem

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Pydantic models ────────────────────────────────────────────────────────────


class DecisionCreate(BaseModel):
    memory_id: str
    decision: str
    reasoning: str
    alternatives: list[str] | None = None


class DecisionResponse(BaseModel):
    id: str
    memory_id: str
    decision: str
    reasoning: str
    alternatives: list[str] | None
    created_at: datetime


class DecisionListResponse(BaseModel):
    decisions: list[DecisionResponse]
    total: int


# ── Helpers ────────────────────────────────────────────────────────────────────


def _decision_to_response(d: Decision) -> DecisionResponse:
    return DecisionResponse(
        id=str(d.id),
        memory_id=str(d.memory_id),
        decision=d.decision,
        reasoning=d.reasoning,
        alternatives=d.alternatives,
        created_at=d.created_at,
    )


# ── GET /v1/decisions ──────────────────────────────────────────────────────────


@router.get("/v1/decisions", response_model=DecisionListResponse)
@limiter.limit(decisions_limit)
async def list_decisions(
    request: Request,
    memory_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> DecisionListResponse:
    """List decisions with an optional memory_id filter.

    Args:
        memory_id: UUID of the memory item to filter by (optional).
        limit: Maximum results to return (1–500).
        offset: Number of results to skip.

    Returns:
        DecisionListResponse with matching decisions and total count.

    Raises:
        422: If memory_id is provided but is not a valid UUID.
    """
    stmt = select(Decision)
    count_stmt = select(func.count()).select_from(Decision)

    if memory_id is not None:
        try:
            memory_uuid = _uuid.UUID(memory_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="memory_id is not a valid UUID") from None
        stmt = stmt.where(Decision.memory_id == memory_uuid)
        count_stmt = count_stmt.where(Decision.memory_id == memory_uuid)

    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    decisions = list(result.scalars().all())

    logger.info("list_decisions", total=total, returned=len(decisions))
    return DecisionListResponse(
        decisions=[_decision_to_response(d) for d in decisions], total=total
    )


# ── POST /v1/decisions ─────────────────────────────────────────────────────────


@router.post("/v1/decisions", response_model=DecisionResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(decisions_limit)
async def create_decision(
    request: Request,
    body: DecisionCreate,
    session: AsyncSession = Depends(get_db),
) -> DecisionResponse:
    """Create a decision linked to an existing memory item.

    Args:
        body: DecisionCreate with memory_id, decision text, reasoning, and optional alternatives.

    Returns:
        DecisionResponse with the created decision.

    Raises:
        404: If memory_id does not match any MemoryItem.
        422: If memory_id is not a valid UUID.
    """
    try:
        memory_uuid = _uuid.UUID(body.memory_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="memory_id is not a valid UUID") from None

    memory_item = await session.get(MemoryItem, memory_uuid)
    if memory_item is None:
        raise HTTPException(status_code=404, detail=f"MemoryItem {body.memory_id} not found")

    decision = Decision(
        memory_id=memory_uuid,
        decision=body.decision,
        reasoning=body.reasoning,
        alternatives=body.alternatives,
    )
    session.add(decision)
    await session.flush()
    await session.commit()

    logger.info("create_decision", decision_id=str(decision.id), memory_id=body.memory_id)
    return _decision_to_response(decision)
