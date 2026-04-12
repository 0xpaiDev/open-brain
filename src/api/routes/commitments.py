"""Commitment challenge endpoints.

POST   /v1/commitments            — create commitment + pre-generate entries
GET    /v1/commitments             — list (default: active only, ?status=all)
GET    /v1/commitments/{id}        — single commitment with entries + streak info
PATCH  /v1/commitments/{id}        — update (abandon, etc.)
POST   /v1/commitments/{id}/log    — log count for today's entry
"""

from __future__ import annotations

import uuid as _uuid
from datetime import date, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import commitments_limit, limiter
from src.core.database import get_db
from src.core.models import Commitment, CommitmentEntry

logger = structlog.get_logger(__name__)

router = APIRouter()

_VALID_STATUSES = {"active", "completed", "abandoned"}
_VALID_METRICS = {"reps", "minutes", "tss"}


# ── Pydantic models ────────────────────────────────────────────────────────────


class CommitmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    exercise: str = Field(..., min_length=1, max_length=100)
    daily_target: int = Field(..., gt=0)
    metric: str = "reps"
    start_date: date
    end_date: date

    @field_validator("metric")
    @classmethod
    def validate_metric(cls, v: str) -> str:
        if v not in _VALID_METRICS:
            raise ValueError(f"metric must be one of {sorted(_VALID_METRICS)}")
        return v

    @field_validator("end_date")
    @classmethod
    def validate_end_after_start(cls, v: date, info) -> date:
        start = info.data.get("start_date")
        if start and v < start:
            raise ValueError("end_date must be on or after start_date")
        return v


class CommitmentUpdate(BaseModel):
    status: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(_VALID_STATUSES)}")
        return v


class LogCount(BaseModel):
    count: int = Field(..., gt=0)


class EntryResponse(BaseModel):
    id: str
    commitment_id: str
    entry_date: date
    logged_count: int
    status: str
    created_at: str
    updated_at: str


class CommitmentResponse(BaseModel):
    id: str
    name: str
    exercise: str
    daily_target: int
    metric: str
    start_date: date
    end_date: date
    status: str
    created_at: str
    updated_at: str
    current_streak: int = 0
    entries: list[EntryResponse] = []


class CommitmentListResponse(BaseModel):
    commitments: list[CommitmentResponse]
    total: int


# ── Helpers ────────────────────────────────────────────────────────────────────


