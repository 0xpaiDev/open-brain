"""Commitment challenge endpoints.

POST   /v1/commitments                                       — create commitment + pre-generate entries
POST   /v1/commitments/import?dry_run=...                    — plan import (preview/commit)
GET    /v1/commitments                                       — list (default: active only, ?status=all)
GET    /v1/commitments/{id}                                  — single commitment with entries + streak info
PATCH  /v1/commitments/{id}                                  — update (abandon, etc.)
POST   /v1/commitments/{id}/log                              — log count for today (single kind only)
POST   /v1/commitments/{id}/exercises/{exercise_id}/log      — per-exercise log (routine/plan kinds)
DELETE /v1/commitments/{id}/exercises/{exercise_id}/logs/{log_id} — soft-delete a log
GET    /v1/commitments/{id}/progression                      — per-exercise progression series
"""

from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import commitments_limit, limiter
from src.core.database import get_db
from src.core.models import Commitment, CommitmentEntry, CommitmentExercise, CommitmentExerciseLog

logger = structlog.get_logger(__name__)

router = APIRouter()

_VALID_STATUSES = {"active", "completed", "abandoned"}
_VALID_METRICS = {"reps", "minutes", "tss", "seconds"}
_VALID_CADENCES = {"daily", "aggregate"}
_VALID_TARGET_KEYS = {"km", "tss", "minutes", "hours", "elevation_m"}
_VALID_EXERCISE_METRICS = {"reps", "minutes", "kg", "seconds"}
_VALID_KINDS = {"single", "routine", "plan"}


# ── Pydantic models ────────────────────────────────────────────────────────────


class ExerciseSpec(BaseModel):
    """Exercise definition for routine kind commitments."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=100)
    target: int = Field(..., gt=0)
    metric: str = "reps"
    progression_metric: str = "reps"

    @field_validator("metric", "progression_metric")
    @classmethod
    def validate_exercise_metric(cls, v: str) -> str:
        if v not in _VALID_EXERCISE_METRICS:
            raise ValueError(f"metric must be one of {sorted(_VALID_EXERCISE_METRICS)}")
        return v


class CommitmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    exercise: str | None = Field(None, min_length=1, max_length=100)
    kind: str = "single"
    cadence: str = "daily"
    daily_target: int = Field(0, ge=0)
    metric: str = "reps"
    targets: dict[str, float] | None = None
    exercises: list[ExerciseSpec] | None = None
    start_date: date
    end_date: date

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, v: str) -> str:
        if v not in _VALID_KINDS:
            raise ValueError(f"kind must be one of {sorted(_VALID_KINDS)}")
        return v

    @field_validator("cadence")
    @classmethod
    def validate_cadence(cls, v: str) -> str:
        if v not in _VALID_CADENCES:
            raise ValueError(f"cadence must be one of {sorted(_VALID_CADENCES)}")
        return v

    @field_validator("metric")
    @classmethod
    def validate_metric(cls, v: str) -> str:
        if v not in _VALID_METRICS:
            raise ValueError(f"metric must be one of {sorted(_VALID_METRICS)}")
        return v

    @field_validator("end_date")
    @classmethod
    def validate_end_after_start(cls, v: date, info) -> date:
        start = info.data.get("start_date")
        if start and v < start:
            raise ValueError("end_date must be on or after start_date")
        return v

    @model_validator(mode="after")
    def validate_kind_fields(self) -> CommitmentCreate:
        if self.kind == "single":
            if self.cadence == "daily" and self.daily_target <= 0:
                raise ValueError("daily_target must be > 0 for daily single commitments")
            elif self.cadence == "aggregate":
                if not self.targets or len(self.targets) == 0:
                    raise ValueError("aggregate commitments require at least one target")
                for key, val in self.targets.items():
                    if key not in _VALID_TARGET_KEYS:
                        raise ValueError(f"target key must be one of {sorted(_VALID_TARGET_KEYS)}")
                    if val <= 0:
                        raise ValueError("target values must be positive")
        elif self.kind == "routine":
            if not self.exercises or len(self.exercises) == 0:
                raise ValueError("routine commitments require at least 1 exercise")
            if len(self.exercises) > 5:
                raise ValueError("routine commitments support at most 5 exercises")
        elif self.kind == "plan":
            raise ValueError("plan commitments must be created via POST /v1/commitments/import")
        return self


class CommitmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(_VALID_STATUSES)}")
        return v


class LogCount(BaseModel):
    count: int = Field(..., gt=0)


class ExerciseLogCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sets: int | None = Field(None, ge=1)
    reps: int | None = Field(None, ge=0)
    weight_kg: float | None = Field(None, ge=0)
    duration_minutes: float | None = Field(None, ge=0)
    notes: str | None = Field(None, max_length=500)


class EntryResponse(BaseModel):
    id: str
    commitment_id: str
    entry_date: date
    logged_count: int
    status: str
    created_at: str
    updated_at: str


class ExerciseResponse(BaseModel):
    id: str
    commitment_id: str
    name: str
    sets: int | None = None
    target: int
    metric: str
    progression_metric: str
    position: int
    logged_today: bool = False


class ExerciseLogResponse(BaseModel):
    id: str
    commitment_id: str
    exercise_id: str
    log_date: date
    sets: int | None
    reps: int | None
    weight_kg: float | None
    duration_minutes: float | None
    notes: str | None
    created_at: str


class ProgressionPoint(BaseModel):
    date: date
    value: float
    metric: str


class ExerciseProgressionResponse(BaseModel):
    exercise_id: str
    exercise_name: str
    points: list[ProgressionPoint]


class CommitmentResponse(BaseModel):
    id: str
    name: str
    exercise: str | None
    daily_target: int
    metric: str
    cadence: str = "daily"
    kind: str = "single"
    targets: dict[str, float] | None = None
    progress: dict[str, float] | None = None
    pace: dict[str, float] | None = None
    start_date: date
    end_date: date
    status: str
    created_at: str
    updated_at: str
    current_streak: int = 0
    goal_reached: bool | None = None
    entries: list[EntryResponse] = []
    exercises: list[ExerciseResponse] = []


class CommitmentListResponse(BaseModel):
    commitments: list[CommitmentResponse]
    total: int


# ── Helpers ────────────────────────────────────────────────────────────────────


def _get_today() -> date:
    """Return today's date in the configured pulse timezone."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from src.core.config import get_settings

    settings = get_settings()
    try:
        tz = ZoneInfo(settings.pulse_timezone)
    except (ZoneInfoNotFoundError, AttributeError):
        tz = ZoneInfo("UTC")

    from datetime import datetime

    return datetime.now(tz).date()


