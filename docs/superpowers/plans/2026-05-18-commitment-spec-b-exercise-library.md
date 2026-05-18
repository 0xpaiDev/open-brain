# Commitment Spec B: Exercise Library + Per-Day Schedule — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the global exercise library, store per-day exercise assignments, extend the import wizard to resolve unknown exercises, and add a plan CRUD editor page.

**Architecture:** New `CommitmentEntryExercise` ORM model joins `CommitmentEntry` ↔ `CommitmentExercise` for per-day schedule storage. Import service extended to upsert into `exercises` table and create junction rows. New `schedule_service.py` handles CRUD on schedule. Import page becomes a 3-step wizard. New `/commitments/[id]/edit` page is the plan editor.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, pytest, Next.js 15, React 19, TypeScript, Vitest

---

## File Map

| File | Change |
|---|---|
| `src/core/models.py` | Add `CommitmentEntryExercise` model + relationships on `CommitmentEntry`/`CommitmentExercise` |
| `alembic/versions/0021_commitment_entry_exercises.py` | New migration for junction table |
| `src/api/schemas/commitment_import.py` | Add `UnknownExercise`, `ResolvedExercise`, extend `CommitmentImportRequest` + `CommitmentImportResult` |
| `src/api/services/commitment_import_service.py` | Add `_normalise`, library upsert, per-day entry_exercises creation |
| `src/api/services/schedule_service.py` | New — `get_schedule`, `swap_day`, `update_day_exercises` |
| `src/api/routes/commitments.py` | Add `GET /v1/exercises`, `GET /v1/commitments/{id}/schedule`, `PATCH /v1/commitments/{id}/entries/{date}`, `PATCH /v1/commitments/{id}/entries/{entry_id}/exercises`; update exercise log endpoint |
| `src/api/routes/exercises.py` | New router for `GET /v1/exercises` |
| `tests/test_commitment_import.py` | Extend with library + entry_exercises tests |
| `tests/test_commitment_schedule.py` | New test file |
| `web/lib/types.ts` | Add `Exercise`, `ScheduleDay`, `ScheduleResponse`, `UnknownExercise`, `ResolvedExercise`; extend `CommitmentImportResult` |
| `web/hooks/use-exercises.ts` | New hook |
| `web/hooks/use-commitments.ts` | Add `getSchedule`, `swapDay`, `updateDayExercises` |
| `web/app/commitments/import/page.tsx` | Rewrite as 3-step wizard |
| `web/app/commitments/[id]/edit/page.tsx` | New plan CRUD editor page |

---

### Task 1: Add `CommitmentEntryExercise` ORM model

**Files:**
- Modify: `src/core/models.py` (after line 615, the `CommitmentEntry` class)

- [ ] **Step 1: Add the model after `CommitmentEntry`**

In `src/core/models.py`, after the `CommitmentEntry` class (after line 615), add:

```python
class CommitmentEntryExercise(Base):
    """Junction table: which exercises are scheduled for a specific CommitmentEntry (day).

    Created at import time per workout day. Editable via CRUD editor.
    """

    __tablename__ = "commitment_entry_exercises"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    commitment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commitments.id", ondelete="CASCADE"), nullable=False
    )
    entry_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commitment_entries.id", ondelete="CASCADE"), nullable=False
    )
    exercise_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("commitment_exercises.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("entry_id", "exercise_id", name="uq_entry_exercise"),
        Index("ix_entry_exercises_commitment_entry", "commitment_id", "entry_id"),
    )

    entry: Mapped["CommitmentEntry"] = relationship("CommitmentEntry", back_populates="entry_exercises")
    commitment_exercise: Mapped["CommitmentExercise"] = relationship(
        "CommitmentExercise", back_populates="entry_exercises"
    )
```

- [ ] **Step 2: Add relationships to `CommitmentEntry` and `CommitmentExercise`**

In the `CommitmentEntry` class, add after the existing `commitment` relationship:

```python
entry_exercises: Mapped[list["CommitmentEntryExercise"]] = relationship(
    "CommitmentEntryExercise", back_populates="entry", cascade="all, delete-orphan"
)
```

In the `CommitmentExercise` class, add after the existing `exercise_library` relationship:

```python
entry_exercises: Mapped[list["CommitmentEntryExercise"]] = relationship(
    "CommitmentEntryExercise", back_populates="commitment_exercise", passive_deletes=True
)
```

- [ ] **Step 3: Run tests to confirm models import cleanly**

```bash
make test -k "test_legacy" 2>&1 | tail -20
```

Expected: 1 passed. (Just checks the models load without import errors.)

- [ ] **Step 4: Commit**

```bash
git add src/core/models.py
git commit -m "feat(models): add CommitmentEntryExercise junction table model"
```

---

### Task 2: Alembic migration 0021

**Files:**
- Create: `alembic/versions/0021_commitment_entry_exercises.py`

The table already exists in production Supabase (created manually). This migration recreates it for local/SQLite test runs.

- [ ] **Step 1: Create the migration file**

```python
"""Add commitment_entry_exercises junction table.

Table already exists in Supabase (created manually).
This migration ensures fresh SQLite test DBs and future environments get it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "commitment_entry_exercises",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("commitment_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("entry_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["commitment_id"], ["commitments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entry_id"], ["commitment_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exercise_id"], ["commitment_exercises.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("entry_id", "exercise_id", name="uq_entry_exercise"),
    )
    op.create_index(
        "ix_entry_exercises_commitment_entry",
        "commitment_entry_exercises",
        ["commitment_id", "entry_id"],
    )
    try:
        op.execute("ALTER TABLE commitment_entry_exercises ENABLE ROW LEVEL SECURITY")
    except Exception:
        pass  # SQLite ignores RLS


def downgrade() -> None:
    op.drop_index("ix_entry_exercises_commitment_entry", table_name="commitment_entry_exercises")
    op.drop_table("commitment_entry_exercises")
```

- [ ] **Step 2: Run tests to confirm migration applies on SQLite**

```bash
make test -k "test_legacy" 2>&1 | tail -20
```

Expected: 1 passed. (The test fixtures run migrations on a fresh SQLite DB.)

- [ ] **Step 3: Commit**

```bash
git add alembic/versions/0021_commitment_entry_exercises.py
git commit -m "feat(db): add migration 0021 for commitment_entry_exercises junction table"
```

---

### Task 3: Extend import schemas

**Files:**
- Modify: `src/api/schemas/commitment_import.py`

- [ ] **Step 1: Add `UnknownExercise`, `ResolvedExercise`, extend `CommitmentImportResult` and `CommitmentImportRequest`**

Replace the entire contents of `src/api/schemas/commitment_import.py` with:

