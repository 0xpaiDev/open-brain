"""Morning Pulse API endpoints.

POST   /v1/pulse              — create today's pulse record (one per day, 409 on duplicate)
GET    /v1/pulse/today        — today's pulse or 404
PATCH  /v1/pulse/today        — update reply fields on today's pulse
GET    /v1/pulse              — paginated history (newest first)
GET    /v1/pulse/{pulse_date} — specific date (YYYY-MM-DD) or 404

Note: /v1/pulse/today must be declared before /v1/pulse/{pulse_date} to
prevent FastAPI from matching the literal string "today" as a date.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import limiter, pulse_limit
from src.core.database import get_db
from src.core.models import DailyPulse, TodoItem

logger = structlog.get_logger(__name__)

router = APIRouter()

_VALID_STATUSES = {"sent", "replied", "parsed", "parse_failed", "skipped", "expired", "completed"}


# ── Settings helper ────────────────────────────────────────────────────────────


def _get_settings():
    from src.core import config

    if config.settings is None:
        config.settings = config.Settings()
    return config.settings


# ── Pydantic models ────────────────────────────────────────────────────────────


class PulseCreate(BaseModel):
    pulse_date: datetime
    status: str = "sent"
    discord_message_id: str | None = None
    ai_question: str | None = None


class PulseUpdate(BaseModel):
    raw_reply: str | None = None
    sleep_quality: int | None = None
    energy_level: int | None = None
    wake_time: str | None = None
    parsed_data: dict | None = None
    ai_question_response: str | None = None
    notes: str | None = None
    status: str | None = None

    @field_validator("sleep_quality", "energy_level")
    @classmethod
    def validate_scale(cls, v: int | None) -> int | None:
        if v is not None and not (1 <= v <= 5):
            raise ValueError("must be between 1 and 5")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(_VALID_STATUSES)}")
        return v


class PulseResponse(BaseModel):
    id: str
    pulse_date: datetime
    raw_reply: str | None
    sleep_quality: int | None
    energy_level: int | None
    wake_time: str | None
    parsed_data: dict | None
    ai_question: str | None
    ai_question_response: str | None
    notes: str | None
    status: str
    discord_message_id: str | None
    created_at: datetime
    updated_at: datetime


class PulseListResponse(BaseModel):
    pulses: list[PulseResponse]
    total: int


# ── Helpers ────────────────────────────────────────────────────────────────────


def _pulse_to_response(pulse: DailyPulse) -> PulseResponse:
    return PulseResponse(
        id=str(pulse.id),
        pulse_date=pulse.pulse_date,
        raw_reply=pulse.raw_reply,
        sleep_quality=pulse.sleep_quality,
        energy_level=pulse.energy_level,
        wake_time=pulse.wake_time,
        parsed_data=pulse.parsed_data,
        ai_question=pulse.ai_question,
        ai_question_response=pulse.ai_question_response,
        notes=pulse.notes,
        status=pulse.status,
        discord_message_id=pulse.discord_message_id,
        created_at=pulse.created_at,
        updated_at=pulse.updated_at,
    )


def _today_midnight_utc() -> datetime:
    """Return today's midnight in UTC, adjusted for the configured pulse timezone."""
    settings = _get_settings()
    try:
        tz = ZoneInfo(settings.pulse_timezone)
    except (ZoneInfoNotFoundError, AttributeError):
        tz = ZoneInfo("UTC")

    local_midnight = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(ZoneInfo("UTC"))


# ── POST /v1/pulse/start ──────────────────────────────────────────────────────