def _compute_streak(entries: list[CommitmentEntry], today: date) -> int:
    """Compute the current consecutive hit streak ending at today (or yesterday)."""
    sorted_entries = sorted(entries, key=lambda e: e.entry_date, reverse=True)
    streak = 0
    for entry in sorted_entries:
        if entry.entry_date > today:
            continue
        if entry.status == "hit":
            streak += 1
        elif entry.status == "pending" and entry.entry_date == today:
            # Today's still pending — skip it, count streak from yesterday
            continue
        else:
            break
    return streak


def _entry_to_response(entry: CommitmentEntry) -> EntryResponse:
    return EntryResponse(
        id=str(entry.id),
        commitment_id=str(entry.commitment_id),
        entry_date=entry.entry_date,
        logged_count=entry.logged_count,
        status=entry.status,
        created_at=str(entry.created_at),
        updated_at=str(entry.updated_at),
    )


def _compute_pace(
    targets: dict[str, float] | None,
    progress: dict[str, float] | None,
    start_date: date,
    end_date: date,
    today: date,
) -> dict[str, float] | None:
    """Compute pace ratios for an aggregate commitment."""
    if not targets:
        return None

    total_days = (end_date - start_date).days + 1
    elapsed_days = min((today - start_date).days + 1, total_days)

    if elapsed_days <= 0:
        # Commitment hasn't started
        return {**dict.fromkeys(targets, 0.0), "overall": 0.0}

    elapsed_fraction = elapsed_days / total_days
    prog = progress or {}

    pace: dict[str, float] = {}
    for metric, target in targets.items():
        actual = prog.get(metric, 0.0)
        if target > 0 and elapsed_fraction > 0:
            pace[metric] = round((actual / target) / elapsed_fraction, 2)
        else:
            pace[metric] = 0.0

    # Overall = minimum pace (conservative — weakest metric)
    pace["overall"] = min(pace.values()) if pace else 0.0
    return pace


