---\nstatus: shipped\ncreated: 2026-05-18\nshipped: 2026-05-18\n---

# Commitment Spec A: Inline Exercise Log Form — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the empty "Done" POST with an inline expand form that collects reps/sets/weight before logging, and show a logged-value summary after. Progression chart will then display real data.

**Architecture:** Backend gains `last_logged` on `CommitmentExercise` responses via a single batch query. Frontend `ExerciseRow` gains local expand state with metric-matched fields. No new DB tables; no new endpoints.

**Tech Stack:** FastAPI, SQLAlchemy async, pytest, Next.js 15, React 19, TypeScript, Vitest

**Prerequisite:** Spec B must be shipped first (exercise library + per-day schedule).

---

## File Map

| File | Change |
|---|---|
| `src/api/routes/commitments.py` | Add `LastLoggedValues` + `last_logged` to `ExerciseResponse`; add `_fetch_last_logged_batch` helper; populate in list + detail endpoints |
| `tests/test_commitments.py` | Add tests for `last_logged` field |
| `web/lib/types.ts` | Add `LastLoggedValues`; extend `CommitmentExercise` |
| `web/components/dashboard/commitment-list.tsx` | Rewrite `ExerciseRow` with inline expand form |

---

### Task 1: Backend — `last_logged` on exercise responses

**Files:**
- Modify: `src/api/routes/commitments.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_commitments.py`:

```python
@pytest.mark.asyncio
async def test_exercise_response_has_last_logged_null_when_no_logs(test_client, api_key_headers):
    """last_logged is null on exercises with no logs."""
    from datetime import date, timedelta
    today = date.today()
    payload = {
        "name": "Morning Routine",
        "kind": "routine",
        "exercises": [
            {"name": "Push-ups", "target": 20, "metric": "reps", "progression_metric": "reps"},
        ],
        "start_date": str(today),
        "end_date": str(today + timedelta(days=6)),
    }
    resp = await test_client.post("/v1/commitments", json=payload, headers=api_key_headers)
    assert resp.status_code == 201
    commitment_id = resp.json()["id"]

    detail = await test_client.get(f"/v1/commitments/{commitment_id}", headers=api_key_headers)
    exercises = detail.json()["exercises"]
    assert len(exercises) == 1
    assert exercises[0]["last_logged"] is None


@pytest.mark.asyncio
async def test_exercise_response_has_last_logged_after_log(test_client, api_key_headers):
    """last_logged is populated with most recent log values."""
    from datetime import date, timedelta
    today = date.today()
    payload = {
        "name": "Morning Routine",
        "kind": "routine",
        "exercises": [
            {"name": "Squat", "target": 5, "metric": "reps", "progression_metric": "kg"},
        ],
        "start_date": str(today),
        "end_date": str(today + timedelta(days=6)),
    }
    resp = await test_client.post("/v1/commitments", json=payload, headers=api_key_headers)
    commitment_id = resp.json()["id"]
    exercise_id = resp.json()["exercises"][0]["id"]

    log_resp = await test_client.post(
        f"/v1/commitments/{commitment_id}/exercises/{exercise_id}/log",
        json={"reps": 5, "sets": 3, "weight_kg": 100.0},
        headers=api_key_headers,
    )
    assert log_resp.status_code == 201

    detail = await test_client.get(f"/v1/commitments/{commitment_id}", headers=api_key_headers)
    exercises = detail.json()["exercises"]
    last = exercises[0]["last_logged"]
    assert last is not None
    assert last["reps"] == 5
    assert last["sets"] == 3
    assert last["weight_kg"] == 100.0
    assert last["log_date"] == str(today)
```

- [ ] **Step 2: Run to confirm they fail**

```bash
make test -k "test_exercise_response_has_last_logged" 2>&1 | tail -20
```

Expected: 2 failures (`last_logged` field missing).

- [ ] **Step 3: Add `LastLoggedValues` Pydantic model and extend `ExerciseResponse`**

