"""Schedule service: read and mutate per-day exercise assignments for plan commitments."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import structlog
from fastapi import HTTPException
from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import Commitment, CommitmentEntry, CommitmentEntryExercise, CommitmentExercise

logger = structlog.get_logger(__name__)


async def get_schedule(
    session: AsyncSession,
    commitment_id: str,
) -> dict:
    """Return full day-by-day schedule for a plan commitment.

    Includes all days from start_date to end_date. Rest days have no entry_id
    and status="rest". Workout days include their assigned exercises.
    """
    commitment = await session.get(Commitment, commitment_id)
    if commitment is None:
        raise HTTPException(status_code=404, detail="Commitment not found")
    if commitment.kind != "plan":
        raise HTTPException(status_code=400, detail="Schedule is only available for plan commitments")

    # Load all entries for this commitment
    entries_result = await session.execute(
        select(CommitmentEntry)
        .where(CommitmentEntry.commitment_id == commitment_id)
        .order_by(CommitmentEntry.entry_date)
    )
    entries_by_date: dict[date, CommitmentEntry] = {
        e.entry_date: e for e in entries_result.scalars().all()
    }

    # Load all entry_exercises for this commitment
    junction_result = await session.execute(
        select(CommitmentEntryExercise, CommitmentExercise)
        .join(CommitmentExercise, CommitmentEntryExercise.exercise_id == CommitmentExercise.id)
        .where(CommitmentEntryExercise.commitment_id == commitment_id)
    )
    exercises_by_entry: dict[str, list[dict]] = {}
    for junction, ex in junction_result.all():
        entry_key = str(junction.entry_id)
        exercises_by_entry.setdefault(entry_key, []).append({
            "exercise_id": str(ex.id),
            "name": ex.name,
            "sets": ex.sets,
            "target": ex.target,
            "metric": ex.metric,
        })

    # Build day list
    days = []
    current = commitment.start_date
    while current <= commitment.end_date:
        entry = entries_by_date.get(current)
        if entry is not None:
            days.append({
                "entry_id": str(entry.id),
                "date": str(current),
                "status": entry.status,
                "exercises": exercises_by_entry.get(str(entry.id), []),
            })
        else:
            days.append({
                "entry_id": None,
                "date": str(current),
                "status": "rest",
                "exercises": [],
            })
        current += timedelta(days=1)

    return {"commitment_id": str(commitment_id), "days": days}


async def swap_day(
    session: AsyncSession,
    commitment_id: str,
    target_date: date,
    action: str,
    exercise_ids: list[str],
) -> None:
    """Flip a day between rest and workout.

    to_workout: creates CommitmentEntry + CommitmentEntryExercise rows.
    to_rest: deletes the CommitmentEntry (cascades to entry_exercises + pending logs).
             Refuses if entry status is hit or miss.
    """
    commitment = await session.get(Commitment, commitment_id)
    if commitment is None:
        raise HTTPException(status_code=404, detail="Commitment not found")
    if commitment.kind != "plan":
        raise HTTPException(status_code=400, detail="Day swap is only available for plan commitments")
    if not (commitment.start_date <= target_date <= commitment.end_date):
        raise HTTPException(status_code=400, detail="Date is outside commitment range")

    entry_result = await session.execute(
        select(CommitmentEntry).where(
            and_(
                CommitmentEntry.commitment_id == commitment_id,
                CommitmentEntry.entry_date == target_date,
            )
        )
    )
    entry = entry_result.scalar_one_or_none()

    if action == "to_workout":
        if entry is not None:
            raise HTTPException(status_code=400, detail="Day is already a workout day")
        if not exercise_ids:
            raise HTTPException(status_code=400, detail="exercise_ids required when converting to workout day")

        new_entry = CommitmentEntry(
            id=uuid4(),
            commitment_id=commitment_id,
            entry_date=target_date,
        )
        session.add(new_entry)
        await session.flush()

        for ex_id in exercise_ids:
            ex = await session.get(CommitmentExercise, ex_id)
            if ex is None or str(ex.commitment_id) != str(commitment_id):
                raise HTTPException(status_code=400, detail=f"Exercise {ex_id} not found in this commitment")
            junction = CommitmentEntryExercise(
                id=uuid4(),
                commitment_id=commitment_id,
                entry_id=new_entry.id,
                exercise_id=ex_id,
            )
            session.add(junction)

    elif action == "to_rest":
        if entry is None:
            raise HTTPException(status_code=400, detail="Day is already a rest day")
        if entry.status in ("hit", "miss"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot convert a {entry.status} day to rest",
            )
        await session.delete(entry)

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    await session.commit()
    logger.info("day_swapped", commitment_id=str(commitment_id), date=str(target_date), action=action)


async def update_day_exercises(
    session: AsyncSession,
    commitment_id: str,
    entry_id: str,
    exercise_ids: list[str],
) -> None:
    """Replace all exercise assignments for an existing workout day."""
    entry = await session.get(CommitmentEntry, entry_id)
    if entry is None or str(entry.commitment_id) != str(commitment_id):
        raise HTTPException(status_code=404, detail="Entry not found")

    # Delete existing junction rows for this entry
    await session.execute(
        delete(CommitmentEntryExercise).where(CommitmentEntryExercise.entry_id == entry_id)
    )

    # Insert new ones
    for ex_id in exercise_ids:
        ex = await session.get(CommitmentExercise, ex_id)
        if ex is None or str(ex.commitment_id) != str(commitment_id):
            raise HTTPException(status_code=400, detail=f"Exercise {ex_id} not found in this commitment")
        junction = CommitmentEntryExercise(
            id=uuid4(),
            commitment_id=commitment_id,
            entry_id=entry_id,
            exercise_id=ex_id,
        )
        session.add(junction)

    await session.commit()
