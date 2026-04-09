#!/usr/bin/env python3
"""One-time backfill: sync all completed/parsed DailyPulse entries into memory_items.

Run via: python -m scripts.backfill_pulse_memories

Only pulses with status "completed" or "parsed" are synced — these are the
terminal success states with actual wellness data. Skipped/expired/sent
pulses have no meaningful content to embed.

Idempotent: if a pulse already has a non-superseded memory_item, the sync
will supersede it and create a fresh one (harmless but redundant).
"""

import asyncio

import structlog
from sqlalchemy import select

from src.core.database import get_db_context, init_db
from src.core.models import DailyPulse
from src.llm.client import embedding_client
from src.pipeline.pulse_sync import sync_pulse_to_memory

logger = structlog.get_logger(__name__)

SYNC_STATUSES = {"completed", "parsed"}


async def backfill() -> None:
    await init_db()

    if not embedding_client:
        logger.error("backfill_no_embedding_client")
        return

    failed = 0
    total = 0

    async with get_db_context() as session:
        result = await session.execute(
            select(DailyPulse)
            .where(DailyPulse.status.in_(SYNC_STATUSES))
            .order_by(DailyPulse.pulse_date)
        )
        for pulse in result.scalars():
            total += 1
            try:
                await sync_pulse_to_memory(session, pulse, embedding_client)
            except Exception:
                failed += 1
                logger.warning("backfill_pulse_failed", pulse_id=str(pulse.id), exc_info=True)

    logger.info("backfill_complete", total=total, failed=failed)


if __name__ == "__main__":
    asyncio.run(backfill())
