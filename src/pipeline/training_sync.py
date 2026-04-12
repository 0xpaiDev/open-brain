"""Sync weekly training summaries into memory_items for hybrid search visibility.

Follows the same direct-create pattern as pulse_sync.py and todo_sync.py:
creates RawMemory + MemoryItem directly with pre-computed embedding,
bypassing the refinement queue.
"""

from __future__ import annotations

from datetime import UTC, date, timedelta

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import (
    Commitment,
    CommitmentEntry,
    DailyPulse,
    MemoryItem,
    RawMemory,
    StravaActivity,
)
from src.pipeline.embedder import embed_text

logger = structlog.get_logger(__name__)


def _format_commitment_summary(
    commitment_name: str, hits: int, misses: int, pending: int, streak: int
) -> str:
    total = hits + misses + pending
    return (
        f"{commitment_name}: {hits}/{total} days hit, "
        f"{misses} missed, current streak {streak} days"
    )


def _format_training_content(
    week_start: date,
    week_end: date,
    commitment_summaries: list[str],
    strava_summary: str,
    nutrition_summary: str,
) -> str:
    parts = [f"Weekly training summary for {week_start} to {week_end}:"]

    if commitment_summaries:
        parts.append("Commitments: " + "; ".join(commitment_summaries) + ".")

    if strava_summary:
        parts.append(f"Training: {strava_summary}.")

    if nutrition_summary:
        parts.append(f"Nutrition: {nutrition_summary}.")

    if len(parts) == 1:
        parts.append("No training data recorded this week.")

    return " ".join(parts)


async def sync_weekly_training(
    session: AsyncSession,
    voyage_client,
    reference_date: date | None = None,
) -> str | None:
    """Generate and store a weekly training summary as a memory item.

    Args:
        session: Database session
        voyage_client: Voyage embedding client
        reference_date: The end of the week to summarize (default: yesterday).
            The week is reference_date - 6 days through reference_date.

    Returns:
        The memory_item ID if created, None if no data to summarize.
    """
    if reference_date is None:
        reference_date = date.today()

    week_end = reference_date
    week_start = week_end - timedelta(days=6)

    # ── 1. Commitment entries for the week ────────────────────────────────
    commitment_summaries: list[str] = []

    active_commitments = await session.execute(
        select(Commitment).where(Commitment.status == "active")
    )
    for commitment in active_commitments.scalars():
        entries_result = await session.execute(
            select(CommitmentEntry).where(
                and_(
                    CommitmentEntry.commitment_id == commitment.id,
                    CommitmentEntry.entry_date >= week_start,
                    CommitmentEntry.entry_date <= week_end,
                )
            )
        )
        entries = list(entries_result.scalars().all())
        hits = sum(1 for e in entries if e.status == "hit")
        misses = sum(1 for e in entries if e.status == "miss")
        pending = sum(1 for e in entries if e.status == "pending")

        # Compute streak from all entries up to week_end
        all_entries_result = await session.execute(
            select(CommitmentEntry)
            .where(
                and_(
                    CommitmentEntry.commitment_id == commitment.id,
                    CommitmentEntry.entry_date <= week_end,
                )
            )
            .order_by(CommitmentEntry.entry_date.desc())
        )
        streak = 0
        for e in all_entries_result.scalars():
            if e.status == "hit":
                streak += 1
            else:
                break

        if entries:
            commitment_summaries.append(
                _format_commitment_summary(commitment.name, hits, misses, pending, streak)
            )

    # ── 2. Strava activities for the week ─────────────────────────────────
    from datetime import datetime

    week_start_dt = datetime(week_start.year, week_start.month, week_start.day, tzinfo=UTC)
    week_end_dt = datetime(
        week_end.year, week_end.month, week_end.day, 23, 59, 59, tzinfo=UTC
    )

    activities_result = await session.execute(
        select(StravaActivity).where(
            and_(
                StravaActivity.started_at >= week_start_dt,
                StravaActivity.started_at <= week_end_dt,
            )
        )
    )
    activities = list(activities_result.scalars().all())

    strava_summary = ""
    if activities:
        total_distance_km = sum(a.distance_m or 0 for a in activities) / 1000
        total_duration_h = sum(a.duration_s or 0 for a in activities) / 3600
        total_tss = sum(a.tss or 0 for a in activities)
        activity_count = len(activities)

        parts = [f"{activity_count} activities"]
        if total_distance_km > 0:
            parts.append(f"{total_distance_km:.1f} km")
        if total_duration_h > 0:
            parts.append(f"{total_duration_h:.1f} hours")
        if total_tss > 0:
            parts.append(f"{total_tss:.0f} TSS")
        strava_summary = ", ".join(parts)

    # ── 3. Nutrition from daily pulse ─────────────────────────────────────

    pulses_result = await session.execute(
        select(DailyPulse).where(
            and_(
                DailyPulse.pulse_date >= week_start_dt,
                DailyPulse.pulse_date <= week_end_dt,
            )
        )
    )
    pulses = list(pulses_result.scalars().all())

    nutrition_summary = ""
    if pulses:
        clean_days = sum(1 for p in pulses if p.clean_meal is True)
        alcohol_days = sum(1 for p in pulses if p.alcohol is True)
        total_pulse_days = len(pulses)

        parts = []
        if any(p.clean_meal is not None for p in pulses):
            parts.append(f"{clean_days}/{total_pulse_days} clean eating days")
        if any(p.alcohol is not None for p in pulses):
            parts.append(f"{alcohol_days} days with alcohol")
        nutrition_summary = ", ".join(parts)

    # ── 4. Format, embed, and store ───────────────────────────────────────
    content = _format_training_content(
        week_start, week_end, commitment_summaries, strava_summary, nutrition_summary
    )

    embedding = await embed_text(content, voyage_client)

    # Supersede previous week's summary for the same week
    week_start_str = str(week_start)
    existing = await session.execute(
        select(MemoryItem)
        .join(RawMemory, MemoryItem.raw_id == RawMemory.id)
        .where(
            and_(
                RawMemory.metadata_["week_start"].as_string() == week_start_str,
                RawMemory.source == "training-weekly",
                MemoryItem.is_superseded.is_(False),
            )
        )
    )
    for old_item in existing.scalars():
        old_item.is_superseded = True

    # Create raw memory
    raw = RawMemory(
        source="training-weekly",
        raw_text=content,
        metadata_={"week_start": week_start_str, "week_end": str(week_end)},
    )
    session.add(raw)
    await session.flush()

    # Create memory item
    memory_item = MemoryItem(
        raw_id=raw.id,
        type="training_weekly",
        content=content,
        base_importance=0.6,
        embedding=embedding,
        tags=["training:weekly"],
    )
    session.add(memory_item)
    await session.commit()

    logger.info(
        "weekly_training_synced",
        memory_id=str(memory_item.id),
        week_start=week_start_str,
    )
    return str(memory_item.id)