def _compute_goal_reached(
    commitment: Commitment, entries: list[CommitmentEntry], today: date
) -> bool | None:
    """Return whether the commitment's goal was achieved.

    None while the commitment is still in progress (period hasn't ended and
    status is active). Once the period has ended — or the status has been
    flipped to completed by the cron — returns True/False so the UI can
    distinguish a successful finish from "not reached".
    """
    period_over = commitment.end_date < today or commitment.status != "active"
    if not period_over:
        return None

    if commitment.cadence == "aggregate":
        targets = commitment.targets or {}
        if not targets:
            return None
        progress = commitment.progress or {}
        return all(progress.get(metric, 0.0) >= target for metric, target in targets.items())

    # Daily: goal reached means every entry in range hit the target.
    in_range = [e for e in entries if commitment.start_date <= e.entry_date <= commitment.end_date]
    if not in_range:
        return None
    return all(e.status == "hit" for e in in_range)


def _exercise_to_response(ex: CommitmentExercise, logged_today: bool = False) -> ExerciseResponse:
    return ExerciseResponse(
        id=str(ex.id),
        commitment_id=str(ex.commitment_id),
        name=ex.name,
        sets=ex.sets,
        target=ex.target,
        metric=ex.metric,
        progression_metric=ex.progression_metric,
        position=ex.position,
        logged_today=logged_today,
    )


def _log_to_response(log: CommitmentExerciseLog) -> ExerciseLogResponse:
    return ExerciseLogResponse(
        id=str(log.id),
        commitment_id=str(log.commitment_id),
        exercise_id=str(log.exercise_id),
        log_date=log.log_date,
        sets=log.sets,
        reps=log.reps,
        weight_kg=log.weight_kg,
        duration_minutes=log.duration_minutes,
        notes=log.notes,
        created_at=str(log.created_at),
    )


def _commitment_to_response(
    commitment: Commitment,
    entries: list[CommitmentEntry] | None = None,
    today: date | None = None,
    exercises: list[CommitmentExercise] | None = None,
    logged_exercise_ids_today: set[str] | None = None,
) -> CommitmentResponse:
    entry_list = entries or []
    t = today or _get_today()
    ex_list = exercises or []
    logged_ids = logged_exercise_ids_today or set()

    pace = None
    if commitment.cadence == "aggregate":
        pace = _compute_pace(
            commitment.targets, commitment.progress,
            commitment.start_date, commitment.end_date, t,
        )

    return CommitmentResponse(
        id=str(commitment.id),
        name=commitment.name,
        exercise=commitment.exercise,
        daily_target=commitment.daily_target,
        metric=commitment.metric,
        cadence=commitment.cadence,
        kind=commitment.kind or "single",
        targets=commitment.targets,
        progress=commitment.progress or ({} if commitment.cadence == "aggregate" else None),
        pace=pace,
        start_date=commitment.start_date,
        end_date=commitment.end_date,
        status=commitment.status,
        created_at=str(commitment.created_at),
        updated_at=str(commitment.updated_at),
        current_streak=_compute_streak(entry_list, t) if commitment.cadence == "daily" else 0,
        goal_reached=_compute_goal_reached(commitment, entry_list, t),
        entries=[_entry_to_response(e) for e in entry_list],
        exercises=[_exercise_to_response(ex, str(ex.id) in logged_ids) for ex in ex_list],
    )


# ── POST /v1/commitments ──────────────────────────────────────────────────────