```python
"""Pydantic schemas for the commitment plan import API.

All models use extra="forbid" to reject unknown fields before any DB writes.
Position is server-assigned; exercise order is preserved from the payload array.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_VALID_METRICS = {"reps", "minutes", "kg", "seconds"}
_VALID_PROGRESSION_METRICS = {"reps", "minutes", "kg", "seconds"}


class ImportExerciseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    sets: int | None = Field(default=None, ge=1, le=100)
    target: int = Field(gt=0)
    metric: str = Field(default="reps")
    progression_metric: str = Field(default="reps")

    @field_validator("metric")
    @classmethod
    def validate_metric(cls, v: str) -> str:
        if v not in _VALID_METRICS:
            raise ValueError(f"metric must be one of {sorted(_VALID_METRICS)}")
        return v

    @field_validator("progression_metric")
    @classmethod
    def validate_progression_metric(cls, v: str) -> str:
        if v not in _VALID_PROGRESSION_METRICS:
            raise ValueError(f"progression_metric must be one of {sorted(_VALID_PROGRESSION_METRICS)}")
        return v


class ImportScheduleDay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: date
    rest: bool = False
    exercises: list[ImportExerciseSpec] = Field(default_factory=list)

    @field_validator("exercises")
    @classmethod
    def validate_exercises(cls, v: list, info) -> list:
        if not info.data.get("rest", False) and len(v) == 0:
            raise ValueError("workout days must have at least 1 exercise")
        if len(v) > 5:
            raise ValueError("maximum 5 exercises per workout day")
        return v


class UnknownExercise(BaseModel):
    """An exercise name from the import payload that has no match in the exercises library."""
    name: str
    sets: int | None = None
    target: int
    metric: str = "reps"
    progression_metric: str = "reps"


class ResolvedExercise(BaseModel):
    """User's resolution for an unknown exercise during import wizard step 2."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    exercise_id: str | None = None       # set if matched to existing library entry
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    metric: str = "reps"
    progression_metric: str = "reps"
    target: int = Field(gt=0)
    sets: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def validate_resolution(self) -> "ResolvedExercise":
        if self.exercise_id is None and self.display_name is None:
            raise ValueError("Either exercise_id (match existing) or display_name (create new) must be provided")
        return self

    @field_validator("metric")
    @classmethod
    def validate_metric(cls, v: str) -> str:
        if v not in _VALID_METRICS:
            raise ValueError(f"metric must be one of {sorted(_VALID_METRICS)}")
        return v

    @field_validator("progression_metric")
    @classmethod
    def validate_progression_metric(cls, v: str) -> str:
        if v not in _VALID_PROGRESSION_METRICS:
            raise ValueError(f"progression_metric must be one of {sorted(_VALID_PROGRESSION_METRICS)}")
        return v


class CommitmentImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date
    schedule: list[ImportScheduleDay] = Field(min_length=1, max_length=200)
    resolved_exercises: list[ResolvedExercise] = Field(default_factory=list)

    @field_validator("end_date")
    @classmethod
    def validate_end_after_start(cls, v: date, info) -> date:
        start = info.data.get("start_date")
        if start and v < start:
            raise ValueError("end_date must be on or after start_date")
        return v


class CommitmentImportResult(BaseModel):
    dry_run: bool
    commitment_id: str | None = None
    already_exists: bool = False
    workout_days: int
    rest_days: int
    exercise_count: int
    unknown_exercises: list[UnknownExercise] = Field(default_factory=list)
```

- [ ] **Step 2: Write failing tests for the new schema**

Add to `tests/test_commitment_import.py`:

```python
def test_resolved_exercise_requires_id_or_display_name():
    """ResolvedExercise must have either exercise_id or display_name."""
    from pydantic import ValidationError
    from src.api.schemas.commitment_import import ResolvedExercise
    with pytest.raises(ValidationError, match="exercise_id.*display_name|display_name.*exercise_id"):
        ResolvedExercise(name="Squat", target=5)


def test_resolved_exercise_with_display_name_is_valid():
    from src.api.schemas.commitment_import import ResolvedExercise
    r = ResolvedExercise(name="Squat", display_name="Squat", target=5)
    assert r.display_name == "Squat"
    assert r.exercise_id is None


def test_resolved_exercise_with_exercise_id_is_valid():
    from src.api.schemas.commitment_import import ResolvedExercise
    r = ResolvedExercise(name="Squat", exercise_id="some-uuid", target=5)
    assert r.exercise_id == "some-uuid"
    assert r.display_name is None
```

- [ ] **Step 3: Run these tests**

