"""Dead-letter queue management and job trigger endpoints.

GET  /v1/queue/status              — aggregate queue counts + worker health signal
GET  /v1/dead-letters              — list failed refinement jobs
POST /v1/dead-letters/{id}/retry   — re-enqueue a dead-letter job (retry_count < limit guard)
POST /v1/synthesis/run             — manually trigger weekly synthesis job
"""

import uuid as _uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import dead_letters_limit, limiter
from src.core.database import get_db
from src.core.models import FailedRefinement, RefinementQueue

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Pydantic models ────────────────────────────────────────────────────────────


class FailedRefinementResponse(BaseModel):
    id: str
    raw_id: str
    queue_id: str
    error_reason: str
    attempt_count: int
    last_output: str | None
    retry_count: int
    created_at: datetime
    resolved_at: datetime | None


class DeadLetterListResponse(BaseModel):
    items: list[FailedRefinementResponse]
    total: int


class RetryResponse(BaseModel):
    id: str
    queue_id: str
    retry_count: int
    message: str


class QueueStatusResponse(BaseModel):
    pending: int
    processing: int
    done: int
    failed: int
    total: int
    oldest_locked_at: datetime | None


# ── Helpers ────────────────────────────────────────────────────────────────────


def _parse_uuid(value: str, field: str = "id") -> _uuid.UUID:
    """Parse UUID string, raise 422 on failure."""
    try:
        return _uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{field} is not a valid UUID") from None


def _failed_to_response(f: FailedRefinement) -> FailedRefinementResponse:
    return FailedRefinementResponse(
        id=str(f.id),
        raw_id=str(f.raw_id),
        queue_id=str(f.queue_id),
        error_reason=f.error_reason,
        attempt_count=f.attempt_count,
        last_output=f.last_output,
        retry_count=f.retry_count,
        created_at=f.created_at,
        resolved_at=f.resolved_at,
    )


def _get_settings():
    from src.core import config
    if config.settings is None:
        config.settings = config.Settings()
    return config.settings


# ── GET /v1/queue/status ──────────────────────────────────────────────────────


@router.get("/v1/queue/status", response_model=QueueStatusResponse)
async def get_queue_status(
    session: AsyncSession = Depends(get_db),
) -> QueueStatusResponse:
    """Return aggregate counts for the refinement queue by status.

    Also exposes oldest_locked_at (MIN of locked_at for processing rows) as a
    worker health signal — a stale value here means the worker may be stuck.

    Returns:
        QueueStatusResponse with per-status counts and oldest processing lock.

    Raises:
        401: Missing or invalid X-API-Key (handled by middleware).
    """
    counts_result = await session.execute(
        select(RefinementQueue.status, func.count().label("n")).group_by(RefinementQueue.status)
    )
    counts: dict[str, int] = {row.status: row.n for row in counts_result.all()}

    locked_result = await session.execute(
        select(func.min(RefinementQueue.locked_at)).where(RefinementQueue.status == "processing")
    )
    oldest_locked_at: datetime | None = locked_result.scalar_one_or_none()

    pending = counts.get("pending", 0)
    processing = counts.get("processing", 0)
    done = counts.get("done", 0)
    failed = counts.get("failed", 0)

    logger.info("queue_status_fetched", pending=pending, processing=processing)
    return QueueStatusResponse(
        pending=pending,
        processing=processing,
        done=done,
        failed=failed,
        total=pending + processing + done + failed,
        oldest_locked_at=oldest_locked_at,
    )


# ── GET /v1/dead-letters ───────────────────────────────────────────────────────