def _get_today() -> date:
    """Return today's date in the configured pulse timezone."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from src.core.config import get_settings

    settings = get_settings()
    try:
        tz = ZoneInfo(settings.pulse_timezone)
    except (ZoneInfoNotFoundError, AttributeError):
        tz = ZoneInfo("UTC")

    from datetime import datetime

    return datetime.now(tz).date()


def _compute_streak(entries: list[CommitmentEntry], today: date) -> int:
    """Compute the current consecutive hit streak ending at today (or yesterday)."""
    sorted_entries = sorted(entries, key=lambda e: e.entry_date, reverse=True)
    streak = 0
    for entry in sorted_entries:
        if entry.entry_date > today:
            continue
        if entry.status == "hit":
            streak += 1
        elif entry.status == "pending" and entry.entry_date == today:
            # Today's still pending — skip it, count streak from yesterday
            continue
        else:
            break
    return streak


def _entry_to_response(entry: CommitmentEntry) -> EntryResponse:
    return EntryResponse(
        id=str(entry.id),
        commitment_id=str(entry.commitment_id),
        entry_date=entry.entry_date,
        logged_count=entry.logged_count,
        status=entry.status,
        created_at=str(entry.created_at),
        updated_at=str(entry.updated_at),
    )


def _commitment_to_response(
    commitment: Commitment, entries: list[CommitmentEntry] | None = None, today: date | None = None
) -> CommitmentResponse:
    entry_list = entries or []
    t = today or _get_today()
    return CommitmentResponse(
        id=str(commitment.id),
        name=commitment.name,
        exercise=commitment.exercise,
        daily_target=commitment.daily_target,
        metric=commitment.metric,
        start_date=commitment.start_date,
        end_date=commitment.end_date,
        status=commitment.status,
        created_at=str(commitment.created_at),
        updated_at=str(commitment.updated_at),
        current_streak=_compute_streak(entry_list, t),
        entries=[_entry_to_response(e) for e in entry_list],
    )


# ── POST /v1/commitments ──────────────────────────────────────────────────────


@router.post("/v1/commitments", response_model=CommitmentResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(commitments_limit)
async def create_commitment(
    request: Request,
    body: CommitmentCreate,
    session: AsyncSession = Depends(get_db),
) -> CommitmentResponse:
    """Create a commitment and pre-generate daily entries."""
    commitment = Commitment(
        name=body.name,
        exercise=body.exercise,
        daily_target=body.daily_target,
        metric=body.metric,
        start_date=body.start_date,
        end_date=body.end_date,
    )
    session.add(commitment)
    await session.flush()

    # Pre-generate entries for each day in the range
    entries = []
    current = body.start_date
    while current <= body.end_date:
        entry = CommitmentEntry(
            commitment_id=commitment.id,
            entry_date=current,
        )
        session.add(entry)
        entries.append(entry)
        current += timedelta(days=1)

    await session.commit()
    await session.refresh(commitment)
    for entry in entries:
        await session.refresh(entry)

    logger.info(
        "commitment_created",
        commitment_id=str(commitment.id),
        name=commitment.name,
        days=len(entries),
    )
    return _commitment_to_response(commitment, entries, _get_today())


# ── GET /v1/commitments ───────────────────────────────────────────────────────


@router.get("/v1/commitments", response_model=CommitmentListResponse)
@limiter.limit(commitments_limit)
async def list_commitments(
    request: Request,
    status_filter: str = Query("active", alias="status"),
    session: AsyncSession = Depends(get_db),
) -> CommitmentListResponse:
    """List commitments. Default: active only. Use ?status=all for all."""
    stmt = select(Commitment).order_by(Commitment.created_at.desc())
    if status_filter != "all":
        stmt = stmt.where(Commitment.status == status_filter)

    result = await session.execute(stmt)
    commitments = list(result.scalars().all())

    today = _get_today()
    responses = []
    for c in commitments:
        entries_result = await session.execute(
            select(CommitmentEntry)
            .where(CommitmentEntry.commitment_id == c.id)
            .order_by(CommitmentEntry.entry_date)
        )
        entries = list(entries_result.scalars().all())
        responses.append(_commitment_to_response(c, entries, today))

    return CommitmentListResponse(commitments=responses, total=len(responses))


# ── GET /v1/commitments/{id} ──────────────────────────────────────────────────


@router.get("/v1/commitments/{commitment_id}", response_model=CommitmentResponse)
@limiter.limit(commitments_limit)
async def get_commitment(
    request: Request,
    commitment_id: _uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> CommitmentResponse:
    """Get a single commitment with all entries and streak info."""
    commitment = await session.get(Commitment, commitment_id)
    if commitment is None:
        raise HTTPException(status_code=404, detail="Commitment not found")

    entries_result = await session.execute(
        select(CommitmentEntry)
        .where(CommitmentEntry.commitment_id == commitment.id)
        .order_by(CommitmentEntry.entry_date)
    )
    entries = list(entries_result.scalars().all())

    return _commitment_to_response(commitment, entries, _get_today())


# ── PATCH /v1/commitments/{id} ────────────────────────────────────────────────


@router.patch("/v1/commitments/{commitment_id}", response_model=CommitmentResponse)
@limiter.limit(commitments_limit)
async def update_commitment(
    request: Request,
    commitment_id: _uuid.UUID,
    body: CommitmentUpdate,
    session: AsyncSession = Depends(get_db),
) -> CommitmentResponse:
    """Update commitment fields (e.g., abandon)."""
    commitment = await session.get(Commitment, commitment_id)
    if commitment is None:
        raise HTTPException(status_code=404, detail="Commitment not found")

    if body.status is not None:
        commitment.status = body.status

    await session.commit()
    await session.refresh(commitment)

    entries_result = await session.execute(
        select(CommitmentEntry)
        .where(CommitmentEntry.commitment_id == commitment.id)
        .order_by(CommitmentEntry.entry_date)
    )
    entries = list(entries_result.scalars().all())

    logger.info("commitment_updated", commitment_id=str(commitment.id), status=commitment.status)
    return _commitment_to_response(commitment, entries, _get_today())


# ── POST /v1/commitments/{id}/log ─────────────────────────────────────────────


@router.post("/v1/commitments/{commitment_id}/log", response_model=EntryResponse)
@limiter.limit(commitments_limit)
async def log_count(
    request: Request,
    commitment_id: _uuid.UUID,
    body: LogCount,
    session: AsyncSession = Depends(get_db),
) -> EntryResponse:
    """Log count for today's entry. Increments logged_count additively."""
    today = _get_today()

    # Verify commitment exists and is active
    commitment = await session.get(Commitment, commitment_id)
    if commitment is None:
        raise HTTPException(status_code=404, detail="Commitment not found")
    if commitment.status != "active":
        raise HTTPException(status_code=400, detail="Commitment is not active")

    # Find today's entry
    entry_result = await session.execute(
        select(CommitmentEntry).where(
            CommitmentEntry.commitment_id == commitment_id,
            CommitmentEntry.entry_date == today,
        )
    )
    entry = entry_result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=400,
            detail="No entry for today — date may be outside commitment range",
        )
    if entry.status == "miss":
        raise HTTPException(status_code=400, detail="Cannot log on a missed entry")

    # Increment count
    entry.logged_count += body.count

    # Auto-transition to "hit" when target met
    if entry.logged_count >= commitment.daily_target and entry.status == "pending":
        entry.status = "hit"

    await session.commit()
    await session.refresh(entry)

    logger.info(
        "commitment_logged",
        commitment_id=commitment_id,
        entry_date=str(today),
        logged_count=entry.logged_count,
        status=entry.status,
    )
    return _entry_to_response(entry)