async def _check_and_flip_entry(
    session: AsyncSession,
    commitment_id,
    today: date,
) -> None:
    """After a log insert, check if all exercises are done today and flip entry to hit."""
    total_exercises_result = await session.execute(
        select(CommitmentExercise).where(CommitmentExercise.commitment_id == commitment_id)
    )
    total_exercises = list(total_exercises_result.scalars().all())
    if not total_exercises:
        return

    logged_today_result = await session.execute(
        select(CommitmentExerciseLog.exercise_id).where(
            and_(
                CommitmentExerciseLog.commitment_id == commitment_id,
                CommitmentExerciseLog.log_date == today,
                CommitmentExerciseLog.deleted_at.is_(None),
            )
        ).distinct()
    )
    logged_exercise_ids = {str(row[0]) for row in logged_today_result.all()}
    total_ids = {str(ex.id) for ex in total_exercises}

    entry_result = await session.execute(
        select(CommitmentEntry).where(
            and_(
                CommitmentEntry.commitment_id == commitment_id,
                CommitmentEntry.entry_date == today,
            )
        )
    )
    entry = entry_result.scalar_one_or_none()
    if entry is None:
        return

    if total_ids <= logged_exercise_ids:
        entry.status = "hit"
    else:
        if entry.status == "hit":
            entry.status = "pending"