In `src/api/routes/commitments.py`, add after the `ExerciseLogCreate` class:

```python
class LastLoggedValues(BaseModel):
    reps: int | None
    sets: int | None
    weight_kg: float | None
    duration_minutes: float | None
    log_date: str
```

Modify `ExerciseResponse` to add `last_logged`:

```python
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
    last_logged: LastLoggedValues | None = None
```

- [ ] **Step 4: Add `_fetch_last_logged_batch` helper**

Add this function after `_exercise_to_response`:

```python
async def _fetch_last_logged_batch(
    session: AsyncSession,
    exercise_ids: list[str],
) -> dict[str, LastLoggedValues]:
    """Return the most recent active log per exercise_id (batch, no N+1).

    Uses a subquery to find the latest log_date per exercise, then fetches
    the matching row. Works on both SQLite (tests) and PostgreSQL.
    """
    if not exercise_ids:
        return {}

    from sqlalchemy import func as sqlfunc

    # Subquery: latest log_date per exercise_id
    sub = (
        select(
            CommitmentExerciseLog.exercise_id,
            sqlfunc.max(CommitmentExerciseLog.log_date).label("max_date"),
        )
        .where(
            and_(
                CommitmentExerciseLog.exercise_id.in_(exercise_ids),
                CommitmentExerciseLog.deleted_at.is_(None),
            )
        )
        .group_by(CommitmentExerciseLog.exercise_id)
        .subquery()
    )

    stmt = (
        select(CommitmentExerciseLog)
        .join(
            sub,
            and_(
                CommitmentExerciseLog.exercise_id == sub.c.exercise_id,
                CommitmentExerciseLog.log_date == sub.c.max_date,
            ),
        )
        .where(CommitmentExerciseLog.deleted_at.is_(None))
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    out: dict[str, LastLoggedValues] = {}
    for log in rows:
        out[str(log.exercise_id)] = LastLoggedValues(
            reps=log.reps,
            sets=log.sets,
            weight_kg=log.weight_kg,
            duration_minutes=log.duration_minutes,
            log_date=str(log.log_date),
        )
    return out
```

- [ ] **Step 5: Update `_exercise_to_response` to accept `last_logged`**

```python
def _exercise_to_response(
    ex: CommitmentExercise,
    logged_today: bool = False,
    last_logged: LastLoggedValues | None = None,
) -> ExerciseResponse:
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
        last_logged=last_logged,
    )
```

- [ ] **Step 6: Populate `last_logged` in `_commitment_to_response`**

`_commitment_to_response` is a sync helper. It needs `last_logged_map` passed in. Change its signature:

```python
def _commitment_to_response(
    commitment: Commitment,
    entries: list[CommitmentEntry] | None = None,
    today: date | None = None,
    exercises: list[CommitmentExercise] | None = None,
    logged_exercise_ids_today: set[str] | None = None,
    last_logged_map: dict[str, LastLoggedValues] | None = None,
) -> CommitmentResponse:
```

And in the `exercises` line:

```python
        exercises=[
            _exercise_to_response(
                ex,
                str(ex.id) in logged_ids,
                (last_logged_map or {}).get(str(ex.id)),
            )
            for ex in ex_list
        ],
```

- [ ] **Step 7: Fetch and pass `last_logged_map` in both list and detail endpoints**

In `list_commitments`, after fetching `logged_ids`, add:

```python
        last_logged_map: dict[str, LastLoggedValues] = {}
        if exercises:
            exercise_ids = [str(ex.id) for ex in exercises]
            last_logged_map = await _fetch_last_logged_batch(session, exercise_ids)
        responses.append(_commitment_to_response(c, entries, today, exercises, logged_ids, last_logged_map))
```

In `get_commitment`, same pattern:

```python
    last_logged_map: dict[str, LastLoggedValues] = {}
    if exercises:
        exercise_ids = [str(ex.id) for ex in exercises]
        last_logged_map = await _fetch_last_logged_batch(session, exercise_ids)

    return _commitment_to_response(commitment, entries, today, exercises, logged_ids, last_logged_map)
```

