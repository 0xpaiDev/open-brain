"""Daily importance aggregation job for Open Brain.

Aggregates retrieval_events with exponential decay and writes the result
into memory_items.dynamic_importance.

Algorithm
---------
For every memory_id with ≥1 retrieval event:
    weighted_score = Σ exp(-age_days / half_life_days)
    dynamic_importance = min(1.0, weighted_score / NORMALIZATION_FACTOR)

For every memory_id with zero retrieval events (but dynamic_importance > 0):
    dynamic_importance *= exp(-1 / half_life_days)   # one-day decay step

NORMALIZATION_FACTOR = 5.0: five recent accesses → full dynamic importance.

Settings used
-------------
- importance_recency_half_life_days (default: 30)

Invocation
----------
    python -m src.jobs.importance          # run once, then exit
"""

import asyncio
import math
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import MemoryItem, RetrievalEvent

logger = structlog.get_logger(__name__)

NORMALIZATION_FACTOR = 5.0  # 5 recent accesses → dynamic_importance = 1.0


def _get_settings():
    from src.core import config

    if config.settings is None:
        config.settings = config.Settings()
    return config.settings


def _compute_weighted_score(
    event_times: list[datetime],
    half_life_days: int,
    now: datetime,
) -> float:
    """Sum exp(-age_days / half_life_days) for each retrieval event.

    Args:
        event_times: List of timezone-aware datetimes for each retrieval event.
        half_life_days: Decay half-life in days (from settings).
        now: Reference timestamp (UTC).

    Returns:
        Weighted score ≥ 0.0. Not yet normalized to [0, 1].
    """
    total = 0.0
    for retrieved_at in event_times:
        # Ensure timezone-aware for subtraction
        if retrieved_at.tzinfo is None:
            retrieved_at = retrieved_at.replace(tzinfo=UTC)
        age_days = (now - retrieved_at).total_seconds() / 86400.0
        age_days = max(0.0, age_days)  # guard against clock skew
        total += math.exp(-age_days / half_life_days)
    return total


async def run_importance_job(session: AsyncSession) -> dict[str, int]:
    """Run one pass of the daily importance aggregation job.

    Reads all retrieval_events, groups by memory_id, computes exponentially
    decayed scores, and writes dynamic_importance back to memory_items.

    Args:
        session: Async SQLAlchemy session. Will call commit() before returning.

    Returns:
        Dict with keys "updated" (memories with events) and "decayed"
        (memories whose score was reduced due to zero events).
    """
    settings = _get_settings()
    half_life_days: int = settings.importance_recency_half_life_days
    now = datetime.now(UTC)

    # Load all retrieval events in one query
    events_result = await session.execute(
        select(RetrievalEvent.memory_id, RetrievalEvent.retrieved_at)
    )
    all_events = events_result.all()

    # Group event timestamps by memory_id (str key for safe dict lookup)
    events_by_memory: dict[str, list[datetime]] = {}
    for memory_id, retrieved_at in all_events:
        key = str(memory_id)
        events_by_memory.setdefault(key, []).append(retrieved_at)

    logger.info("importance_job_start", memory_ids_with_events=len(events_by_memory))

    # Load all memory items
    memories_result = await session.execute(select(MemoryItem))
    all_memories = list(memories_result.scalars().all())

    updated = 0
    decayed = 0

    for memory in all_memories:
        memory_id_str = str(memory.id)

        if memory_id_str in events_by_memory:
            weighted = _compute_weighted_score(events_by_memory[memory_id_str], half_life_days, now)
            new_dynamic = min(1.0, weighted / NORMALIZATION_FACTOR)

            logger.debug(
                "importance_job_updated",
                memory_id=memory_id_str,
                old=float(memory.dynamic_importance or 0.0),
                new=new_dynamic,
                event_count=len(events_by_memory[memory_id_str]),
            )
            memory.dynamic_importance = new_dynamic
            updated += 1
        else:
            current = float(memory.dynamic_importance or 0.0)
            if current > 0.0:
                decay_factor = math.exp(-1.0 / half_life_days)
                new_dynamic = max(0.0, current * decay_factor)
                memory.dynamic_importance = new_dynamic
                decayed += 1

    await session.flush()
    await session.commit()

    duration = round((datetime.now(UTC) - now).total_seconds(), 2)
    logger.info(
        "importance_job_complete",
        updated=updated,
        decayed=decayed,
        duration_seconds=duration,
    )
    return {"updated": updated, "decayed": decayed}


async def main() -> None:
    """Entry point for cron invocation.

    Initializes the DB connection pool, runs one job pass, then closes.
    """
    from src.core.database import close_db, get_db_context, init_db

    await init_db()
    try:
        async with get_db_context() as session:
            result = await run_importance_job(session)
            logger.info("importance_job_main_complete", **result)
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