@router.post("/v1/commitments/import", status_code=status.HTTP_201_CREATED)
@limiter.limit(commitments_limit)
async def import_commitment_plan(
    request: Request,
    dry_run: bool = Query(...),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Import a training plan. dry_run=true returns preview with zero DB writes."""
    from src.api.schemas.commitment_import import CommitmentImportRequest
    from src.api.services.commitment_import_service import import_commitment_plan as _import

    try:
        body_json = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid JSON body")

    try:
        plan_request = CommitmentImportRequest.model_validate(body_json)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    result = await _import(session, plan_request, dry_run=dry_run)
    response_status = status.HTTP_200_OK if (dry_run or result.already_exists) else status.HTTP_201_CREATED
    from fastapi.responses import JSONResponse
    return JSONResponse(content=result.model_dump(), status_code=response_status)


@router.post("/v1/commitments", response_model=CommitmentResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(commitments_limit)
async def create_commitment(
    request: Request,
    body: CommitmentCreate,
    session: AsyncSession = Depends(get_db),
) -> CommitmentResponse:
    """Create a commitment and pre-generate daily entries (for daily cadence)."""
    commitment = Commitment(
        name=body.name,
        exercise=body.exercise if body.kind == "single" else None,
        daily_target=body.daily_target if body.kind == "single" else 0,
        metric=body.metric,
        cadence=body.cadence,
        kind=body.kind,
        targets=body.targets if body.cadence == "aggregate" else None,
        progress={} if body.cadence == "aggregate" else None,
        start_date=body.start_date,
        end_date=body.end_date,
    )
    session.add(commitment)
    await session.flush()

    # Create exercise definitions for routine kind
    ex_objects: list[CommitmentExercise] = []
    if body.kind == "routine" and body.exercises:
        for i, ex_spec in enumerate(body.exercises):
            ex = CommitmentExercise(
                commitment_id=commitment.id,
                name=ex_spec.name,
                target=ex_spec.target,
                metric=ex_spec.metric,
                progression_metric=ex_spec.progression_metric,
                position=i,
            )
            session.add(ex)
            ex_objects.append(ex)

    # Pre-generate entries only for daily cadence (all days for single/routine)
    entries = []
    if body.cadence == "daily":
        current = body.start_date
        while current <= body.end_date:
            entry = CommitmentEntry(
                commitment_id=commitment.id,
                entry_date=current,
            )
            session.add(entry)
            entries.append(entry)
            current += timedelta(days=1)

    await session.commit()
    await session.refresh(commitment)
    for entry in entries:
        await session.refresh(entry)
    for ex in ex_objects:
        await session.refresh(ex)

    logger.info(
        "commitment_created",
        commitment_id=str(commitment.id),
        name=commitment.name,
        kind=body.kind,
        cadence=body.cadence,
        days=len(entries),
    )
    return _commitment_to_response(commitment, entries, _get_today(), ex_objects)


# ── GET /v1/commitments ───────────────────────────────────────────────────────


@router.get("/v1/commitments", response_model=CommitmentListResponse)
@limiter.limit(commitments_limit)
async def list_commitments(
    request: Request,
    status_filter: str = Query("active", alias="status"),
    session: AsyncSession = Depends(get_db),
) -> CommitmentListResponse:
    """List commitments. Default: active only. Use ?status=all for all."""
    today = _get_today()
    stmt = select(Commitment).order_by(Commitment.created_at.desc())
    if status_filter != "all":
        stmt = stmt.where(Commitment.status == status_filter)
        stmt = stmt.where(Commitment.start_date <= today)

    result = await session.execute(stmt)
    commitments = list(result.scalars().all())
    responses = []
    for c in commitments:
        entries_result = await session.execute(
            select(CommitmentEntry)
            .where(CommitmentEntry.commitment_id == c.id)
            .order_by(CommitmentEntry.entry_date)
        )
        entries = list(entries_result.scalars().all())
        exercises_result = await session.execute(
            select(CommitmentExercise)
            .where(CommitmentExercise.commitment_id == c.id)
            .order_by(CommitmentExercise.position)
        )
        exercises = list(exercises_result.scalars().all())
        logged_ids: set[str] = set()
        if exercises:
            logs_result = await session.execute(
                select(CommitmentExerciseLog.exercise_id).where(
                    and_(
                        CommitmentExerciseLog.commitment_id == c.id,
                        CommitmentExerciseLog.log_date == today,
                        CommitmentExerciseLog.deleted_at.is_(None),
                    )
                ).distinct()
            )
            logged_ids = {str(row[0]) for row in logs_result.all()}
        responses.append(_commitment_to_response(c, entries, today, exercises, logged_ids))

    return CommitmentListResponse(commitments=responses, total=len(responses))


# ── GET /v1/commitments/{id} ──────────────────────────────────────────────────


@router.get("/v1/commitments/{commitment_id}", response_model=CommitmentResponse)
@limiter.limit(commitments_limit)
async def get_commitment(
    request: Request,
    commitment_id: _uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> CommitmentResponse:
    """Get a single commitment with all entries and streak info."""
    commitment = await session.get(Commitment, commitment_id)
    if commitment is None:
        raise HTTPException(status_code=404, detail="Commitment not found")

    today = _get_today()
    entries_result = await session.execute(
        select(CommitmentEntry)
        .where(CommitmentEntry.commitment_id == commitment.id)
        .order_by(CommitmentEntry.entry_date)
    )
    entries = list(entries_result.scalars().all())
    exercises_result = await session.execute(
        select(CommitmentExercise)
        .where(CommitmentExercise.commitment_id == commitment.id)
        .order_by(CommitmentExercise.position)
    )
    exercises = list(exercises_result.scalars().all())
    logged_ids: set[str] = set()
    if exercises:
        logs_result = await session.execute(
            select(CommitmentExerciseLog.exercise_id).where(
                and_(
                    CommitmentExerciseLog.commitment_id == commitment.id,
                    CommitmentExerciseLog.log_date == today,
                    CommitmentExerciseLog.deleted_at.is_(None),
                )
            ).distinct()
        )
        logged_ids = {str(row[0]) for row in logs_result.all()}

    return _commitment_to_response(commitment, entries, today, exercises, logged_ids)


# ── PATCH /v1/commitments/{id} ────────────────────────────────────────────────


@router.patch("/v1/commitments/{commitment_id}", response_model=CommitmentResponse)
@limiter.limit(commitments_limit)
async def update_commitment(
    request: Request,
    commitment_id: _uuid.UUID,
    body: CommitmentUpdate,
    session: AsyncSession = Depends(get_db),
) -> CommitmentResponse:
    """Update commitment fields (e.g., abandon)."""
    commitment = await session.get(Commitment, commitment_id)
    if commitment is None:
        raise HTTPException(status_code=404, detail="Commitment not found")

    if body.status is not None:
        commitment.status = body.status

    await session.commit()
    await session.refresh(commitment)

    entries_result = await session.execute(
        select(CommitmentEntry)
        .where(CommitmentEntry.commitment_id == commitment.id)
        .order_by(CommitmentEntry.entry_date)
    )
    entries = list(entries_result.scalars().all())
    exercises_result = await session.execute(
        select(CommitmentExercise)
        .where(CommitmentExercise.commitment_id == commitment.id)
        .order_by(CommitmentExercise.position)
    )
    exercises = list(exercises_result.scalars().all())
    today = _get_today()
    logged_ids: set[str] = set()
    if exercises:
        logs_result = await session.execute(
            select(CommitmentExerciseLog.exercise_id).where(
                and_(
                    CommitmentExerciseLog.commitment_id == commitment.id,
                    CommitmentExerciseLog.log_date == today,
                    CommitmentExerciseLog.deleted_at.is_(None),
                )
            ).distinct()
        )
        logged_ids = {str(row[0]) for row in logs_result.all()}

    logger.info("commitment_updated", commitment_id=str(commitment.id), status=commitment.status)
    return _commitment_to_response(commitment, entries, today, exercises, logged_ids)


# ── POST /v1/commitments/{id}/log ─────────────────────────────────────────────


@router.post("/v1/commitments/{commitment_id}/log", response_model=EntryResponse)
@limiter.limit(commitments_limit)
async def log_count(
    request: Request,
    commitment_id: _uuid.UUID,
    body: LogCount,
    session: AsyncSession = Depends(get_db),
) -> EntryResponse:
    """Log count for today's entry. Increments logged_count additively."""
    today = _get_today()

    # Verify commitment exists and is active
    commitment = await session.get(Commitment, commitment_id)
    if commitment is None:
        raise HTTPException(status_code=404, detail="Commitment not found")
    if commitment.cadence == "aggregate":
        raise HTTPException(
            status_code=400,
            detail="Aggregate commitments are tracked via Strava, not manual logging",
        )
    kind = commitment.kind or "single"
    if kind in ("routine", "plan"):
        raise HTTPException(
            status_code=400,
            detail="Multi-exercise commitments use POST /v1/commitments/{id}/exercises/{exercise_id}/log",
        )
    if commitment.status != "active":
        raise HTTPException(status_code=400, detail="Commitment is not active")
    if today < commitment.start_date:
        raise HTTPException(status_code=400, detail="Commitment has not started yet")

    # Find today's entry
    entry_result = await session.execute(
        select(CommitmentEntry).where(
            CommitmentEntry.commitment_id == commitment_id,
            CommitmentEntry.entry_date == today,
        )
    )
    entry = entry_result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=400,
            detail="No entry for today — date may be outside commitment range",
        )
    if entry.status == "miss":
        raise HTTPException(status_code=400, detail="Cannot log on a missed entry")

    # Increment count
    entry.logged_count += body.count

    # Auto-transition to "hit" when target met
    if entry.logged_count >= commitment.daily_target and entry.status == "pending":
        entry.status = "hit"

    await session.commit()
    await session.refresh(entry)

    logger.info(
        "commitment_logged",
        commitment_id=commitment_id,
        entry_date=str(today),
        logged_count=entry.logged_count,
        status=entry.status,
    )
    return _entry_to_response(entry)


