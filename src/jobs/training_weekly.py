"""Weekly training summary cron job.

Generates a weekly training summary and syncs it into memory_items
for hybrid search visibility.

Usage:
    python -m src.jobs.training_weekly
"""

from __future__ import annotations

import asyncio

import structlog

from src.core.database import get_db_context

logger = structlog.get_logger(__name__)


async def _run_weekly_sync() -> None:
    """Generate and store the weekly training summary."""
    from src.llm.client import embedding_client
    from src.pipeline.training_sync import sync_weekly_training

    if not embedding_client:
        raise RuntimeError("No embedding client available — VOYAGE_API_KEY not set")

    async with get_db_context() as session:
        await sync_weekly_training(session, embedding_client)


async def main() -> None:
    """Entry point for the weekly training summary job."""
    from src.jobs.runner import run_tracked

    await run_tracked("training_weekly", _run_weekly_sync)


if __name__ == "__main__":
    asyncio.run(main())
