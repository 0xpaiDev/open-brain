"""Observability raw-payload retention sweep for Open Brain.

Nulls raw_request and raw_response on LLMCall rows whose parent trace:
  - has status != 'failed'  (failed traces are exempt from sweeping)
  - has started_at older than OB_OBSERVABILITY_RAW_TTL_DAYS days

Settings used
-------------
- observability_raw_ttl_days (default: 90)

Invocation
----------
    python -m src.jobs.observability_sweep          # run once, then exit
"""

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.models import LLMCall, Trace

logger = structlog.get_logger(__name__)


async def sweep_raw_payloads(session: AsyncSession, ttl_days: int) -> int:
    """Null raw_request and raw_response on expired, non-failed LLMCall rows.

    A row is eligible for sweeping when:
      - Its parent trace has status != 'failed'
      - Its parent trace started_at is older than ttl_days days ago

    Args:
        session: Async SQLAlchemy session. Will call commit() before returning.
        ttl_days: Number of days after which raw payloads are nulled.

    Returns:
        Number of LLMCall rows updated.
    """
    cutoff = datetime.now(UTC) - timedelta(days=ttl_days)

    # Subquery: trace ids that are eligible (not failed, old enough)
    eligible_trace_ids = select(Trace.id).where(
        Trace.status != "failed",
        Trace.started_at < cutoff,
    )

    stmt = (
        sa_update(LLMCall)
        .where(
            LLMCall.raw_request.isnot(None),
            LLMCall.trace_id.in_(eligible_trace_ids),
        )
        .values(raw_request=None, raw_response=None)
        .execution_options(synchronize_session=False)
    )

    result = await session.execute(stmt)
    await session.commit()

    rows_swept = result.rowcount
    logger.info(
        "observability_sweep_complete",
        rows_swept=rows_swept,
        ttl_days=ttl_days,
        cutoff=cutoff.isoformat(),
    )
    return rows_swept


async def _sweep_job() -> None:
    """Core sweep job logic (DB init handled by runner)."""
    from src.core.database import get_db_context

    settings = get_settings()
    ttl_days = settings.observability_raw_ttl_days

    async with get_db_context() as session:
        rows_swept = await sweep_raw_payloads(session, ttl_days=ttl_days)
        logger.info("observability_sweep_main_complete", rows_swept=rows_swept)


async def main() -> None:
    """Entry point for cron invocation."""
    from src.jobs.runner import run_tracked

    await run_tracked("observability_sweep", _sweep_job)


if __name__ == "__main__":
    asyncio.run(main())
