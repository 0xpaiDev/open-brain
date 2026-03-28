"""Job runner wrapper — tracks execution in job_runs and alerts on failure.

Wraps each scheduled job with:
1. A JobRun record (started_at, finished_at, status, duration)
2. Discord DM alert to the pulse user on failure

Usage:
    from src.jobs.runner import run_tracked

    async def main() -> None:
        await run_tracked("pulse", my_async_job_function)
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from src.core.config import get_settings
from src.core.database import close_db, get_db_context, init_db
from src.core.models import JobRun

logger = structlog.get_logger(__name__)


async def _send_discord_alert(job_name: str, error_msg: str, started_at: datetime) -> None:
    """Send a failure alert via Discord DM to the pulse user."""
    settings = get_settings()
    bot_token = settings.discord_bot_token.get_secret_value()
    user_id = settings.discord_pulse_user_id
    if not bot_token or not user_id:
        logger.warning("discord_alert_skipped", reason="no bot token or user id")
        return

    from src.jobs.pulse import get_or_create_dm_channel, send_dm_via_rest

    message = (
        f"**Job failed: `{job_name}`**\n"
        f"Error: {error_msg[:500]}\n"
        f"Time: {started_at.strftime('%Y-%m-%d %H:%M UTC')}"
    )

    async with httpx.AsyncClient(timeout=10.0) as http:
        try:
            channel_id = await get_or_create_dm_channel(http, bot_token, user_id)
            await send_dm_via_rest(http, bot_token, channel_id, content=message)
            logger.info("discord_alert_sent", job_name=job_name)
        except Exception:
            logger.exception("discord_alert_failed", job_name=job_name)


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
    await init_db()
    started_at = datetime.now(UTC)
    status = "success"
    error_msg: str | None = None

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

        # Execute the actual job
        try:
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

    # Send alert outside the DB context (best-effort)
    if status == "failed" and error_msg:
        try:
            await _send_discord_alert(job_name, error_msg, started_at)
        except Exception:
            logger.exception("discord_alert_outer_failed", job_name=job_name)
