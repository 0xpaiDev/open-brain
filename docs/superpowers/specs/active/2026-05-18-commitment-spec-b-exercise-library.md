# Spec B: Exercise Library + Per-Day Schedule + Import Wizard + Plan CRUD

**Date:** 2026-05-18  
**Status:** Active  
**Depends on:** Spec 0 (chart fix) recommended first  
**Blocks:** Spec A (inline log form + day-swap)

---

## Problem

1. The import service discards per-day exercise assignments — all exercises are shown on every workout day regardless of which day they were scheduled for.
2. No global exercise library exists — the same exercise name can be imported with different spellings across plans with no deduplication.
3. No way to edit a plan after import — rest/workout days and exercise assignments are fixed.
4. No import review step for new exercises — targets and metrics come entirely from the JSON with no validation UI.

---

## Database

The SQL migration has already been run manually on Supabase. The Alembic migration file `0020_exercise_library.py` exists but only covers the `exercises` table and `commitment_exercises.exercise_id` FK. A second migration `0021_commitment_entry_exercises.py` must be created for the junction table.

### `exercises` (already migrated)
```
id            UUID PK
name          VARCHAR(100) NOT NULL  -- normalised: strip().lower()
display_name  VARCHAR(100) NOT NULL  -- original casing, first insert wins
created_at    TIMESTAMPTZ
UNIQUE(name)
RLS enabled
```

### `commitment_exercises.exercise_id` (already migrated)
Nullable FK → `exercises.id` ON DELETE SET NULL.

### `commitment_entry_exercises` (already migrated in Supabase, needs Alembic file)
```
id             UUID PK
commitment_id  UUID FK → commitments.id CASCADE
entry_id       UUID FK → commitment_entries.id CASCADE
exercise_id    UUID FK → commitment_exercises.id CASCADE
created_at     TIMESTAMPTZ
UNIQUE(entry_id, exercise_id)
INDEX(commitment_id, entry_id)
RLS enabled
```

---

## ORM Models (`src/core/models.py`)

The `Exercise` model and `CommitmentExercise.exercise_id` FK were partially written in the earlier session — verify and keep them.

Add `CommitmentEntryExercise`:

```python
class CommitmentEntryExercise(Base):
    __tablename__ = "commitment_entry_exercises"
    id: UUID PK, default uuid4
    commitment_id: UUID FK → commitments.id CASCADE
    entry_id: UUID FK → commitment_entries.id CASCADE
    exercise_id: UUID FK → commitment_exercises.id CASCADE
    created_at: DateTime server_default now()
    UniqueConstraint("entry_id", "exercise_id", name="uq_entry_exercise")
    Index("ix_entry_exercises_commitment_entry", "commitment_id", "entry_id")
```

Add relationships:
- `CommitmentEntry.entry_exercises` → list[CommitmentEntryExercise] cascade all/delete-orphan
- `CommitmentExercise.entry_exercises` → list[CommitmentEntryExercise] passive_deletes=True

---

## Alembic Migration `0021_commitment_entry_exercises.py`

Code-only migration — the table already exists in Supabase. The migration must be written so it can run against a fresh SQLite test DB:

```python
def upgrade():
    op.create_table(
        "commitment_entry_exercises",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("commitment_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("entry_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(datetime('now'))"), nullable=False),
        sa.ForeignKeyConstraint(["commitment_id"], ["commitments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entry_id"], ["commitment_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exercise_id"], ["commitment_exercises.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("entry_id", "exercise_id", name="uq_entry_exercise"),
    )
    op.create_index("ix_entry_exercises_commitment_entry", "commitment_entry_exercises", ["commitment_id", "entry_id"])
    # RLS — Postgres only, SQLite silently ignores
    try:
        op.execute("ALTER TABLE commitment_entry_exercises ENABLE ROW LEVEL SECURITY")
    except Exception:
        pass

def downgrade():
    op.drop_index("ix_entry_exercises_commitment_entry", table_name="commitment_entry_exercises")
    op.drop_table("commitment_entry_exercises")
```

Note: `sa.text("(datetime('now'))")` is the SQLite-compatible server_default; Postgres also accepts it.

---

## Import Service (`src/api/services/commitment_import_service.py`)

### Normalisation helper
```python
def _normalise(name: str) -> str:
    return name.strip().lower()
```

### Dry-run response gains `unknown_exercises`
After collecting unique exercise names from the schedule, query `exercises` table for normalised matches. Return unmatched ones as:
```python
unknown_exercises: list[UnknownExercise]  # {name, sets, target, metric, progression_metric}
```

### Commit request gains `resolved_exercises`
```python
class ResolvedExercise(BaseModel):
    name: str                        # original name from schedule
    exercise_id: str | None = None   # set if matched to existing library entry
    display_name: str | None = None  # set if creating new
    metric: str = "reps"
    progression_metric: str = "reps"
    target: int
    sets: int | None = None
```

### Commit transaction (atomic)
1. For each resolved exercise with no `exercise_id`: insert into `exercises` (normalised name, display_name)
2. For each resolved exercise with `exercise_id`: verify it exists
3. Create `Commitment`
4. Create `CommitmentExercise` rows — link `exercise_id` to library entry
5. For each workout day: create `CommitmentEntry` + one `CommitmentEntryExercise` per exercise scheduled that day
6. Commit — rollback entire transaction on any failure

---

## New API Endpoints

### `GET /v1/exercises`
Returns `list[ExerciseResponse]` ordered by `display_name`. No auth beyond existing rate-limit decorator.

```python
class ExerciseResponse(BaseModel):
    id: str
    name: str          # normalised
    display_name: str
    created_at: str
```

### `GET /v1/commitments/{id}/schedule`
Returns full schedule for a plan commitment:

