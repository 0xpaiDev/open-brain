"""Commitment miss detection cron job.

Runs nightly after day boundary. Marks all pending commitment_entries
for yesterday as "miss". Uses pulse_timezone for day boundary calculation.

Usage:
    python -m src.jobs.commitment_miss
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

import structlog
from sqlalchemy import and_, select, update

from src.core.database import get_db_context
from src.core.models import Commitment, CommitmentEntry

logger = structlog.get_logger(__name__)


def _get_yesterday() -> date:
    """Return yesterday's date in the configured pulse timezone."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from src.core.config import get_settings

    settings = get_settings()
    try:
        tz = ZoneInfo(settings.pulse_timezone)
    except (ZoneInfoNotFoundError, AttributeError):
        tz = ZoneInfo("UTC")

    return (datetime.now(tz) - timedelta(days=1)).date()


async def detect_misses() -> int:
    """Mark yesterday's pending commitment entries as missed.

    Only processes entries for active commitments.

    Returns:
        Number of entries marked as missed.
    """
    yesterday = _get_yesterday()

    async with get_db_context() as session:
        # Get IDs of active commitments
        active_result = await session.execute(
            select(Commitment.id).where(Commitment.status == "active")
        )
        active_ids = [row[0] for row in active_result.all()]

        if not active_ids:
            logger.info("commitment_miss_no_active_commitments")
            return 0

        # Update pending entries for yesterday
        stmt = (
            update(CommitmentEntry)
            .where(
                and_(
                    CommitmentEntry.commitment_id.in_(active_ids),
                    CommitmentEntry.entry_date == yesterday,
                    CommitmentEntry.status == "pending",
                )
            )
            .values(status="miss")
        )
        result = await session.execute(stmt)
        await session.commit()

        count = result.rowcount
        logger.info(
            "commitment_miss_detected",
            date=str(yesterday),
            count=count,
        )
        return count


async def main() -> None:
    """Entry point for the commitment miss detection job."""
    from src.jobs.runner import run_tracked

    await run_tracked("commitment_miss", detect_misses)


if __name__ == "__main__":
    asyncio.run(main())
