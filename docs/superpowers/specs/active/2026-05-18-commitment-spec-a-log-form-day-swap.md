# Spec A: Inline Exercise Log Form + Day-Swap UI

**Date:** 2026-05-18  
**Status:** Active  
**Depends on:** Spec B (exercise library + per-day schedule) must be shipped first

---

## Problem

1. The "Done" button on exercise rows fires an empty POST — no reps, sets, or weight are captured. The progression chart is permanently empty as a result.
2. No UI exists to swap a rest day ↔ workout day after a plan is imported.

---

## Inline Log Form

### Behaviour
Clicking "Log" on an `ExerciseRow` expands the row in-place (no modal). The expanded state shows only the fields relevant to the exercise's `metric` and `progression_metric`:

| metric / progression_metric | Fields shown |
|---|---|
| `reps` | reps (required), sets (optional) |
| `kg` | weight_kg (required), reps (optional), sets (optional) |
| `minutes` | duration_minutes (required) |
| `seconds` | duration_minutes mapped to seconds display, required |

**Default values:**
- `reps` defaults to `exercise.target`
- `weight_kg` defaults to the last logged `weight_kg` for this exercise (fetched from the most recent `CommitmentExerciseLog` for this exercise — included in the API response, see below)
- `sets` defaults to `exercise.sets` if set

**Confirm flow:**
- "Confirm" button fires `logExercise(commitmentId, exerciseId, { reps, sets, weight_kg, duration_minutes })`
- On success: row collapses, shows check + summary line (e.g. "3 × 10 @ 15 kg")
- On error: toast, form stays open

**Already-logged state:**
- Shows check icon + summary of logged values
- No re-log from the card — to correct a log, go to detail page (out of scope for this spec)

### Input sizing
All `<input>` elements use `text-base md:text-sm` per the mobile font-size footgun rule.

---

## Backend Changes

### `GET /v1/commitments` and `GET /v1/commitments/{id}` responses
`CommitmentExercise` in the response gains one new field:
```python
last_logged: LastLoggedValues | None
```
```python
class LastLoggedValues(BaseModel):
    reps: int | None
    sets: int | None
    weight_kg: float | None
    duration_minutes: float | None
    log_date: str
```

This must be computed with a **single batch query** to avoid N+1: `SELECT DISTINCT ON (exercise_id) * FROM commitment_exercise_logs WHERE exercise_id IN (...) AND deleted_at IS NULL ORDER BY exercise_id, log_date DESC, created_at DESC`. On SQLite (tests) use a subquery with `MAX(log_date)` grouped by `exercise_id` instead of `DISTINCT ON`. Abstract into a helper in `src/api/routes/commitments.py`.

No new endpoints needed.

---

## Day-Swap UI

Day-swap lives on the **plan CRUD editor page** (`/commitments/[id]/edit`) introduced in Spec B — not on the dashboard card. The dashboard card remains read-only.

The editor page (specified in Spec B) handles both directions:
- Rest → workout: exercise picker → `swapDay(..., "to_workout", selectedIds)`  
- Workout → rest: confirm dialog → `swapDay(..., "to_rest", [])`

This spec has no additional backend work beyond what Spec B defines. The only frontend addition here is ensuring the exercise picker pre-selects the exercises already assigned to a day when editing an existing workout day.

---

## Frontend Changes

### `web/components/dashboard/commitment-list.tsx`

**`ExerciseRow`** gains:
- `lastLogged: LastLoggedValues | null` prop
- Local state: `expanded: boolean`, `reps: number`, `sets: number | null`, `weightKg: number | null`, `durationMinutes: number | null`
- On mount/exercise change: initialise fields from `lastLogged` (or `exercise.target` / `exercise.sets`)
- "Log" button (renamed from "Done") toggles `expanded = true`
- Expanded: renders relevant input fields + "Confirm" + "Cancel" buttons
- Confirm: calls `onLog(exerciseId, { reps, sets, weight_kg: weightKg, duration_minutes: durationMinutes })`

**`MultiExerciseCommitmentCard`** updated signature:
```typescript
onLogExercise: (commitmentId: string, exerciseId: string, data: ExerciseLogData) => Promise<void>
```

### `web/hooks/use-commitments.ts`
`logExercise` already accepts the full data object — no change needed.

### `web/lib/types.ts`
```typescript
interface LastLoggedValues {
  reps: number | null
  sets: number | null
  weight_kg: number | null
  duration_minutes: number | null
  log_date: string
}

// CommitmentExercise gains:
last_logged: LastLoggedValues | null
```

---

## Testing

**Backend (`tests/test_commitments.py` extensions):**
- Log endpoint with `reps=10, sets=3, weight_kg=60` → stored correctly, progression endpoint returns point with value=60 (if progression_metric="kg")
- `GET /v1/commitments/{id}` response includes `last_logged` on each exercise after a log exists
- `last_logged` is null when no logs exist for the exercise
- Log endpoint rejects exercise not in today's `commitment_entry_exercises` (plan kind) — covered by Spec B tests, just verify integration

**Frontend (`cd web && npm test`):**
- `ExerciseRow` renders "Log" button when not logged
- Clicking "Log" expands the form
- Form shows only fields matching exercise metric
- Confirm calls `onLog` with correct data shape
- After log: row shows summary, no form

**End-to-end:**
- Import a plan → log Squat with 5 reps @ 100kg → open detail page → progression chart shows one point at 100 on the y-axis
