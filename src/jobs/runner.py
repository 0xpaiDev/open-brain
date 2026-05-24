"""Job runner wrapper — tracks execution in job_runs and logs on failure.

Wraps each scheduled job with:
1. A JobRun record (started_at, finished_at, status, duration)
2. An observability Trace (Execution Explorer Phase 2)

Usage:
    from src.jobs.runner import run_tracked

    async def main() -> None:
        await run_tracked("pulse", my_async_job_function)
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

import structlog

from src.core.database import close_db, get_db_context, init_db
from src.core.logging import configure_logging
from src.core.models import JobRun
from src.observability import start_trace
from src.observability.rerun import register_rerun_handler

logger = structlog.get_logger(__name__)

# Registry mapping job_name → job_fn for rerun support
_JOB_REGISTRY: dict[str, Callable] = {}


async def run_tracked(
    job_name: str,
    job_fn: Callable[..., Coroutine[Any, Any, Any]],
    *args: Any,
    **kwargs: Any,
) -> None:
    """Run a job function with DB tracking and Discord failure alerts.

    Initializes the DB, records a JobRun, executes job_fn(*args, **kwargs),
    updates the run record, and sends a Discord alert on failure.

    Args:
        job_name: Short identifier (e.g. "pulse", "importance", "synthesis").
        job_fn: The async function to execute.
        *args, **kwargs: Passed through to job_fn.
    """
    from src.core.config import get_settings

    configure_logging(get_settings().log_level)
    await init_db()
    started_at = datetime.now(UTC)
    status = "success"
    error_msg: str | None = None

    # Register for rerun support (last-write-wins; safe for repeated calls)
    _JOB_REGISTRY[job_name] = job_fn

    try:
        # Record job start
        async with get_db_context() as session:
            run = JobRun(
                job_name=job_name,
                started_at=started_at,
                status="running",
            )
            session.add(run)
            await session.flush()
            await session.commit()
            run_id = run.id

        # Execute the actual job, wrapped in an observability trace
        try:
            async with start_trace(
                trigger_type="cron",
                trigger_name=job_name,
                trigger_metadata={"job_name": job_name},
            ):
                await job_fn(*args, **kwargs)
        except Exception as exc:
            status = "failed"
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.exception("job_failed", job_name=job_name, error=error_msg)

        # Update job run record
        finished_at = datetime.now(UTC)
        duration = (finished_at - started_at).total_seconds()
        async with get_db_context() as session:
            run_record = await session.get(JobRun, run_id)
            if run_record:
                run_record.finished_at = finished_at
                run_record.status = status
                run_record.error_message = error_msg
                run_record.duration_seconds = round(duration, 2)
                await session.flush()
                await session.commit()

        logger.info(
            "job_run_complete",
            job_name=job_name,
            status=status,
            duration_seconds=round(duration, 2),
        )

    except Exception:
        # If tracking itself fails, log but don't crash
        logger.exception("job_tracking_failed", job_name=job_name)

    finally:
        await close_db()


async def _handle_cron_rerun(trace: Any) -> None:
    """Rerun handler for cron-triggered jobs.

    Looks up the original job function from _JOB_REGISTRY by trigger_name
    and re-invokes run_tracked. The dispatch_rerun wrapper already opens the
    new Trace, so run_tracked will open a nested one — that's acceptable.
    """
    job_fn = _JOB_REGISTRY.get(trace.trigger_name)
    if job_fn is None:
        raise ValueError(f"No job registered for rerun: {trace.trigger_name!r}")
    await run_tracked(trace.trigger_name, job_fn)


register_rerun_handler("cron", _handle_cron_rerun)