```python
class ScheduleDay(BaseModel):
    entry_id: str | None    # None = rest day
    date: str
    status: str             # "pending" | "hit" | "miss" | "rest"
    exercises: list[ExerciseRef]  # [{exercise_id, name, sets, target, metric}]

class ScheduleResponse(BaseModel):
    commitment_id: str
    days: list[ScheduleDay]  # all days from start_date to end_date inclusive
```

Validates `kind == "plan"`.

### `PATCH /v1/commitments/{id}/entries/{date}`
```python
class EntrySwapRequest(BaseModel):
    action: Literal["to_workout", "to_rest"]
    exercise_ids: list[str] = []  # required when action="to_workout"
```

- `to_workout`: validates date in range, no existing entry; creates `CommitmentEntry(status="pending")` + `CommitmentEntryExercise` rows for each exercise_id
- `to_rest`: validates entry exists and status is "pending" (refuses hit/miss); deletes entry (cascades to entry_exercises and any pending logs)

### Modified: `POST /v1/commitments/{id}/exercises/{exercise_id}/log`
Add validation: `exercise_id` must appear in `commitment_entry_exercises` for today's entry. Returns 400 "Exercise not scheduled for today" if not found. Routine commitments skip this check (all exercises valid every day).

---

## New Service: `src/api/services/schedule_service.py`

- `get_schedule(session, commitment_id, start_date, end_date) -> ScheduleResponse` — fetches all entries + their entry_exercises, fills in rest days for dates with no entry
- `swap_day(session, commitment_id, date, action, exercise_ids) -> None` — rest↔workout logic
- `update_day_exercises(session, entry_id, exercise_ids) -> None` — replace all entry_exercises for a day (used by CRUD editor)

---

## Frontend

### New hook: `web/hooks/use-exercises.ts`
- `exercises: Exercise[]`
- `refresh()` → `GET /v1/exercises`
- Auto-loads on mount, cached for the session

### Modified: `web/hooks/use-commitments.ts`
- Add `fetchById(id)` → `GET /v1/commitments/{id}` (also serves Spec 0 fix)
- Add `getSchedule(id)` → `GET /v1/commitments/{id}/schedule`
- Add `swapDay(commitmentId, date, action, exerciseIds)` → `PATCH /v1/commitments/{id}/entries/{date}`
- Add `updateDayExercises(commitmentId, entryId, exerciseIds)` → `PATCH /v1/commitments/{id}/entries/{entry_id}/exercises` body `{"exercise_ids": [...]}`

### Modified: `web/app/commitments/import/page.tsx`
Three-step wizard using local React state:

**Step 1 — Validate** (existing, extended)
- Dry-run response now includes `unknown_exercises`
- If `unknown_exercises.length === 0` → skip to step 3
- If `unknown_exercises.length > 0` → advance to step 2

**Step 2 — Resolve unknowns**
- One card per unknown exercise
- Each card: pre-filled name, fields for `display_name`, `metric`, `progression_metric`, `target`, `sets`
- "Or match existing" button opens an inline search/select from `use-exercises` list
- All cards must be resolved before "Next" is enabled

**Step 3 — Confirm & Import**
- Summary: X workout days, Y rest days, Z exercises (N new, M matched)
- Import button → POST with resolved_exercises → on success redirect to `/commitments/{id}`

### New page: `web/app/commitments/[id]/edit/page.tsx` (plan CRUD editor)
- Link from detail page header (only shown for `kind === "plan"`)
- Loads schedule via `getSchedule(id)`
- Renders day list grouped by week
- Workout day row: date, exercise chips, "Edit exercises" button
- Rest day row: date, "Rest" label, "Make workout" button
- "Edit exercises" → opens exercise picker panel (checkboxes over commitment's exercises)
- "Make workout" → opens exercise picker, on confirm calls `swapDay(..., "to_workout", selectedIds)`
- Workout → rest: confirm dialog (warns if has logs), calls `swapDay(..., "to_rest", [])`

### New types: `web/lib/types.ts`
```typescript
interface Exercise {
  id: string
  name: string
  display_name: string
  created_at: string
}

interface ScheduleDay {
  entry_id: string | null
  date: string
  status: "pending" | "hit" | "miss" | "rest"
  exercises: Array<{ exercise_id: string; name: string; sets: number | null; target: number; metric: string }>
}

interface ScheduleResponse {
  commitment_id: string
  days: ScheduleDay[]
}

interface UnknownExercise {
  name: string
  sets: number | null
  target: number
  metric: string
  progression_metric: string
}

interface ResolvedExercise {
  name: string
  exercise_id?: string
  display_name?: string
  metric: string
  progression_metric: string
  target: number
  sets?: number | null
}
```

---

## Testing

- `tests/test_commitment_import.py` — extend existing suite:
  - Dry-run with known exercises returns `unknown_exercises: []`
  - Dry-run with unknown exercises returns correct `unknown_exercises` list
  - Commit with `resolved_exercises` creates `Exercise` rows + `commitment_entry_exercises` rows
  - Re-import same hash returns existing commitment (idempotency unchanged)
  - Commit without resolving all unknowns returns 422

- `tests/test_commitment_schedule.py` (new):
  - `GET /schedule` returns correct days including rest days
  - `PATCH entries/{date}` to_workout creates entry + entry_exercises
  - `PATCH entries/{date}` to_rest on pending entry deletes it
  - `PATCH entries/{date}` to_rest on hit entry returns 400
  - Log endpoint rejects exercise not in today's entry_exercises (plan kind)
  - Log endpoint allows any exercise on routine kind (no entry_exercise check)

- Frontend: `cd web && npm test` — no regressions