- [ ] **Step 8: Run the failing tests**

```bash
make test -k "test_exercise_response_has_last_logged" 2>&1 | tail -20
```

Expected: 2 passed.

- [ ] **Step 9: Run full test suite**

```bash
make test 2>&1 | tail -20
```

Expected: all passing.

- [ ] **Step 10: Commit**

```bash
git add src/api/routes/commitments.py tests/test_commitments.py
git commit -m "feat(api): add last_logged to exercise responses via batch query"
```

---

### Task 2: Frontend types

**Files:**
- Modify: `web/lib/types.ts`

- [ ] **Step 1: Add `LastLoggedValues` and extend `CommitmentExercise`**

Add after the `CommitmentExerciseLog` interface:

```typescript
export interface LastLoggedValues {
  reps: number | null;
  sets: number | null;
  weight_kg: number | null;
  duration_minutes: number | null;
  log_date: string;
}
```

Extend `CommitmentExercise`:

```typescript
export interface CommitmentExercise {
  id: string;
  commitment_id: string;
  name: string;
  sets: number | null;
  target: number;
  metric: string;
  progression_metric: string;
  position: number;
  logged_today: boolean;
  last_logged: LastLoggedValues | null;  // add this field
}
```

- [ ] **Step 2: Type check**

```bash
cd web && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/lib/types.ts
git commit -m "feat(web): add LastLoggedValues type and last_logged to CommitmentExercise"
```

---

### Task 3: Inline log form in `ExerciseRow`

**Files:**
- Modify: `web/components/dashboard/commitment-list.tsx`

- [ ] **Step 1: Write a Vitest test for the inline form**

In the appropriate frontend test file (check `web/__tests__/` or `web/components/__tests__/`), add:

```typescript
import { render, screen, fireEvent } from "@testing-library/react";
import { ExerciseRow } from "@/components/dashboard/commitment-list";  // adjust if not exported

// NOTE: ExerciseRow needs to be exported for this test — add `export` to the function declaration

const mockExercise = {
  id: "ex-1",
  commitment_id: "c-1",
  name: "Squat",
  sets: 3,
  target: 5,
  metric: "reps",
  progression_metric: "kg",
  position: 0,
  logged_today: false,
  last_logged: null,
};

test("ExerciseRow expands form on Log click", () => {
  const onLog = vi.fn().mockResolvedValue(undefined);
  render(
    <ExerciseRow
      exercise={mockExercise}
      isLogged={false}
      isRestDay={false}
      onLog={onLog}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: /log squat/i }));
  expect(screen.getByLabelText(/reps/i)).toBeInTheDocument();
});

test("ExerciseRow shows kg field for kg metric", () => {
  const onLog = vi.fn().mockResolvedValue(undefined);
  render(
    <ExerciseRow
      exercise={{ ...mockExercise, metric: "kg", progression_metric: "kg" }}
      isLogged={false}
      isRestDay={false}
      onLog={onLog}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: /log squat/i }));
  expect(screen.getByLabelText(/weight/i)).toBeInTheDocument();
});

test("ExerciseRow shows summary when already logged", () => {
  render(
    <ExerciseRow
      exercise={{ ...mockExercise, logged_today: true, last_logged: { reps: 5, sets: 3, weight_kg: 100, duration_minutes: null, log_date: "2026-05-18" } }}
      isLogged={true}
      isRestDay={false}
      onLog={vi.fn()}
    />
  );
  expect(screen.getByText(/3 × 5/)).toBeInTheDocument();
  expect(screen.getByText(/100/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to confirm fail**

```bash
cd web && npm test -- --run 2>&1 | grep -E "FAIL|PASS|Error" | head -20
```

- [ ] **Step 3: Rewrite `ExerciseRow` in `commitment-list.tsx`**

Replace the `ExerciseRow` function (lines 275–324) with:

```typescript
export function ExerciseRow({
  exercise,
  isLogged,
  isRestDay,
  onLog,
}: {
  exercise: CommitmentExercise;
  isLogged: boolean;
  isRestDay: boolean;
  onLog: (exerciseId: string, data: { reps?: number; sets?: number; weight_kg?: number; duration_minutes?: number }) => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [pending, setPending] = useState(false);
  const [reps, setReps] = useState<number>(exercise.last_logged?.reps ?? exercise.target);
  const [sets, setSets] = useState<number | null>(exercise.last_logged?.sets ?? exercise.sets ?? null);
  const [weightKg, setWeightKg] = useState<number | null>(exercise.last_logged?.weight_kg ?? null);
  const [durationMinutes, setDurationMinutes] = useState<number | null>(
    exercise.last_logged?.duration_minutes ?? null
  );

  const showReps = exercise.metric === "reps" || exercise.progression_metric === "reps";
  const showKg = exercise.metric === "kg" || exercise.progression_metric === "kg";
  const showMinutes = exercise.metric === "minutes" || exercise.progression_metric === "minutes";
  const showSeconds = exercise.metric === "seconds" || exercise.progression_metric === "seconds";

  const handleConfirm = async () => {
    if (pending) return;
    setPending(true);
    try {
      await onLog(exercise.id, {
        reps: showReps ? reps : undefined,
        sets: sets ?? undefined,
        weight_kg: showKg ? (weightKg ?? undefined) : undefined,
        duration_minutes: (showMinutes || showSeconds) ? (durationMinutes ?? undefined) : undefined,
      });
      setExpanded(false);
    } catch {
      // toast shown by hook
    } finally {
      setPending(false);
    }
  };

  const loggedSummary = () => {
    if (!exercise.last_logged) return null;
    const { reps: r, sets: s, weight_kg: w } = exercise.last_logged;
    const parts: string[] = [];
    if (s != null && r != null) parts.push(`${s} × ${r}`);
    else if (r != null) parts.push(`${r} reps`);
    if (w != null) parts.push(`@ ${w} kg`);
    return parts.join(" ") || null;
  };

  return (
    <div className="py-1.5 space-y-2">
      <div className="flex items-center justify-between">
        <span className="font-body text-sm text-on-surface">{exercise.name}</span>
        <div className="flex items-center gap-2">
          <span className="text-on-surface-variant text-sm font-body">
            {exercise.sets != null ? `${exercise.sets} × ` : ""}{exercise.target} {exercise.metric}
          </span>
          {isRestDay ? (
            <span className="text-outline text-xs font-body">rest</span>
          ) : isLogged ? (
            <div className="flex items-center gap-1">
              <Check className="w-4 h-4 text-streak-hit" aria-label="Done" />
              {loggedSummary() && (
                <span className="text-xs text-on-surface-variant font-body">{loggedSummary()}</span>
              )}
            </div>
          ) : expanded ? (
            <button
              onClick={() => setExpanded(false)}
              className="text-xs text-outline font-body"
            >
              Cancel
            </button>
          ) : (
            <button
              onClick={() => setExpanded(true)}
              disabled={pending}
              aria-label={`Log ${exercise.name}`}
              className="bg-primary-container text-on-primary-container rounded-full px-3 h-8 text-base md:text-sm font-body
                hover:bg-primary hover:text-on-primary active:scale-95 transition-all
                disabled:opacity-50 cursor-pointer"
            >
              Log
            </button>
          )}
        </div>
      </div>

      {expanded && !isLogged && !isRestDay && (
        <div className="bg-surface-container-high rounded-xl p-3 space-y-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {showReps && (
              <div>
                <label className="text-xs text-on-surface-variant font-body block mb-1" htmlFor={`reps-${exercise.id}`}>
                  Reps
                </label>
                <input
                  id={`reps-${exercise.id}`}
                  type="number"
                  min={0}
                  value={reps}
                  onChange={(e) => setReps(Number(e.target.value))}
                  className="w-full bg-surface rounded-lg px-3 py-2 text-base md:text-sm text-on-surface border border-outline/20 focus:outline-none focus:border-primary"
                />
              </div>
            )}
            {showKg && (
              <div>
                <label className="text-xs text-on-surface-variant font-body block mb-1" htmlFor={`weight-${exercise.id}`}>
                  Weight (kg)
                </label>
                <input
                  id={`weight-${exercise.id}`}
                  type="number"
                  min={0}
                  step={0.5}
                  value={weightKg ?? ""}
                  onChange={(e) => setWeightKg(e.target.value ? Number(e.target.value) : null)}
                  className="w-full bg-surface rounded-lg px-3 py-2 text-base md:text-sm text-on-surface border border-outline/20 focus:outline-none focus:border-primary"
                />
              </div>
            )}
            {(showMinutes || showSeconds) && (
              <div>
                <label className="text-xs text-on-surface-variant font-body block mb-1" htmlFor={`duration-${exercise.id}`}>
                  {showSeconds ? "Seconds" : "Minutes"}
                </label>
                <input
                  id={`duration-${exercise.id}`}
                  type="number"
                  min={0}
                  value={durationMinutes ?? ""}
                  onChange={(e) => setDurationMinutes(e.target.value ? Number(e.target.value) : null)}
                  className="w-full bg-surface rounded-lg px-3 py-2 text-base md:text-sm text-on-surface border border-outline/20 focus:outline-none focus:border-primary"
                />
              </div>
            )}
            <div>
              <label className="text-xs text-on-surface-variant font-body block mb-1" htmlFor={`sets-${exercise.id}`}>
                Sets (optional)
              </label>
              <input
                id={`sets-${exercise.id}`}
                type="number"
                min={1}
                value={sets ?? ""}
                onChange={(e) => setSets(e.target.value ? Number(e.target.value) : null)}
                className="w-full bg-surface rounded-lg px-3 py-2 text-base md:text-sm text-on-surface border border-outline/20 focus:outline-none focus:border-primary"
              />
            </div>
          </div>
          <button
            onClick={handleConfirm}
            disabled={pending}
            className="w-full bg-primary text-on-primary rounded-lg py-2 text-base md:text-sm font-body disabled:opacity-40 hover:opacity-90 transition-opacity"
          >
            {pending ? "Logging…" : "Confirm"}
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Update `MultiExerciseCommitmentCard` to pass the new `onLog` signature**

In `MultiExerciseCommitmentCard`, the `onLog` prop for `ExerciseRow` needs updating. Change:

```typescript
onLog={(exerciseId) => onLogExercise(commitment.id, exerciseId)}
```

to:

```typescript
onLog={(exerciseId, data) => onLogExercise(commitment.id, exerciseId, data)}
```

Update the `onLogExercise` prop type on `MultiExerciseCommitmentCard`:

```typescript
onLogExercise: (commitmentId: string, exerciseId: string, data: { reps?: number; sets?: number; weight_kg?: number; duration_minutes?: number }) => Promise<void>
```

- [ ] **Step 5: Update `CommitmentList` to pass data through**

In the `CommitmentList` component, the `logExercise` call currently passes `{}`. Update it to pass `data`:

```typescript
onLogExercise={async (commitmentId, exerciseId, data) => {
  await logExercise(commitmentId, exerciseId, data);
}}
```

- [ ] **Step 6: Run frontend tests**

```bash
cd web && npm test -- --run 2>&1 | tail -20
```

Expected: all passing including the new ExerciseRow tests.

- [ ] **Step 7: Run full backend tests**

```bash
make test 2>&1 | tail -20
```

Expected: all passing.

- [ ] **Step 8: Commit**

```bash
git add web/components/dashboard/commitment-list.tsx
git commit -m "feat(web): inline expand log form on ExerciseRow with metric-matched fields"
```