@router.get("/v1/dead-letters", response_model=DeadLetterListResponse)
async def list_dead_letters(
    resolved: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> DeadLetterListResponse:
    """List failed refinement jobs (dead-letter queue).

    By default returns unresolved jobs (resolved_at IS NULL).

    Args:
        resolved: If None or False, return unresolved jobs. If True, return resolved jobs.
        limit: Maximum results to return (1–500).
        offset: Number of results to skip.

    Returns:
        DeadLetterListResponse with matching dead-letter items and total count.
    """
    stmt = select(FailedRefinement)
    count_stmt = select(func.count()).select_from(FailedRefinement)

    if resolved is True:
        stmt = stmt.where(FailedRefinement.resolved_at.is_not(None))
        count_stmt = count_stmt.where(FailedRefinement.resolved_at.is_not(None))
    else:
        # Default: show unresolved (resolved=None or resolved=False)
        stmt = stmt.where(FailedRefinement.resolved_at.is_(None))
        count_stmt = count_stmt.where(FailedRefinement.resolved_at.is_(None))

    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    items = list(result.scalars().all())

    logger.info("list_dead_letters", total=total, returned=len(items), resolved=resolved)
    return DeadLetterListResponse(items=[_failed_to_response(i) for i in items], total=total)


# ── POST /v1/dead-letters/{failed_id}/retry ────────────────────────────────────


@router.post("/v1/dead-letters/{failed_id}/retry", response_model=RetryResponse)
@limiter.limit(dead_letters_limit)
async def retry_dead_letter(
    request: Request,
    failed_id: str,
    session: AsyncSession = Depends(get_db),
) -> RetryResponse:
    """Re-enqueue a dead-letter job for processing.

    Increments retry_count and resets the associated refinement_queue row back
    to 'pending' so the worker will pick it up again.

    Args:
        failed_id: UUID of the FailedRefinement to retry.

    Returns:
        RetryResponse with updated retry_count.

    Raises:
        404: If failed_id does not match any FailedRefinement.
        409: If retry_count has reached dead_letter_retry_limit.
        422: If failed_id is not a valid UUID.
    """
    failed_uuid = _parse_uuid(failed_id, "failed_id")

    failed = await session.get(FailedRefinement, failed_uuid)
    if failed is None:
        raise HTTPException(status_code=404, detail=f"FailedRefinement {failed_id} not found")

    _settings = _get_settings()
    if failed.retry_count >= _settings.dead_letter_retry_limit:
        raise HTTPException(
            status_code=409,
            detail=f"Retry limit of {_settings.dead_letter_retry_limit} reached for dead-letter {failed_id}",
        )

    # Fetch the associated queue row (no ORM relationship — must fetch separately)
    queue_row = await session.get(RefinementQueue, failed.queue_id)
    if queue_row is None:
        raise HTTPException(
            status_code=404,
            detail=f"RefinementQueue {str(failed.queue_id)} not found for dead-letter {failed_id}",
        )

    failed.retry_count += 1
    queue_row.status = "pending"
    queue_row.attempts = 0
    queue_row.locked_at = None

    await session.flush()
    await session.commit()

    logger.info(
        "dead_letter_retry_enqueued",
        failed_id=failed_id,
        retry_count=failed.retry_count,
        queue_id=str(failed.queue_id),
    )
    return RetryResponse(
        id=str(failed.id),
        queue_id=str(failed.queue_id),
        retry_count=failed.retry_count,
        message="Re-enqueued for processing",
    )


# ── POST /v1/synthesis/run ─────────────────────────────────────────────────────


class SynthesisRunRequest(BaseModel):
    days: int = Field(default=7, ge=1, le=365, description="Days to look back for memories")


class SynthesisRunResponse(BaseModel):
    synthesis_id: str | None
    memory_count: int
    date_from: str
    date_to: str
    skipped: bool
    message: str


@router.post("/v1/synthesis/run", response_model=SynthesisRunResponse)
async def run_synthesis(
    request: SynthesisRunRequest = Body(default=SynthesisRunRequest()),
    session: AsyncSession = Depends(get_db),
) -> SynthesisRunResponse:
    """Trigger a weekly synthesis job for recent memories.

    Fetches memory_items from the last N days, clusters by entities, calls
    Claude to produce a structured digest, and stores the result as a MemoryItem
    with source='synthesis' in the linked RawMemory row.

    Args:
        request: days to look back (1–90, default 7)

    Returns:
        SynthesisRunResponse with synthesis_id, memory_count, date range.

    Raises:
        400: ANTHROPIC_API_KEY is not configured.
        401: Missing or invalid X-API-Key (middleware).
        500: LLM call or storage failure.
    """
    settings = _get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=400,
            detail="ANTHROPIC_API_KEY is not configured. Cannot run synthesis.",
        )

    from src.jobs.synthesis import run_synthesis_job
    from src.llm.client import AnthropicClient

    client = AnthropicClient(
        api_key=settings.anthropic_api_key.get_secret_value(),
        model=settings.synthesis_model,
    )

    try:
        result: dict[str, Any] = await run_synthesis_job(session, client, days=request.days)
    except Exception as exc:
        logger.exception("synthesis_run_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Synthesis failed: {exc}") from exc

    logger.info("synthesis_run_complete", **result)
    return SynthesisRunResponse(
        synthesis_id=result.get("synthesis_id"),
        memory_count=result["memory_count"],
        date_from=result["date_from"],
        date_to=result["date_to"],
        skipped=result.get("skipped", False),
        message="Skipped — no memories found in window" if result.get("skipped") else "Synthesis complete",
    )