```bash
make test -k "test_resolved_exercise" 2>&1 | tail -20
```

Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add src/api/schemas/commitment_import.py tests/test_commitment_import.py
git commit -m "feat(schemas): add UnknownExercise, ResolvedExercise to import schemas"
```

---

### Task 4: Update import service

**Files:**
- Modify: `src/api/services/commitment_import_service.py`

- [ ] **Step 1: Write failing tests for the new service behaviour**

Add to `tests/test_commitment_import.py`:

```python
@pytest.mark.asyncio
async def test_dry_run_returns_unknown_exercises(test_client, api_key_headers):
    """Dry run returns unknown_exercises for names not in the library."""
    payload = _make_plan_payload()
    resp = await test_client.post(
        "/v1/commitments/import?dry_run=true", json=payload, headers=api_key_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    # Fresh DB has no exercises library entries, so both exercises are unknown
    assert len(data["unknown_exercises"]) == 2
    names = {e["name"] for e in data["unknown_exercises"]}
    assert "Squat" in names
    assert "Bench Press" in names


@pytest.mark.asyncio
async def test_dry_run_no_unknowns_when_library_seeded(test_client, api_key_headers, async_session):
    """Dry run returns no unknowns when exercises already in library."""
    from src.core.models import Exercise
    squat = Exercise(name="squat", display_name="Squat")
    bench = Exercise(name="bench press", display_name="Bench Press")
    async_session.add_all([squat, bench])
    await async_session.commit()

    payload = _make_plan_payload()
    resp = await test_client.post(
        "/v1/commitments/import?dry_run=true", json=payload, headers=api_key_headers
    )
    assert resp.status_code == 200
    assert resp.json()["unknown_exercises"] == []


@pytest.mark.asyncio
async def test_commit_with_resolved_exercises_creates_library_entries(test_client, api_key_headers, async_session):
    """Committing with resolved_exercises creates Exercise rows and entry_exercises."""
    from src.core.models import CommitmentEntryExercise, Exercise
    today = date.today()
    payload = _make_plan_payload()
    payload["resolved_exercises"] = [
        {"name": "Squat", "display_name": "Squat", "target": 5, "metric": "reps", "progression_metric": "kg"},
        {"name": "Bench Press", "display_name": "Bench Press", "target": 5, "metric": "reps", "progression_metric": "kg"},
    ]
    resp = await test_client.post(
        "/v1/commitments/import?dry_run=false", json=payload, headers=api_key_headers
    )
    assert resp.status_code == 200
    commitment_id = resp.json()["commitment_id"]

    # Exercise library entries created
    result = await async_session.execute(select(Exercise).where(Exercise.name == "squat"))
    assert result.scalar_one_or_none() is not None

    # entry_exercises created for workout days
    result = await async_session.execute(
        select(CommitmentEntryExercise).where(CommitmentEntryExercise.commitment_id == commitment_id)
    )
    rows = result.scalars().all()
    assert len(rows) >= 2  # at least 2 exercises × 1 workout day


@pytest.mark.asyncio
async def test_commit_without_resolving_unknowns_returns_422(test_client, api_key_headers):
    """Committing without resolved_exercises when unknowns exist returns 422."""
    payload = _make_plan_payload()
    # No resolved_exercises provided, fresh DB has no library entries
    resp = await test_client.post(
        "/v1/commitments/import?dry_run=false", json=payload, headers=api_key_headers
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run to confirm they fail**

```bash
make test -k "test_dry_run_returns_unknown or test_dry_run_no_unknowns or test_commit_with_resolved or test_commit_without_resolving" 2>&1 | tail -30
```

Expected: 4 failures (functions not yet implemented).

- [ ] **Step 3: Rewrite the import service**

Replace `src/api/services/commitment_import_service.py` with:

```python
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
```

- [ ] **Step 4: Run the failing tests**

```bash
make test -k "test_dry_run_returns_unknown or test_dry_run_no_unknowns or test_commit_with_resolved or test_commit_without_resolving" 2>&1 | tail -30
```

Expected: 4 passed.

- [ ] **Step 5: Run the full import test suite to check no regressions**

```bash
make test -k "test_commitment_import" 2>&1 | tail -20
```

Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add src/api/services/commitment_import_service.py tests/test_commitment_import.py
git commit -m "feat(import): exercise library upsert + per-day entry_exercises on commit"
```

---

### Task 5: Schedule service

**Files:**
- Create: `src/api/services/schedule_service.py`

- [ ] **Step 1: Create new test file with failing tests**

Create `tests/test_commitment_schedule.py`:

```python
"""Tests for schedule service: GET /schedule, day-swap PATCH endpoint."""

from datetime import date, timedelta

import pytest

from tests.test_commitment_import import _make_plan_payload


def _make_resolved_payload(name="Test Plan", days=4):
    today = date.today()
    payload = _make_plan_payload(name=name, days=days)
    payload["resolved_exercises"] = [
        {"name": "Squat", "display_name": "Squat", "target": 5, "metric": "reps", "progression_metric": "kg"},
        {"name": "Bench Press", "display_name": "Bench Press", "target": 5, "metric": "reps", "progression_metric": "kg"},
    ]
    return payload


@pytest.mark.asyncio
async def test_get_schedule_returns_all_days(test_client, api_key_headers):
    """GET /schedule returns every day from start to end, including rest days."""
    today = date.today()
    payload = _make_resolved_payload(days=4)
    create_resp = await test_client.post(
        "/v1/commitments/import?dry_run=false", json=payload, headers=api_key_headers
    )
    assert create_resp.status_code == 200
    commitment_id = create_resp.json()["commitment_id"]

    resp = await test_client.get(
        f"/v1/commitments/{commitment_id}/schedule", headers=api_key_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["commitment_id"] == commitment_id
    assert len(data["days"]) == 4  # 4 days total
    statuses = {d["date"]: d["status"] for d in data["days"]}
    assert statuses[str(today)] in ("pending", "hit", "miss")  # workout day
    assert statuses[str(today + timedelta(days=1))] == "rest"   # rest day


@pytest.mark.asyncio
async def test_get_schedule_includes_exercises_per_day(test_client, api_key_headers):
    """Workout days in schedule include their assigned exercises."""
    today = date.today()
    payload = _make_resolved_payload(days=2)
    create_resp = await test_client.post(
        "/v1/commitments/import?dry_run=false", json=payload, headers=api_key_headers
    )
    commitment_id = create_resp.json()["commitment_id"]

    resp = await test_client.get(
        f"/v1/commitments/{commitment_id}/schedule", headers=api_key_headers
    )
    days = resp.json()["days"]
    workout_day = next(d for d in days if d["status"] != "rest")
    assert len(workout_day["exercises"]) == 2
    names = {e["name"] for e in workout_day["exercises"]}
    assert "Squat" in names


@pytest.mark.asyncio
async def test_swap_rest_to_workout(test_client, api_key_headers):
    """PATCH entries/{date} to_workout creates entry + entry_exercises."""
    today = date.today()
    payload = _make_resolved_payload(days=2)
    create_resp = await test_client.post(
        "/v1/commitments/import?dry_run=false", json=payload, headers=api_key_headers
    )
    commitment_id = create_resp.json()["commitment_id"]

    # Get exercise IDs from the commitment
    detail = await test_client.get(f"/v1/commitments/{commitment_id}", headers=api_key_headers)
    exercise_ids = [e["id"] for e in detail.json()["exercises"]]

    rest_day = str(today + timedelta(days=1))
    resp = await test_client.patch(
        f"/v1/commitments/{commitment_id}/entries/{rest_day}",
        json={"action": "to_workout", "exercise_ids": exercise_ids},
        headers=api_key_headers,
    )
    assert resp.status_code == 200

    # Schedule should now show workout day
    schedule = await test_client.get(
        f"/v1/commitments/{commitment_id}/schedule", headers=api_key_headers
    )
    days = {d["date"]: d for d in schedule.json()["days"]}
    assert days[rest_day]["status"] == "pending"
    assert len(days[rest_day]["exercises"]) == len(exercise_ids)


@pytest.mark.asyncio
async def test_swap_workout_to_rest_pending(test_client, api_key_headers):
    """PATCH entries/{date} to_rest on pending entry deletes it."""
    today = date.today()
    payload = _make_resolved_payload(days=2)
    create_resp = await test_client.post(
        "/v1/commitments/import?dry_run=false", json=payload, headers=api_key_headers
    )
    commitment_id = create_resp.json()["commitment_id"]

    resp = await test_client.patch(
        f"/v1/commitments/{commitment_id}/entries/{str(today)}",
        json={"action": "to_rest", "exercise_ids": []},
        headers=api_key_headers,
    )
    assert resp.status_code == 200

    schedule = await test_client.get(
        f"/v1/commitments/{commitment_id}/schedule", headers=api_key_headers
    )
    days = {d["date"]: d for d in schedule.json()["days"]}
    assert days[str(today)]["status"] == "rest"


@pytest.mark.asyncio
async def test_swap_workout_to_rest_hit_rejected(test_client, api_key_headers, async_session):
    """PATCH to_rest on a hit entry returns 400."""
    from src.core.models import CommitmentEntry
    from sqlalchemy import select as sa_select, and_

    today = date.today()
    payload = _make_resolved_payload(days=2)
    create_resp = await test_client.post(
        "/v1/commitments/import?dry_run=false", json=payload, headers=api_key_headers
    )
    commitment_id = create_resp.json()["commitment_id"]

    # Manually mark today's entry as hit
    result = await async_session.execute(
        sa_select(CommitmentEntry).where(
            and_(CommitmentEntry.commitment_id == commitment_id, CommitmentEntry.entry_date == today)
        )
    )
    entry = result.scalar_one()
    entry.status = "hit"
    await async_session.commit()

    resp = await test_client.patch(
        f"/v1/commitments/{commitment_id}/entries/{str(today)}",
        json={"action": "to_rest", "exercise_ids": []},
        headers=api_key_headers,
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run to confirm all fail**

```bash
make test -k "test_commitment_schedule" 2>&1 | tail -30
```

Expected: 5 failures (endpoints not yet implemented).

- [ ] **Step 3: Create `src/api/services/schedule_service.py`**

```python
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
```

- [ ] **Step 4: Commit the service (before wiring routes)**

```bash
git add src/api/services/schedule_service.py tests/test_commitment_schedule.py
git commit -m "feat(services): add schedule_service with get_schedule, swap_day, update_day_exercises"
```

---

### Task 6: New API routes

**Files:**
- Create: `src/api/routes/exercises.py`
- Modify: `src/api/routes/commitments.py`

- [ ] **Step 1: Create `src/api/routes/exercises.py`**

```python
"""Global exercise library endpoints.

GET /v1/exercises — list all exercises ordered by display_name
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import commitments_limit, limiter
from src.core.database import get_db
from src.core.models import Exercise

logger = structlog.get_logger(__name__)

router = APIRouter()


class ExerciseLibraryResponse(BaseModel):
    id: str
    name: str
    display_name: str
    created_at: str


@router.get("/v1/exercises", response_model=list[ExerciseLibraryResponse])
@limiter.limit(commitments_limit)
async def list_exercises(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> list[ExerciseLibraryResponse]:
    """List all exercises in the global library, ordered by display_name."""
    result = await session.execute(
        select(Exercise).order_by(Exercise.display_name)
    )
    exercises = result.scalars().all()
    return [
        ExerciseLibraryResponse(
            id=str(ex.id),
            name=ex.name,
            display_name=ex.display_name,
            created_at=str(ex.created_at),
        )
        for ex in exercises
    ]
```

- [ ] **Step 2: Register the new router in `src/api/main.py`**

In `src/api/main.py`, add the import alongside the other route imports (around line 14):

```python
from src.api.routes.exercises import router as exercises_router
```

Then add it to the `app.include_router(...)` calls in the same file:

```python
app.include_router(exercises_router)
```

- [ ] **Step 3: Add schedule + swap endpoints to `src/api/routes/commitments.py`**

At the top of the file, add to imports:
```python
from src.api.services.schedule_service import get_schedule, swap_day, update_day_exercises
```

Add these Pydantic models to the models section (after `ExerciseProgressionResponse`):

```python
class ExerciseRef(BaseModel):
    exercise_id: str
    name: str
    sets: int | None = None
    target: int
    metric: str


class ScheduleDay(BaseModel):
    entry_id: str | None
    date: str
    status: str
    exercises: list[ExerciseRef] = []


class ScheduleResponse(BaseModel):
    commitment_id: str
    days: list[ScheduleDay]


class EntrySwapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str  # "to_workout" | "to_rest"
    exercise_ids: list[str] = []

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in ("to_workout", "to_rest"):
            raise ValueError("action must be 'to_workout' or 'to_rest'")
        return v


class UpdateDayExercisesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exercise_ids: list[str]
```

Add these endpoints after the `GET /v1/commitments/{id}/progression` endpoint:

```python
# ── GET /v1/commitments/{id}/schedule ────────────────────────────────────────


@router.get("/v1/commitments/{commitment_id}/schedule", response_model=ScheduleResponse)
@limiter.limit(commitments_limit)
async def get_commitment_schedule(
    request: Request,
    commitment_id: _uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> ScheduleResponse:
    """Get full day-by-day schedule for a plan commitment."""
    data = await get_schedule(session, str(commitment_id))
    return ScheduleResponse(
        commitment_id=data["commitment_id"],
        days=[ScheduleDay(**d) for d in data["days"]],
    )


# ── PATCH /v1/commitments/{id}/entries/{date} ─────────────────────────────────


@router.patch("/v1/commitments/{commitment_id}/entries/{entry_date}")
@limiter.limit(commitments_limit)
async def swap_commitment_day(
    request: Request,
    commitment_id: _uuid.UUID,
    entry_date: date,
    body: EntrySwapRequest,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Flip a day between rest and workout for a plan commitment."""
    await swap_day(session, str(commitment_id), entry_date, body.action, body.exercise_ids)
    return {"ok": True}


# ── PATCH /v1/commitments/{id}/entries/{entry_id}/exercises ──────────────────


@router.patch("/v1/commitments/{commitment_id}/entries/{entry_id}/exercises")
@limiter.limit(commitments_limit)
async def update_entry_exercises(
    request: Request,
    commitment_id: _uuid.UUID,
    entry_id: _uuid.UUID,
    body: UpdateDayExercisesRequest,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Replace the exercise assignments for a workout day."""
    await update_day_exercises(session, str(commitment_id), str(entry_id), body.exercise_ids)
    return {"ok": True}
```

- [ ] **Step 4: Run the schedule tests**

```bash
make test -k "test_commitment_schedule" 2>&1 | tail -30
```

Expected: all 5 passed.

- [ ] **Step 5: Fix `_check_and_flip_entry` for plan kind + add exercise-log validation**

The existing `_check_and_flip_entry` compares ALL commitment exercises against today's logs. For plan commitments, a day is "hit" when only the *scheduled* exercises (those in `commitment_entry_exercises` for today's entry) are all logged — not all exercises globally. Update it:

```python
async def _check_and_flip_entry(
    session: AsyncSession,
    commitment_id,
    today: date,
) -> None:
    """After a log insert, check if all exercises are done today and flip entry to hit."""
    from src.core.models import CommitmentEntryExercise  # avoid circular at top level

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

    # For plan commitments, "all done" = all entry_exercises for today logged
    commitment = await session.get(Commitment, commitment_id)
    kind = (commitment.kind or "single") if commitment else "single"

    if kind == "plan":
        scheduled_result = await session.execute(
            select(CommitmentEntryExercise.exercise_id).where(
                CommitmentEntryExercise.entry_id == entry.id
            )
        )
        total_ids = {str(row[0]) for row in scheduled_result.all()}
    else:
        total_exercises_result = await session.execute(
            select(CommitmentExercise).where(CommitmentExercise.commitment_id == commitment_id)
        )
        total_ids = {str(ex.id) for ex in total_exercises_result.scalars().all()}

    if not total_ids:
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

    if total_ids <= logged_exercise_ids:
        entry.status = "hit"
    else:
        if entry.status == "hit":
            entry.status = "pending"
```

Now add the schedule validation for plan kind. In `log_exercise` (around line 801 in `commitments.py`), after verifying the exercise belongs to the commitment, add:

```python
    # For plan commitments: exercise must be scheduled for today's entry
    if kind == "plan":
        junction_result = await session.execute(
            select(CommitmentEntryExercise).where(
                and_(
                    CommitmentEntryExercise.entry_id == entry.id,
                    CommitmentEntryExercise.exercise_id == exercise_id,
                )
            )
        )
        if junction_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=400,
                detail="Exercise not scheduled for today",
            )
```

Also add the import at the top of `commitments.py`:
```python
from src.core.models import Commitment, CommitmentEntry, CommitmentEntryExercise, CommitmentExercise, CommitmentExerciseLog
```

- [ ] **Step 6: Write and run a test for plan-log restriction**

Add to `tests/test_commitment_schedule.py`:

```python
@pytest.mark.asyncio
async def test_log_exercise_not_scheduled_today_rejected(test_client, api_key_headers):
    """For plan commitments, logging an exercise not in today's schedule returns 400."""
    today = date.today()
    # Create a plan where today has only Squat, not Bench Press
    payload = {
        "name": "Split Plan",
        "start_date": str(today),
        "end_date": str(today + timedelta(days=3)),
        "schedule": [
            {"day": str(today), "rest": False, "exercises": [
                {"name": "Squat", "target": 5, "metric": "reps", "progression_metric": "kg"},
            ]},
            {"day": str(today + timedelta(days=1)), "rest": False, "exercises": [
                {"name": "Bench Press", "target": 5, "metric": "reps", "progression_metric": "kg"},
            ]},
            {"day": str(today + timedelta(days=2)), "rest": True},
            {"day": str(today + timedelta(days=3)), "rest": True},
        ],
        "resolved_exercises": [
            {"name": "Squat", "display_name": "Squat", "target": 5, "metric": "reps", "progression_metric": "kg"},
            {"name": "Bench Press", "display_name": "Bench Press", "target": 5, "metric": "reps", "progression_metric": "kg"},
        ],
    }
    create_resp = await test_client.post(
        "/v1/commitments/import?dry_run=false", json=payload, headers=api_key_headers
    )
    assert create_resp.status_code == 200
    commitment_id = create_resp.json()["commitment_id"]

    detail = await test_client.get(f"/v1/commitments/{commitment_id}", headers=api_key_headers)
    exercises = detail.json()["exercises"]
    bench_id = next(e["id"] for e in exercises if e["name"] == "Bench Press")

    # Trying to log Bench Press on a day only Squat is scheduled → 400
    resp = await test_client.post(
        f"/v1/commitments/{commitment_id}/exercises/{bench_id}/log",
        json={"reps": 5},
        headers=api_key_headers,
    )
    assert resp.status_code == 400
    assert "not scheduled" in resp.json()["detail"].lower()
```

```bash
make test -k "test_log_exercise_not_scheduled" 2>&1 | tail -20
```

Expected: 1 passed.

- [ ] **Step 7: Run full test suite**

```bash
make test 2>&1 | tail -20
```

Expected: all passing.

- [ ] **Step 8: Commit**

```bash
git add src/api/routes/exercises.py src/api/routes/commitments.py src/api/services/schedule_service.py tests/test_commitment_schedule.py
git commit -m "feat(api): add GET /exercises, GET/PATCH schedule endpoints, plan log validation"
```

---

### Task 7: Frontend types

**Files:**
- Modify: `web/lib/types.ts`

- [ ] **Step 1: Add new types and extend existing ones**

In `web/lib/types.ts`, add after the `CommitmentCreate` interface:

```typescript
export interface Exercise {
  id: string;
  name: string;
  display_name: string;
  created_at: string;
}

export interface ScheduleDayExercise {
  exercise_id: string;
  name: string;
  sets: number | null;
  target: number;
  metric: string;
}

export interface ScheduleDay {
  entry_id: string | null;
  date: string;
  status: "pending" | "hit" | "miss" | "rest";
  exercises: ScheduleDayExercise[];
}

export interface ScheduleResponse {
  commitment_id: string;
  days: ScheduleDay[];
}

export interface UnknownExercise {
  name: string;
  sets: number | null;
  target: number;
  metric: string;
  progression_metric: string;
}

export interface ResolvedExercise {
  name: string;
  exercise_id?: string;
  display_name?: string;
  metric: string;
  progression_metric: string;
  target: number;
  sets?: number | null;
}
```

Extend `CommitmentImportResult`:

```typescript
export interface CommitmentImportResult {
  dry_run: boolean;
  commitment_id: string | null;
  already_exists: boolean;
  workout_days: number;
  rest_days: number;
  exercise_count: number;
  unknown_exercises: UnknownExercise[];  // add this field
}
```

- [ ] **Step 2: Run frontend type check**

```bash
cd web && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/lib/types.ts
git commit -m "feat(web): add Exercise, Schedule, UnknownExercise, ResolvedExercise types"
```

---

### Task 8: `use-exercises` hook and extend `use-commitments`

**Files:**
- Create: `web/hooks/use-exercises.ts`
- Modify: `web/hooks/use-commitments.ts`

- [ ] **Step 1: Create `web/hooks/use-exercises.ts`**

```typescript
"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { Exercise } from "@/lib/types";

export function useExercises() {
  const [exercises, setExercises] = useState<Exercise[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await api<Exercise[]>("GET", "/v1/exercises");
      setExercises(data);
    } catch {
      // Silently fail — library may be empty on first use
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { exercises, loading, refresh };
}
```

- [ ] **Step 2: Add `getSchedule`, `swapDay`, `updateDayExercises` to `use-commitments.ts`**

Add these methods before the `return` statement in `useCommitments`:

```typescript
const getSchedule = useCallback(
  async (commitmentId: string) => {
    return api<import("@/lib/types").ScheduleResponse>("GET", `/v1/commitments/${commitmentId}/schedule`);
  },
  [],
);

const swapDay = useCallback(
  async (commitmentId: string, entryDate: string, action: "to_workout" | "to_rest", exerciseIds: string[]) => {
    await api("PATCH", `/v1/commitments/${commitmentId}/entries/${entryDate}`, {
      action,
      exercise_ids: exerciseIds,
    });
    await refresh();
  },
  [refresh],
);

const updateDayExercises = useCallback(
  async (commitmentId: string, entryId: string, exerciseIds: string[]) => {
    await api("PATCH", `/v1/commitments/${commitmentId}/entries/${entryId}/exercises`, {
      exercise_ids: exerciseIds,
    });
    await refresh();
  },
  [refresh],
);
```

Add these to the return object:

```typescript
return { ..., getSchedule, swapDay, updateDayExercises };
```

- [ ] **Step 3: Run frontend tests**

```bash
cd web && npm test -- --run 2>&1 | tail -20
```

Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add web/hooks/use-exercises.ts web/hooks/use-commitments.ts
git commit -m "feat(web): add use-exercises hook and schedule methods to use-commitments"
```

---

### Task 9: Import wizard (3-step)

**Files:**
- Modify: `web/app/commitments/import/page.tsx`

- [ ] **Step 1: Rewrite the import page**

Replace the entire contents of `web/app/commitments/import/page.tsx` with:

```typescript
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { useCommitments } from "@/hooks/use-commitments";
import { useExercises } from "@/hooks/use-exercises";
import type { CommitmentImportResult, UnknownExercise, ResolvedExercise } from "@/lib/types";
import { toast } from "sonner";

type WizardStep = "validate" | "resolve" | "confirm";

const METRIC_OPTIONS = ["reps", "kg", "minutes", "seconds"] as const;

function ExerciseResolutionCard({
  unknown,
  exercises,
  onResolve,
}: {
  unknown: UnknownExercise;
  exercises: Array<{ id: string; display_name: string }>;
  onResolve: (resolved: ResolvedExercise) => void;
}) {
  const [mode, setMode] = useState<"create" | "match">("create");
  const [displayName, setDisplayName] = useState(unknown.name);
  const [metric, setMetric] = useState(unknown.metric);
  const [progressionMetric, setProgressionMetric] = useState(unknown.progression_metric);
  const [target, setTarget] = useState(unknown.target);
  const [sets, setSets] = useState<number | null>(unknown.sets);
  const [matchedId, setMatchedId] = useState("");

  const handleConfirm = () => {
    if (mode === "match" && matchedId) {
      onResolve({ name: unknown.name, exercise_id: matchedId, metric, progression_metric: progressionMetric, target, sets });
    } else {
      onResolve({ name: unknown.name, display_name: displayName, metric, progression_metric: progressionMetric, target, sets });
    }
  };

  const isReady = mode === "match" ? !!matchedId : !!displayName.trim();

  return (
    <div className="bg-surface-container rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="font-headline text-on-surface font-semibold">{unknown.name}</span>
        <div className="flex gap-2">
          <button
            onClick={() => setMode("create")}
            className={`text-xs px-3 py-1 rounded-full font-body transition-colors ${mode === "create" ? "bg-primary text-on-primary" : "bg-surface-container-high text-on-surface-variant"}`}
          >
            Create new
          </button>
          <button
            onClick={() => setMode("match")}
            className={`text-xs px-3 py-1 rounded-full font-body transition-colors ${mode === "match" ? "bg-primary text-on-primary" : "bg-surface-container-high text-on-surface-variant"}`}
          >
            Match existing
          </button>
        </div>
      </div>

      {mode === "create" ? (
        <div className="grid grid-cols-2 gap-2">
          <div className="col-span-2">
            <label className="text-xs text-on-surface-variant font-body block mb-1">Display name</label>
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full bg-surface rounded-lg px-3 py-2 text-base md:text-sm text-on-surface border border-outline/20 focus:outline-none focus:border-primary"
            />
          </div>
          <div>
            <label className="text-xs text-on-surface-variant font-body block mb-1">Metric</label>
            <select
              value={metric}
              onChange={(e) => setMetric(e.target.value)}
              className="w-full bg-surface rounded-lg px-3 py-2 text-base md:text-sm text-on-surface border border-outline/20 focus:outline-none focus:border-primary"
            >
              {METRIC_OPTIONS.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-on-surface-variant font-body block mb-1">Progression metric</label>
            <select
              value={progressionMetric}
              onChange={(e) => setProgressionMetric(e.target.value)}
              className="w-full bg-surface rounded-lg px-3 py-2 text-base md:text-sm text-on-surface border border-outline/20 focus:outline-none focus:border-primary"
            >
              {METRIC_OPTIONS.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-on-surface-variant font-body block mb-1">Target</label>
            <input
              type="number"
              min={1}
              value={target}
              onChange={(e) => setTarget(Number(e.target.value))}
              className="w-full bg-surface rounded-lg px-3 py-2 text-base md:text-sm text-on-surface border border-outline/20 focus:outline-none focus:border-primary"
            />
          </div>
          <div>
            <label className="text-xs text-on-surface-variant font-body block mb-1">Sets (optional)</label>
            <input
              type="number"
              min={1}
              value={sets ?? ""}
              onChange={(e) => setSets(e.target.value ? Number(e.target.value) : null)}
              className="w-full bg-surface rounded-lg px-3 py-2 text-base md:text-sm text-on-surface border border-outline/20 focus:outline-none focus:border-primary"
            />
          </div>
        </div>
      ) : (
        <div>
          <label className="text-xs text-on-surface-variant font-body block mb-1">Match to library exercise</label>
          <select
            value={matchedId}
            onChange={(e) => setMatchedId(e.target.value)}
            className="w-full bg-surface rounded-lg px-3 py-2 text-base md:text-sm text-on-surface border border-outline/20 focus:outline-none focus:border-primary"
          >
            <option value="">Select exercise…</option>
            {exercises.map((ex) => (
              <option key={ex.id} value={ex.id}>{ex.display_name}</option>
            ))}
          </select>
        </div>
      )}

      <button
        onClick={handleConfirm}
        disabled={!isReady}
        className="w-full bg-primary text-on-primary rounded-lg py-2 text-base md:text-sm font-body disabled:opacity-40 hover:opacity-90 transition-opacity"
      >
        Confirm
      </button>
    </div>
  );
}

export default function ImportPlanPage() {
  const router = useRouter();
  const { importPlan } = useCommitments();
  const { exercises } = useExercises();

  const [step, setStep] = useState<WizardStep>("validate");
  const [jsonText, setJsonText] = useState("");
  const [dryRunResult, setDryRunResult] = useState<CommitmentImportResult | null>(null);
  const [parsedPayload, setParsedPayload] = useState<unknown>(null);
  const [resolved, setResolved] = useState<Record<string, ResolvedExercise>>({});
  const [loading, setLoading] = useState(false);

  const handleValidate = async () => {
    let payload: unknown;
    try {
      payload = JSON.parse(jsonText);
    } catch {
      toast.error("Invalid JSON");
      return;
    }
    setLoading(true);
    try {
      const result = await importPlan(payload, true);
      setDryRunResult(result);
      setParsedPayload(payload);
      if (result.unknown_exercises.length === 0) {
        setStep("confirm");
      } else {
        setStep("resolve");
      }
    } catch {
      toast.error("Validation failed");
    } finally {
      setLoading(false);
    }
  };

  const handleResolve = (name: string, resolution: ResolvedExercise) => {
    setResolved((prev) => ({ ...prev, [name]: resolution }));
  };

  const allResolved =
    dryRunResult != null &&
    dryRunResult.unknown_exercises.every((ue) => resolved[ue.name] != null);

  const handleImport = async () => {
    if (!parsedPayload || !dryRunResult) return;
    setLoading(true);
    try {
      const payload = {
        ...(parsedPayload as object),
        resolved_exercises: Object.values(resolved),
      };
      const result = await importPlan(payload, false);
      if (result.commitment_id) {
        toast.success("Plan imported!");
        router.push(`/commitments/${result.commitment_id}`);
      }
    } catch {
      toast.error("Import failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-background p-4 md:p-8 max-w-2xl mx-auto">
      <div className="mb-6">
        <Link href="/commitments" className={buttonVariants({ variant: "ghost" })}>
          ← Back
        </Link>
      </div>

      <h1 className="text-2xl font-headline font-semibold text-on-surface mb-6">Import Training Plan</h1>

      {/* Step indicators */}
      <div className="flex items-center gap-2 mb-8 text-sm font-body">
        {(["validate", "resolve", "confirm"] as WizardStep[]).map((s, i) => (
          <div key={s} className="flex items-center gap-2">
            {i > 0 && <span className="text-outline/40">→</span>}
            <span className={`px-3 py-1 rounded-full ${step === s ? "bg-primary text-on-primary" : "bg-surface-container text-on-surface-variant"}`}>
              {i + 1}. {s.charAt(0).toUpperCase() + s.slice(1)}
            </span>
          </div>
        ))}
      </div>

      {step === "validate" && (
        <div className="space-y-4">
          <textarea
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            placeholder='{"name": "My Plan", "start_date": "2026-06-01", ...}'
            rows={12}
            className="w-full bg-surface-container rounded-xl p-4 text-base md:text-sm font-mono text-on-surface border border-outline/20 focus:outline-none focus:border-primary resize-y"
          />
          <button
            onClick={handleValidate}
            disabled={loading || !jsonText.trim()}
            className="w-full bg-primary text-on-primary rounded-xl py-3 font-body text-base md:text-sm disabled:opacity-40 hover:opacity-90 transition-opacity"
          >
            {loading ? "Validating…" : "Validate"}
          </button>
        </div>
      )}

      {step === "resolve" && dryRunResult && (
        <div className="space-y-4">
          <p className="text-on-surface-variant font-body text-sm">
            {dryRunResult.unknown_exercises.length} new exercise{dryRunResult.unknown_exercises.length !== 1 ? "s" : ""} found. Review each before importing.
          </p>
          {dryRunResult.unknown_exercises.map((ue) => (
            <div key={ue.name}>
              {resolved[ue.name] ? (
                <div className="bg-surface-container rounded-xl p-4 flex items-center justify-between">
                  <span className="font-body text-on-surface text-sm">{ue.name}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-streak-hit text-xs font-body">✓ Resolved</span>
                    <button onClick={() => setResolved((p) => { const n = {...p}; delete n[ue.name]; return n; })} className="text-xs text-outline hover:text-on-surface font-body">Edit</button>
                  </div>
                </div>
              ) : (
                <ExerciseResolutionCard
                  unknown={ue}
                  exercises={exercises}
                  onResolve={(res) => handleResolve(ue.name, res)}
                />
              )}
            </div>
          ))}
          <button
            onClick={() => setStep("confirm")}
            disabled={!allResolved}
            className="w-full bg-primary text-on-primary rounded-xl py-3 font-body text-base md:text-sm disabled:opacity-40 hover:opacity-90 transition-opacity"
          >
            Next →
          </button>
        </div>
      )}

      {step === "confirm" && dryRunResult && (
        <div className="space-y-4">
          <div className="bg-surface-container rounded-xl p-4 space-y-2">
            <div className="flex justify-between text-sm font-body">
              <span className="text-on-surface-variant">Workout days</span>
              <span className="text-on-surface">{dryRunResult.workout_days}</span>
            </div>
            <div className="flex justify-between text-sm font-body">
              <span className="text-on-surface-variant">Rest days</span>
              <span className="text-on-surface">{dryRunResult.rest_days}</span>
            </div>
            <div className="flex justify-between text-sm font-body">
              <span className="text-on-surface-variant">Exercises</span>
              <span className="text-on-surface">
                {dryRunResult.exercise_count}
                {Object.keys(resolved).length > 0 && ` (${Object.keys(resolved).length} new)`}
              </span>
            </div>
          </div>
          <button
            onClick={handleImport}
            disabled={loading}
            className="w-full bg-primary text-on-primary rounded-xl py-3 font-body text-base md:text-sm disabled:opacity-40 hover:opacity-90 transition-opacity"
          >
            {loading ? "Importing…" : "Import Plan"}
          </button>
          <button onClick={() => setStep("validate")} className="w-full text-on-surface-variant font-body text-sm hover:text-on-surface transition-colors">
            ← Start over
          </button>
        </div>
      )}
    </main>
  );
}
```

- [ ] **Step 2: Run frontend tests**

```bash
cd web && npm test -- --run 2>&1 | tail -20
```

Expected: all passing.

- [ ] **Step 3: Commit**

```bash
git add web/app/commitments/import/page.tsx
git commit -m "feat(web): rewrite import page as 3-step wizard with exercise resolution"
```

---

### Task 10: Plan CRUD editor page

**Files:**
- Create: `web/app/commitments/[id]/edit/page.tsx`
- Modify: `web/app/commitments/[id]/page.tsx` (add Edit link)

- [ ] **Step 1: Create the edit page**

Create `web/app/commitments/[id]/edit/page.tsx`:

```typescript
"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { useCommitments } from "@/hooks/use-commitments";
import type { CommitmentResponse, ScheduleResponse, ScheduleDay } from "@/lib/types";
import { toast } from "sonner";

function ExercisePicker({
  exercises,
  selected,
  onConfirm,
  onCancel,
}: {
  exercises: Array<{ id: string; name: string; sets: number | null }>;
  selected: string[];
  onConfirm: (ids: string[]) => void;
  onCancel: () => void;
}) {
  const [checked, setChecked] = useState<Set<string>>(new Set(selected));

  const toggle = (id: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  return (
    <div className="bg-surface-container-high rounded-xl p-4 space-y-3 border border-outline/20">
      <p className="text-sm font-body text-on-surface-variant">Select exercises for this day:</p>
      <div className="space-y-2">
        {exercises.map((ex) => (
          <label key={ex.id} className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={checked.has(ex.id)}
              onChange={() => toggle(ex.id)}
              className="w-4 h-4"
            />
            <span className="font-body text-sm text-on-surface">
              {ex.name}{ex.sets ? ` (${ex.sets} sets)` : ""}
            </span>
          </label>
        ))}
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => onConfirm(Array.from(checked))}
          disabled={checked.size === 0}
          className="flex-1 bg-primary text-on-primary rounded-lg py-2 text-base md:text-sm font-body disabled:opacity-40"
        >
          Confirm
        </button>
        <button onClick={onCancel} className="flex-1 bg-surface-container rounded-lg py-2 text-base md:text-sm font-body text-on-surface-variant">
          Cancel
        </button>
      </div>
    </div>
  );
}

export default function CommitmentEditPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { fetchById, getSchedule, swapDay, updateDayExercises } = useCommitments();
  const [commitment, setCommitment] = useState<CommitmentResponse | null>(null);
  const [schedule, setSchedule] = useState<ScheduleResponse | null>(null);
  const [pickerDay, setPickerDay] = useState<ScheduleDay | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    const c = await fetchById(id);
    setCommitment(c);
    const s = await getSchedule(id);
    setSchedule(s);
  };

  useEffect(() => {
    load().catch(() => {});
  }, [id]);

  if (!commitment || !schedule) {
    return (
      <main className="min-h-screen bg-background p-4 md:p-8 max-w-2xl mx-auto">
        <div className="h-48 bg-surface-container rounded-2xl animate-pulse" />
      </main>
    );
  }

  const handleMakeWorkout = async (day: ScheduleDay, exerciseIds: string[]) => {
    setLoading(true);
    try {
      await swapDay(id, day.date, "to_workout", exerciseIds);
      await load();
      toast.success("Converted to workout day");
    } catch {
      toast.error("Failed to update day");
    } finally {
      setLoading(false);
      setPickerDay(null);
    }
  };

  const handleMakeRest = async (day: ScheduleDay) => {
    if (!confirm(`Convert ${day.date} to a rest day? This will delete any pending logs.`)) return;
    setLoading(true);
    try {
      await swapDay(id, day.date, "to_rest", []);
      await load();
      toast.success("Converted to rest day");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to update day";
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleEditExercises = async (day: ScheduleDay, exerciseIds: string[]) => {
    if (!day.entry_id) return;
    setLoading(true);
    try {
      await updateDayExercises(id, day.entry_id, exerciseIds);
      await load();
      toast.success("Exercises updated");
    } catch {
      toast.error("Failed to update exercises");
    } finally {
      setLoading(false);
      setPickerDay(null);
    }
  };

  // Group days by week
  const weeks: ScheduleDay[][] = [];
  schedule.days.forEach((day, i) => {
    const weekIdx = Math.floor(i / 7);
    if (!weeks[weekIdx]) weeks[weekIdx] = [];
    weeks[weekIdx].push(day);
  });

  const allExercises = commitment.exercises;

  return (
    <main className="min-h-screen bg-background p-4 md:p-8 max-w-2xl mx-auto">
      <div className="mb-6">
        <Link href={`/commitments/${id}`} className={buttonVariants({ variant: "ghost" })}>
          ← Back
        </Link>
      </div>

      <h1 className="text-2xl font-headline font-semibold text-on-surface mb-1">
        {commitment.name}
      </h1>
      <p className="text-on-surface-variant text-sm font-body mb-6">
        {commitment.start_date} → {commitment.end_date}
      </p>

      <div className="space-y-6">
        {weeks.map((week, wi) => (
          <div key={wi} className="space-y-2">
            <h2 className="text-xs font-body text-on-surface-variant uppercase tracking-wide">Week {wi + 1}</h2>
            {week.map((day) => {
              const isRest = day.status === "rest";
              const isPast = day.date < new Date().toISOString().slice(0, 10);
              const isHitMiss = day.status === "hit" || day.status === "miss";

              return (
                <div key={day.date}>
                  <div className={`bg-surface-container rounded-xl p-3 flex items-center justify-between ${isRest ? "opacity-60" : ""}`}>
                    <div>
                      <p className="text-sm font-body text-on-surface">{day.date}</p>
                      {!isRest && (
                        <p className="text-xs text-on-surface-variant font-body mt-0.5">
                          {day.exercises.map((e) => e.name).join(", ")}
                        </p>
                      )}
                      {isRest && <p className="text-xs text-outline font-body mt-0.5">Rest</p>}
                    </div>
                    {!isHitMiss && !isPast && (
                      <div className="flex gap-2">
                        {isRest ? (
                          <button
                            onClick={() => setPickerDay(day)}
                            disabled={loading}
                            className="text-xs bg-primary-container text-on-primary-container rounded-full px-3 py-1 font-body hover:bg-primary hover:text-on-primary transition-colors disabled:opacity-40"
                          >
                            Make workout
                          </button>
                        ) : (
                          <>
                            <button
                              onClick={() => setPickerDay(day)}
                              disabled={loading}
                              className="text-xs bg-surface-container-high text-on-surface-variant rounded-full px-3 py-1 font-body hover:text-on-surface transition-colors disabled:opacity-40"
                            >
                              Edit
                            </button>
                            <button
                              onClick={() => handleMakeRest(day)}
                              disabled={loading}
                              className="text-xs text-outline rounded-full px-3 py-1 font-body hover:text-error transition-colors disabled:opacity-40"
                            >
                              Make rest
                            </button>
                          </>
                        )}
                      </div>
                    )}
                    {isHitMiss && (
                      <span className={`text-xs font-body ${day.status === "hit" ? "text-streak-hit" : "text-error"}`}>
                        {day.status}
                      </span>
                    )}
                  </div>

                  {pickerDay?.date === day.date && (
                    <div className="mt-2">
                      <ExercisePicker
                        exercises={allExercises}
                        selected={day.exercises.map((e) => e.exercise_id)}
                        onConfirm={(ids) => {
                          if (isRest) {
                            handleMakeWorkout(day, ids);
                          } else {
                            handleEditExercises(day, ids);
                          }
                        }}
                        onCancel={() => setPickerDay(null)}
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </main>
  );
}
```

- [ ] **Step 2: Add Edit link to detail page**

In `web/app/commitments/[id]/page.tsx`, add an "Edit plan" link in the header section for `kind === "plan"`. After line 129 (`{commitment.start_date} → ...`):

```typescript
          {commitment.kind === "plan" && (
            <Link
              href={`/commitments/${id}/edit`}
              className="text-sm text-primary font-body hover:underline"
            >
              Edit plan →
            </Link>
          )}
```

- [ ] **Step 3: Run frontend tests**

```bash
cd web && npm test -- --run 2>&1 | tail -20
```

Expected: all passing.

- [ ] **Step 4: Run full backend tests**

```bash
make test 2>&1 | tail -20
```

Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add web/app/commitments/[id]/edit/page.tsx web/app/commitments/[id]/page.tsx
git commit -m "feat(web): add plan CRUD editor page with day-swap and exercise picker"
```
