"""Training summary endpoints.

POST   /v1/training/weekly-sync  — trigger weekly training summary sync to memory
GET    /v1/training/summary      — get current week's training data
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import limiter, training_limit
from src.core.database import get_db
from src.core.models import Commitment, CommitmentEntry, DailyPulse, StravaActivity

logger = structlog.get_logger(__name__)

router = APIRouter()


def _get_today() -> date:
    """Return today's date in the configured pulse timezone."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from src.core.config import get_settings

    settings = get_settings()
    try:
        tz = ZoneInfo(settings.pulse_timezone)
    except (ZoneInfoNotFoundError, AttributeError):
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


# ── Pydantic models ────────────────────────────────────────────────────────────


class WeeklySyncResponse(BaseModel):
    memory_id: str | None
    status: str


class TrainingSummaryResponse(BaseModel):
    week_start: date
    week_end: date
    strava_activity_count: int
    strava_total_distance_km: float
    strava_total_duration_h: float
    strava_total_tss: float
    clean_meal_days: int
    alcohol_days: int
    pulse_days: int
    commitments: list[dict]


# ── POST /v1/training/weekly-sync ────────────────────────────────────────────���


@router.post("/v1/training/weekly-sync", response_model=WeeklySyncResponse)
@limiter.limit(training_limit)
async def trigger_weekly_sync(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> WeeklySyncResponse:
    """Manually trigger weekly training summary sync to memory."""
    try:
        from src.llm.client import embedding_client
        from src.pipeline.training_sync import sync_weekly_training

        if not embedding_client:
            raise HTTPException(
                status_code=503,
                detail="Embedding client not available",
            )

        memory_id = await sync_weekly_training(session, embedding_client)
        return WeeklySyncResponse(
            memory_id=memory_id,
            status="synced" if memory_id else "no_data",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("weekly_sync_failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Weekly sync failed") from exc


# ── GET /v1/training/summary ──────��───────────────────────────���───────────────


@router.get("/v1/training/summary", response_model=TrainingSummaryResponse)
@limiter.limit(training_limit)
async def get_training_summary(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> TrainingSummaryResponse:
    """Get current week's training data summary."""
    today = _get_today()
    week_start = today - timedelta(days=6)
    week_end = today

    week_start_dt = datetime(week_start.year, week_start.month, week_start.day, tzinfo=UTC)
    week_end_dt = datetime(
        week_end.year, week_end.month, week_end.day, 23, 59, 59, tzinfo=UTC
    )

    # Strava activities
    activities_result = await session.execute(
        select(StravaActivity).where(
            and_(
                StravaActivity.started_at >= week_start_dt,
                StravaActivity.started_at <= week_end_dt,
            )
        )
    )
    activities = list(activities_result.scalars().all())
    total_distance_km = sum(a.distance_m or 0 for a in activities) / 1000
    total_duration_h = sum(a.duration_s or 0 for a in activities) / 3600
    total_tss = sum(a.tss or 0 for a in activities)

    # Nutrition from pulse
    pulses_result = await session.execute(
        select(DailyPulse).where(
            and_(
                DailyPulse.pulse_date >= week_start_dt,
                DailyPulse.pulse_date <= week_end_dt,
            )
        )
    )
    pulses = list(pulses_result.scalars().all())
    clean_days = sum(1 for p in pulses if p.clean_meal is True)
    alcohol_days = sum(1 for p in pulses if p.alcohol is True)

    # Commitment summaries
    active_result = await session.execute(
        select(Commitment).where(Commitment.status == "active")
    )
    commitment_data = []
    for c in active_result.scalars():
        entries_result = await session.execute(
            select(CommitmentEntry).where(
                and_(
                    CommitmentEntry.commitment_id == c.id,
                    CommitmentEntry.entry_date >= week_start,
                    CommitmentEntry.entry_date <= week_end,
                )
            )
        )
        entries = list(entries_result.scalars().all())
        commitment_data.append({
            "name": c.name,
            "exercise": c.exercise,
            "daily_target": c.daily_target,
            "metric": c.metric,
            "hits": sum(1 for e in entries if e.status == "hit"),
            "misses": sum(1 for e in entries if e.status == "miss"),
            "pending": sum(1 for e in entries if e.status == "pending"),
        })

    return TrainingSummaryResponse(
        week_start=week_start,
        week_end=week_end,
        strava_activity_count=len(activities),
        strava_total_distance_km=round(total_distance_km, 1),
        strava_total_duration_h=round(total_duration_h, 1),
        strava_total_tss=round(total_tss, 0),
        clean_meal_days=clean_days,
        alcohol_days=alcohol_days,
        pulse_days=len(pulses),
        commitments=commitment_data,
    )