# ── POST /v1/commitments/{id}/exercises/{exercise_id}/log ─────────────────────


@router.post(
    "/v1/commitments/{commitment_id}/exercises/{exercise_id}/log",
    response_model=ExerciseLogResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(commitments_limit)
async def log_exercise(
    request: Request,
    commitment_id: _uuid.UUID,
    exercise_id: _uuid.UUID,
    body: ExerciseLogCreate,
    session: AsyncSession = Depends(get_db),
) -> ExerciseLogResponse:
    """Log a per-exercise entry for today. Flips entry to hit when all exercises done."""
    today = _get_today()

    commitment = await session.get(Commitment, commitment_id)
    if commitment is None:
        raise HTTPException(status_code=404, detail="Commitment not found")

    kind = commitment.kind or "single"
    if kind not in ("routine", "plan"):
        raise HTTPException(
            status_code=400,
            detail="This endpoint is for routine/plan commitments only",
        )
    if commitment.status != "active":
        raise HTTPException(status_code=400, detail="Commitment is not active")
    if today < commitment.start_date or today > commitment.end_date:
        raise HTTPException(status_code=400, detail="Today is outside commitment range")

    exercise = await session.get(CommitmentExercise, exercise_id)
    if exercise is None or str(exercise.commitment_id) != str(commitment_id):
        raise HTTPException(status_code=404, detail="Exercise not found")

    # Check entry exists for today (rest days have no entry)
    entry_result = await session.execute(
        select(CommitmentEntry).where(
            and_(
                CommitmentEntry.commitment_id == commitment_id,
                CommitmentEntry.entry_date == today,
            )
        )
    )
    entry = entry_result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=400,
            detail="No entry for today — today may be a rest day or outside commitment range",
        )
    if entry.status == "miss":
        raise HTTPException(status_code=400, detail="Cannot log on a missed entry")

    log = CommitmentExerciseLog(
        commitment_id=commitment.id,
        exercise_id=exercise.id,
        log_date=today,
        sets=body.sets,
        reps=body.reps,
        weight_kg=body.weight_kg,
        duration_minutes=body.duration_minutes,
        notes=body.notes,
    )
    session.add(log)
    await session.flush()

    await _check_and_flip_entry(session, commitment_id, today)
    await session.commit()
    await session.refresh(log)

    logger.info(
        "exercise_logged",
        commitment_id=str(commitment_id),
        exercise_id=str(exercise_id),
        log_date=str(today),
    )
    return _log_to_response(log)


