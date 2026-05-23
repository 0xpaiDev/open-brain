---
status: shipped
created: 2026-05-18
shipped: 2026-05-23
---

# Spec 0: Commitment Progression Chart Fix

**Date:** 2026-05-18  
**Status:** Active  
**Scope:** Bug fix only — independent of Spec A and Spec B

---

## Problem

The progression chart section on `/commitments/[id]` always renders as an empty glowing skeleton. Two root causes:

1. **Commitment not found:** `useCommitments()` defaults to `status=active`. Completed/abandoned plans are absent from the list, so `commitment` state stays `null` → the skeleton never resolves → progression is never fetched.

2. **Empty log data:** The "Done" button currently POSTs `{}` (empty body), so `reps` and `weight_kg` are stored as `null`. The progression endpoint returns `points: []` per exercise. Each `ProgressionChart` renders "No logs yet" but the outer guard `progression.length > 0` passes, so the section appears — but with empty cards.

---

## Fix

### Backend — no changes required
The progression endpoint (`GET /v1/commitments/{id}/progression`) is correct. The issue is entirely frontend.

### `web/hooks/use-commitments.ts`
Add `fetchById(id: string): Promise<CommitmentResponse>` that calls `GET /v1/commitments/{id}` directly. Returns the full commitment regardless of status.

### `web/app/commitments/[id]/page.tsx`
Replace the array-lookup `useEffect` with a direct `fetchById(id)` call on mount. The page no longer depends on the commitments list being loaded or filtered correctly.

```
useEffect(() => {
  fetchById(id).then(setCommitment).catch(() => {})
}, [id])
```

Progression fetch stays as-is — it already fires once `commitment` is set and `kind` is `routine` or `plan`.

---

## What This Does Not Fix

The "No logs yet" state per exercise is correct behaviour when no logs exist. The inline log form (Spec A) will fix the empty-body POST problem by collecting real reps/weight before submitting. This spec only fixes the skeleton-never-resolving bug.

---

## Testing

- Import a plan, complete it (or manually set status=completed in DB), navigate to `/commitments/{id}` → page loads, shows commitment name and date range, progression section shows "No logs yet" per exercise (not stuck on skeleton).
- For an active plan: navigate directly to detail URL without visiting the list first → page loads correctly.
- Run `make test` — no regressions in existing commitment tests.
- Run `cd web && npm test` — no regressions in frontend tests.
