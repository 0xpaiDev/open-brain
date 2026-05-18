# Commitment Progression Chart Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the commitment detail page so it loads correctly for all commitment statuses and shows the progression chart skeleton resolving to real content.

**Architecture:** Add a `fetchById` method to `useCommitments` that calls `GET /v1/commitments/{id}` directly, bypassing the active-only list cache. The detail page switches to this direct fetch on mount so completed/abandoned plans also load.

**Tech Stack:** Next.js 15, React 19, TypeScript, FastAPI (Python), pytest, Vitest

---

## File Map

| File | Change |
|---|---|
| `web/hooks/use-commitments.ts` | Add `fetchById(id)` method |
| `web/app/commitments/[id]/page.tsx` | Replace array-lookup useEffect with `fetchById` call |

---

### Task 1: Add `fetchById` to the hook

**Files:**
- Modify: `web/hooks/use-commitments.ts:143-165`

- [ ] **Step 1: Add the method**

In `use-commitments.ts`, add this after `getProgression`:

```typescript
const fetchById = useCallback(
  async (commitmentId: string): Promise<CommitmentResponse> => {
    return api<CommitmentResponse>("GET", `/v1/commitments/${commitmentId}`);
  },
  [],
);
```

And add `fetchById` to the return object on the last line:

```typescript
return { commitments, loading, refresh, logCount, abandonCommitment, createCommitment, logExercise, deleteExerciseLog, getProgression, importPlan, fetchById };
```

- [ ] **Step 2: Run frontend tests**

```bash
cd web && npm test -- --run 2>&1 | tail -20
```

Expected: all passing, no new failures.

- [ ] **Step 3: Commit**

```bash
git add web/hooks/use-commitments.ts
git commit -m "feat(web): add fetchById to useCommitments hook"
```

---

### Task 2: Fix the detail page commitment lookup

**Files:**
- Modify: `web/app/commitments/[id]/page.tsx:80-96`

- [ ] **Step 1: Replace the array-lookup effect**

Current code in `CommitmentDetailPage` (lines 81–96):

```typescript
const { commitments, getProgression } = useCommitments();
const [commitment, setCommitment] = useState<CommitmentResponse | null>(null);
const [progression, setProgression] = useState<ExerciseProgression[]>([]);

useEffect(() => {
  const found = commitments.find((c) => c.id === id) ?? null;
  setCommitment(found);
}, [commitments, id]);
```

Replace with:

```typescript
const { fetchById, getProgression } = useCommitments();
const [commitment, setCommitment] = useState<CommitmentResponse | null>(null);
const [progression, setProgression] = useState<ExerciseProgression[]>([]);

useEffect(() => {
  fetchById(id).then(setCommitment).catch(() => {});
}, [id, fetchById]);
```

- [ ] **Step 2: Run frontend tests**

```bash
cd web && npm test -- --run 2>&1 | tail -20
```

Expected: all passing.

- [ ] **Step 3: Verify backend is untouched**

```bash
make test 2>&1 | tail -20
```

Expected: all passing, no commitment-related failures.

- [ ] **Step 4: Commit**

```bash
git add web/app/commitments/[id]/page.tsx
git commit -m "fix(web): load commitment detail by direct fetch, not active-only list"
```