# ── DELETE /v1/commitments/{id}/exercises/{exercise_id}/logs/{log_id} ─────────


@router.delete(
    "/v1/commitments/{commitment_id}/exercises/{exercise_id}/logs/{log_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
@limiter.limit(commitments_limit)
async def delete_exercise_log(
    request: Request,
    commitment_id: _uuid.UUID,
    exercise_id: _uuid.UUID,
    log_id: _uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete an exercise log. Reverts entry to pending if day becomes incomplete."""
    log = await session.get(CommitmentExerciseLog, log_id)
    if log is None or str(log.commitment_id) != str(commitment_id) or str(log.exercise_id) != str(exercise_id):
        raise HTTPException(status_code=404, detail="Log not found")
    if log.deleted_at is not None:
        raise HTTPException(status_code=400, detail="Log already deleted")

    log.deleted_at = datetime.now(timezone.utc)
    await session.flush()

    await _check_and_flip_entry(session, commitment_id, log.log_date)
    await session.commit()

    logger.info(
        "exercise_log_deleted",
        log_id=str(log_id),
        commitment_id=str(commitment_id),
        exercise_id=str(exercise_id),
    )


# ── GET /v1/commitments/{id}/progression ──────────────────────────────────────


@router.get(
    "/v1/commitments/{commitment_id}/progression",
    response_model=list[ExerciseProgressionResponse],
)
@limiter.limit(commitments_limit)
async def get_progression(
    request: Request,
    commitment_id: _uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> list[ExerciseProgressionResponse]:
    """Per-exercise progression series. Returns all non-deleted logs grouped by exercise."""
    commitment = await session.get(Commitment, commitment_id)
    if commitment is None:
        raise HTTPException(status_code=404, detail="Commitment not found")

    kind = commitment.kind or "single"
    if kind not in ("routine", "plan"):
        raise HTTPException(
            status_code=400,
            detail="Progression is only available for routine/plan commitments",
        )

    exercises_result = await session.execute(
        select(CommitmentExercise)
        .where(CommitmentExercise.commitment_id == commitment_id)
        .order_by(CommitmentExercise.position)
    )
    exercises = list(exercises_result.scalars().all())

    logs_result = await session.execute(
        select(CommitmentExerciseLog).where(
            and_(
                CommitmentExerciseLog.commitment_id == commitment_id,
                CommitmentExerciseLog.deleted_at.is_(None),
            )
        ).order_by(CommitmentExerciseLog.exercise_id, CommitmentExerciseLog.log_date)
    )
    all_logs = list(logs_result.scalars().all())

    logs_by_exercise: dict[str, list[CommitmentExerciseLog]] = {}
    for log in all_logs:
        key = str(log.exercise_id)
        logs_by_exercise.setdefault(key, []).append(log)

    result = []
    for ex in exercises:
        ex_logs = logs_by_exercise.get(str(ex.id), [])
        points = []
        for log in ex_logs:
            if ex.progression_metric == "reps":
                value = float(log.reps or 0)
            elif ex.progression_metric == "kg":
                value = float(log.weight_kg or 0)
            elif ex.progression_metric == "minutes":
                value = float(log.duration_minutes or 0)
            else:
                value = float(log.reps or 0)
            points.append(ProgressionPoint(date=log.log_date, value=value, metric=ex.progression_metric))

        result.append(ExerciseProgressionResponse(
            exercise_id=str(ex.id),
            exercise_name=ex.name,
            points=points,
        ))

    return result
