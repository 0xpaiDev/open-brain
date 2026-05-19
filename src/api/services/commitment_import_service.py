"""Commitment plan import service.

Two-step preview/commit pattern (mirrors import_curriculum in learning_service.py).
Idempotency: SHA-256 of canonicalized payload stored as Commitment.import_hash.
Re-import with same hash returns existing commitment without any writes.

Step 1 (dry_run=True):  validate + return unknown_exercises list (no DB writes)
Step 2 (dry_run=False): resolve exercises → atomic commit of Commitment +
                        CommitmentExercise + CommitmentEntry + CommitmentEntryExercise
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

from src.api.schemas.commitment_import import (
    CommitmentImportRequest,
    CommitmentImportResult,
    UnknownExercise,
)
from src.core.models import (
    Commitment,
    CommitmentEntry,
    CommitmentEntryExercise,
    CommitmentExercise,
    Exercise,
)

logger = structlog.get_logger(__name__)


def _normalise(name: str) -> str:
    """Normalise an exercise name for library dedup."""
    return name.strip().lower()


def _compute_import_hash(payload: CommitmentImportRequest) -> str:
    """Compute SHA-256 of canonicalized payload for idempotency."""
    # Exclude resolved_exercises from hash — same schedule should be idempotent
    raw = payload.model_dump(mode="json")
    raw.pop("resolved_exercises", None)
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _find_unknown_exercises(
    session: AsyncSession,
    workout_days: list,
) -> list[UnknownExercise]:
    """Return exercise specs whose normalised names are not in the exercises library."""
    # Collect unique (name, sets, target, metric, progression_metric) from all workout days
    seen: dict[str, UnknownExercise] = {}
    for day in workout_days:
        for ex_spec in day.exercises:
            key = _normalise(ex_spec.name)
            if key not in seen:
                seen[key] = UnknownExercise(
                    name=ex_spec.name,
                    sets=ex_spec.sets,
                    target=ex_spec.target,
                    metric=ex_spec.metric,
                    progression_metric=ex_spec.progression_metric,
                )

    if not seen:
        return []

    # Query library for existing normalised names
    result = await session.execute(
        select(Exercise.name).where(Exercise.name.in_(list(seen.keys())))
    )
    existing_names = {row[0] for row in result.all()}
    return [ue for key, ue in seen.items() if key not in existing_names]


async def import_commitment_plan(
    session: AsyncSession,
    request: CommitmentImportRequest,
    *,
    dry_run: bool,
) -> CommitmentImportResult:
    """Import a training plan as a commitment.

    dry_run=True: validate + return unknown_exercises (zero DB writes).
    dry_run=False: idempotent commit — same schedule hash returns existing commitment.
    """
    workout_days = [d for d in request.schedule if not d.rest]
    rest_days = [d for d in request.schedule if d.rest]

    # Unique exercise definitions by (name, sets)
    _seen_keys: set[tuple[str, int | None]] = set()
    for day in workout_days:
        for ex_spec in day.exercises:
            _seen_keys.add((ex_spec.name, ex_spec.sets))
    exercise_count = len(_seen_keys)

    unknown_exercises = await _find_unknown_exercises(session, workout_days)

    if dry_run:
        return CommitmentImportResult(
            dry_run=True,
            workout_days=len(workout_days),
            rest_days=len(rest_days),
            exercise_count=exercise_count,
            unknown_exercises=unknown_exercises,
        )

    # Validate: all unknowns must be resolved before commit
    if unknown_exercises:
        resolved_names = {_normalise(r.name) for r in request.resolved_exercises}
        still_unknown = [ue for ue in unknown_exercises if _normalise(ue.name) not in resolved_names]
        if still_unknown:
            unresolved = [ue.name for ue in still_unknown]
            raise HTTPException(
                status_code=422,
                detail=f"Unresolved exercises must be resolved before import: {unresolved}",
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

    # Build resolved_exercises lookup: normalised_name → Exercise DB row
    resolved_lookup: dict[str, Exercise] = {}

    # First: handle matched-to-existing
    for resolved in request.resolved_exercises:
        if resolved.exercise_id is not None:
            lib_ex = await session.get(Exercise, resolved.exercise_id)
            if lib_ex is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"Exercise library entry not found: {resolved.exercise_id}",
                )
            resolved_lookup[_normalise(resolved.name)] = lib_ex

    # Second: create new library entries
    for resolved in request.resolved_exercises:
        if resolved.exercise_id is None:
            norm = _normalise(resolved.name)
            if norm not in resolved_lookup:
                display = resolved.display_name or resolved.name
                lib_ex = Exercise(id=uuid4(), name=norm, display_name=display)
                session.add(lib_ex)
                resolved_lookup[norm] = lib_ex

    # Also resolve exercises already in the library (not in resolved_exercises)
    for day in workout_days:
        for ex_spec in day.exercises:
            norm = _normalise(ex_spec.name)
            if norm not in resolved_lookup:
                result = await session.execute(
                    select(Exercise).where(Exercise.name == norm)
                )
                lib_ex = result.scalar_one_or_none()
                if lib_ex is not None:
                    resolved_lookup[norm] = lib_ex

    await session.flush()

    # Collect unique exercise definitions by (name, sets) across all workout days
    seen_exercises: dict[tuple[str, int | None], CommitmentExercise] = {}
    exercise_order: list[CommitmentExercise] = []
    for day in workout_days:
        for ex_spec in day.exercises:
            key = (ex_spec.name, ex_spec.sets)
            if key not in seen_exercises:
                norm = _normalise(ex_spec.name)
                lib_ex = resolved_lookup.get(norm)
                ex_obj = CommitmentExercise(
                    id=uuid4(),
                    name=ex_spec.name,
                    sets=ex_spec.sets,
                    target=ex_spec.target,
                    metric=ex_spec.metric,
                    progression_metric=ex_spec.progression_metric,
                    position=len(seen_exercises),
                    exercise_id=lib_ex.id if lib_ex else None,
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

        for ex_obj in exercise_order:
            ex_obj.commitment_id = commitment.id
            session.add(ex_obj)
        await session.flush()

        # Pre-generate workout-day entries + per-day exercise assignments
        for day in workout_days:
            entry = CommitmentEntry(
                id=uuid4(),
                commitment_id=commitment.id,
                entry_date=day.day,
            )
            session.add(entry)
            await session.flush()

            for ex_spec in day.exercises:
                key = (ex_spec.name, ex_spec.sets)
                ex_obj = seen_exercises[key]
                junction = CommitmentEntryExercise(
                    id=uuid4(),
                    commitment_id=commitment.id,
                    entry_id=entry.id,
                    exercise_id=ex_obj.id,
                )
                session.add(junction)

        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
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
