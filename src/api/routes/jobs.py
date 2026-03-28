"""Job monitoring endpoint.

GET /v1/jobs/status — last run time, status, and overdue flag for each job.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import limiter
from src.core.database import get_db
from src.core.models import JobRun

logger = structlog.get_logger(__name__)

router = APIRouter()

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