@router.post("/v1/pulse/start", response_model=PulseResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(pulse_limit)
async def start_pulse(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> PulseResponse:
    """Create today's pulse with an AI-generated question.

    Queries open todos from the DB, fetches yesterday's ai_question for
    alternation, calls _generate_ai_question(), and persists the pulse.

    Returns:
        PulseResponse with ai_question populated.

    Raises:
        409: If a pulse record already exists for today.
    """
    from datetime import timedelta

    from src.jobs.pulse import _generate_ai_question

    today_start = _today_midnight_utc()

    # Check if pulse already exists today
    existing_stmt = (
        select(DailyPulse)
        .where(DailyPulse.pulse_date >= today_start)
        .limit(1)
    )
    existing = (await session.execute(existing_stmt)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="A pulse record already exists for today")

    # Fetch open todos from DB directly
    todo_stmt = (
        select(TodoItem)
        .where(TodoItem.status == "open")
        .limit(25)
    )
    todo_rows = (await session.execute(todo_stmt)).scalars().all()
    open_todos = [{"description": t.description, "due_date": t.due_date.isoformat() if t.due_date else None} for t in todo_rows]

    # Fetch yesterday's ai_question for alternation
    yesterday_start = today_start - timedelta(days=1)
    yesterday_stmt = (
        select(DailyPulse)
        .where(DailyPulse.pulse_date >= yesterday_start, DailyPulse.pulse_date < today_start)
        .limit(1)
    )
    yesterday_pulse = (await session.execute(yesterday_stmt)).scalar_one_or_none()
    yesterday_question = yesterday_pulse.ai_question if yesterday_pulse else None

    # Get LLM client (None if no API key)
    llm = None
    try:
        from src.llm.client import anthropic_client

        llm = anthropic_client
    except Exception:
        pass

    ai_question = await _generate_ai_question(llm, open_todos=open_todos, yesterday_question=yesterday_question)

    # Create pulse record
    pulse = DailyPulse(
        pulse_date=today_start,
        status="sent",
        ai_question=ai_question,
    )
    session.add(pulse)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="A pulse record already exists for today") from None

    await session.commit()
    await session.refresh(pulse)
    logger.info("start_pulse", pulse_id=str(pulse.id), ai_question=ai_question[:60])
    return _pulse_to_response(pulse)


# ── POST /v1/pulse ─────────────────────────────────────────────────────────────


@router.post("/v1/pulse", response_model=PulseResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(pulse_limit)
async def create_pulse(
    request: Request,
    body: PulseCreate,
    session: AsyncSession = Depends(get_db),
) -> PulseResponse:
    """Create a pulse record for today. Enforces one record per calendar day.

    Args:
        body: PulseCreate with pulse_date (required), status, discord_message_id,
              and ai_question.

    Returns:
        PulseResponse with the created record.

    Raises:
        409: If a pulse record already exists for this date.
    """
    pulse = DailyPulse(
        pulse_date=body.pulse_date,
        status=body.status,
        discord_message_id=body.discord_message_id,
        ai_question=body.ai_question,
    )
    session.add(pulse)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="A pulse record already exists for this date") from None

    await session.commit()
    await session.refresh(pulse)
    logger.info("create_pulse", pulse_id=str(pulse.id), status=pulse.status)
    return _pulse_to_response(pulse)


# ── GET /v1/pulse/today ────────────────────────────────────────────────────────
# IMPORTANT: must be declared before /v1/pulse/{pulse_date}


@router.get("/v1/pulse/today", response_model=PulseResponse)
@limiter.limit(pulse_limit)
async def get_today_pulse(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> PulseResponse:
    """Return today's pulse record.

    Returns:
        PulseResponse for today.

    Raises:
        404: If no pulse has been sent today.
    """
    today_start = _today_midnight_utc()
    stmt = (
        select(DailyPulse)
        .where(DailyPulse.pulse_date >= today_start)
        .order_by(desc(DailyPulse.pulse_date))
        .limit(1)
    )
    result = await session.execute(stmt)
    pulse = result.scalar_one_or_none()

    if pulse is None:
        raise HTTPException(status_code=404, detail="No pulse record found for today")

    return _pulse_to_response(pulse)


# ── PATCH /v1/pulse/today ──────────────────────────────────────────────────────


@router.patch("/v1/pulse/today", response_model=PulseResponse)
@limiter.limit(pulse_limit)
async def update_today_pulse(
    request: Request,
    body: PulseUpdate,
    session: AsyncSession = Depends(get_db),
) -> PulseResponse:
    """Update reply fields on today's pulse record.

    Only non-None fields in the request body are applied.

    Returns:
        Updated PulseResponse.

    Raises:
        404: If no pulse has been sent today.
        422: If field values are invalid (sleep_quality/energy_level out of 1–5 range,
             invalid status).
    """
    today_start = _today_midnight_utc()
    stmt = (
        select(DailyPulse)
        .where(DailyPulse.pulse_date >= today_start)
        .order_by(desc(DailyPulse.pulse_date))
        .limit(1)
    )
    result = await session.execute(stmt)
    pulse = result.scalar_one_or_none()

    if pulse is None:
        raise HTTPException(status_code=404, detail="No pulse record found for today")

    if body.raw_reply is not None:
        pulse.raw_reply = body.raw_reply
    if body.sleep_quality is not None:
        pulse.sleep_quality = body.sleep_quality
    if body.energy_level is not None:
        pulse.energy_level = body.energy_level
    if body.wake_time is not None:
        pulse.wake_time = body.wake_time
    if body.parsed_data is not None:
        pulse.parsed_data = body.parsed_data
    if body.ai_question_response is not None:
        pulse.ai_question_response = body.ai_question_response
    if body.notes is not None:
        pulse.notes = body.notes
    if body.status is not None:
        pulse.status = body.status

    await session.flush()
    await session.commit()
    await session.refresh(pulse)
    logger.info("update_today_pulse", pulse_id=str(pulse.id), status=pulse.status)
    return _pulse_to_response(pulse)


# ── GET /v1/pulse ──────────────────────────────────────────────────────────────


@router.get("/v1/pulse", response_model=PulseListResponse)
@limiter.limit(pulse_limit)
async def list_pulses(
    request: Request,
    limit: int = Query(default=30, ge=1, le=365),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> PulseListResponse:
    """Return paginated pulse history, newest first.

    Args:
        limit: Maximum results per page (1–365, default 30).
        offset: Number of results to skip.

    Returns:
        PulseListResponse with pulses and total count.
    """
    count_stmt = select(func.count()).select_from(DailyPulse)
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = select(DailyPulse).order_by(desc(DailyPulse.pulse_date)).offset(offset).limit(limit)
    result = await session.execute(stmt)
    pulses = list(result.scalars().all())

    logger.info("list_pulses", total=total, returned=len(pulses))
    return PulseListResponse(pulses=[_pulse_to_response(p) for p in pulses], total=total)


# ── GET /v1/pulse/{pulse_date} ─────────────────────────────────────────────────
# IMPORTANT: declared after /v1/pulse/today to avoid shadowing


@router.get("/v1/pulse/{pulse_date}", response_model=PulseResponse)
@limiter.limit(pulse_limit)
async def get_pulse_by_date(
    request: Request,
    pulse_date: str,
    session: AsyncSession = Depends(get_db),
) -> PulseResponse:
    """Return the pulse record for a specific date.

    Args:
        pulse_date: Date in YYYY-MM-DD format.

    Returns:
        PulseResponse for that date.

    Raises:
        404: If no pulse exists for this date.
        422: If pulse_date is not a valid YYYY-MM-DD string.
    """
    try:
        target_date = date.fromisoformat(pulse_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="pulse_date must be in YYYY-MM-DD format") from None

    # Match any pulse whose pulse_date falls within the target calendar day (UTC)
    day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=UTC)
    day_end = datetime(target_date.year, target_date.month, target_date.day + 1 if target_date.day < 28 else 1,
                       tzinfo=UTC)

    # Safer: use date arithmetic
    from datetime import timedelta

    day_end = day_start + timedelta(days=1)

    stmt = (
        select(DailyPulse)
        .where(DailyPulse.pulse_date >= day_start, DailyPulse.pulse_date < day_end)
        .limit(1)
    )
    result = await session.execute(stmt)
    pulse = result.scalar_one_or_none()

    if pulse is None:
        raise HTTPException(status_code=404, detail=f"No pulse record found for {pulse_date}")

    return _pulse_to_response(pulse)
