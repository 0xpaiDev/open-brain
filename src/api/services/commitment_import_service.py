"""Commitment plan import service.

Two-step preview/commit pattern (mirrors import_curriculum in learning_service.py).
Idempotency: SHA-256 of canonicalized payload stored as Commitment.import_hash.
Re-import with same hash returns existing commitment without any writes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from uuid import uuid4

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.commitment_import import CommitmentImportRequest, CommitmentImportResult
from src.core.models import Commitment, CommitmentEntry, CommitmentExercise

logger = structlog.get_logger(__name__)


def _compute_import_hash(payload: CommitmentImportRequest) -> str:
    """Compute SHA-256 of canonicalized payload for idempotency."""
    raw = payload.model_dump(mode="json")
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def import_commitment_plan(
    session: AsyncSession,
    request: CommitmentImportRequest,
    *,
    dry_run: bool,
) -> CommitmentImportResult:
    """Import a training plan as a commitment.

    dry_run=True: validate and return preview with zero DB writes.
    dry_run=False: idempotent commit — same hash returns existing commitment.
    """
    workout_days = [d for d in request.schedule if not d.rest]
    rest_days = [d for d in request.schedule if d.rest]

    # Unique exercise definitions by (name, sets) — same name with different sets = separate rows
    _seen_keys: set[tuple[str, int | None]] = set()
    for day in workout_days:
        for ex_spec in day.exercises:
            _seen_keys.add((ex_spec.name, ex_spec.sets))
    exercise_count = len(_seen_keys)

    if dry_run:
        return CommitmentImportResult(
            dry_run=True,
            workout_days=len(workout_days),
            rest_days=len(rest_days),
            exercise_count=exercise_count,
        )

    # Idempotency check
    import_hash = _compute_import_hash(request)
    existing = await session.execute(
        select(Commitment).where(
            Commitment.import_hash == import_hash,
            Commitment.status != "abandoned",
        )
    )
    existing_commitment = existing.scalar_one_or_none()
    if existing_commitment is not None:
        logger.info(
            "commitment_plan_already_exists",
            commitment_id=str(existing_commitment.id),
            import_hash=import_hash,
        )
        return CommitmentImportResult(
            dry_run=False,
            commitment_id=str(existing_commitment.id),
            already_exists=True,
            workout_days=len(workout_days),
            rest_days=len(rest_days),
            exercise_count=exercise_count,
        )

    # Collect unique exercise definitions by (name, sets) across all workout days.
    # Same exercise with different sets counts as a distinct definition.
    seen_exercises: dict[tuple[str, int | None], CommitmentExercise] = {}
    exercise_order: list[CommitmentExercise] = []
    for day in workout_days:
        for ex_spec in day.exercises:
            key = (ex_spec.name, ex_spec.sets)
            if key not in seen_exercises:
                ex_obj = CommitmentExercise(
                    id=uuid4(),
                    name=ex_spec.name,
                    sets=ex_spec.sets,
                    target=ex_spec.target,
                    metric=ex_spec.metric,
                    progression_metric=ex_spec.progression_metric,
                    position=len(seen_exercises),
                )
                seen_exercises[key] = ex_obj
                exercise_order.append(ex_obj)

    try:
        commitment = Commitment(
            id=uuid4(),
            name=request.name,
            kind="plan",
            cadence="daily",
            daily_target=0,
            exercise=None,
            import_hash=import_hash,
            start_date=request.start_date,
            end_date=request.end_date,
        )
        session.add(commitment)
        await session.flush()

        # Add exercises
        for ex_obj in exercise_order:
            ex_obj.commitment_id = commitment.id
            session.add(ex_obj)

        # Pre-generate workout-day entries only (rest days get no entry)
        for day in workout_days:
            entry = CommitmentEntry(
                commitment_id=commitment.id,
                entry_date=day.day,
            )
            session.add(entry)

        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.error("commitment_plan_import_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Import failed: {exc!s}") from exc

    logger.info(
        "commitment_plan_imported",
        commitment_id=str(commitment.id),
        workout_days=len(workout_days),
        rest_days=len(rest_days),
    )
    return CommitmentImportResult(
        dry_run=False,
        commitment_id=str(commitment.id),
        already_exists=False,
        workout_days=len(workout_days),
        rest_days=len(rest_days),
        exercise_count=exercise_count,
    )
