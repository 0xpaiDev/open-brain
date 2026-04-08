"""Job monitoring endpoints.

GET /v1/jobs/status  — last run time, status, and overdue flag for each job.
GET /v1/jobs/history — paginated job run history with optional filters.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import limiter
from src.core.database import get_db
from src.core.models import JobRun

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Pydantic response models ────────────────────────────────────────────────


class JobRunItem(BaseModel):
    id: str
    job_name: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    error_message: str | None
    duration_seconds: float | None
    created_at: datetime


class JobHistoryResponse(BaseModel):
    items: list[JobRunItem]
    total: int

# Overdue thresholds per job
_OVERDUE_THRESHOLDS: dict[str, timedelta] = {
    "pulse": timedelta(hours=26),
    "importance": timedelta(hours=26),
    "synthesis": timedelta(days=8),
}

_SCHEDULES: dict[str, str] = {
    "pulse": "daily 05:00 UTC",
    "importance": "daily 01:00 UTC",
    "synthesis": "weekly Sun 00:00 UTC",
}


@router.get("/v1/jobs/status")
@limiter.limit("30/minute")
async def job_status(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Return last run info and overdue status for each scheduled job.

    Returns:
        200: {jobs: {<name>: {last_run, last_status, overdue, schedule}}, checked_at}
    """
    now = datetime.now(UTC)
    jobs: dict[str, dict] = {}

    for job_name in ("pulse", "importance", "synthesis"):
        result = await session.execute(
            select(JobRun)
            .where(JobRun.job_name == job_name)
            .order_by(desc(JobRun.started_at))
            .limit(1)
        )
        last_run = result.scalar_one_or_none()

        threshold = _OVERDUE_THRESHOLDS[job_name]
        if last_run and last_run.finished_at:
            overdue = (now - last_run.finished_at) > threshold
        elif last_run:
            overdue = (now - last_run.started_at) > threshold
        else:
            overdue = True  # never ran

        jobs[job_name] = {
            "last_run": last_run.started_at.isoformat() if last_run else None,
            "last_status": last_run.status if last_run else None,
            "duration_seconds": last_run.duration_seconds if last_run else None,
            "error": last_run.error_message if last_run and last_run.error_message else None,
            "overdue": overdue,
            "schedule": _SCHEDULES[job_name],
        }

    return {
        "jobs": jobs,
        "scheduler": {
            "container": "openbrain-scheduler",
            "tip": "docker logs openbrain-scheduler --tail=20",
        },
        "checked_at": now.isoformat(),
    }


@router.get("/v1/jobs/history", response_model=JobHistoryResponse)
@limiter.limit("30/minute")
async def job_history(
    request: Request,
    job_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Return paginated job run history with optional filters.

    Returns:
        200: {items: [{id, job_name, started_at, ...}], total: int}
    """
    base = select(JobRun)
    count_q = select(func.count()).select_from(JobRun)

    if job_name is not None:
        base = base.where(JobRun.job_name == job_name)
        count_q = count_q.where(JobRun.job_name == job_name)
    if status is not None:
        base = base.where(JobRun.status == status)
        count_q = count_q.where(JobRun.status == status)

    total = (await session.execute(count_q)).scalar() or 0

    rows = (
        await session.execute(
            base.order_by(desc(JobRun.started_at)).offset(offset).limit(limit)
        )
    ).scalars().all()

    items = [
        {
            "id": str(r.id),
            "job_name": r.job_name,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "status": r.status,
            "error_message": r.error_message,
            "duration_seconds": r.duration_seconds,
            "created_at": r.created_at,
        }
        for r in rows
    ]

    return {"items": items, "total": total}
