# Todo Feature Update Plan

## Context
Six improvements to the dashboard todo feature. Covers mobile UX, a closure bug, default behaviors, labels, and a filter redesign. The goal is to make the todo system usable at scale (100+ tasks over a year).

**Schema change required:** Issue 4 adds a `label` column to `todo_items` and a new `todo_labels` table. Alembic migration needed.

---

## Issue 1: Mobile — Date Picker Access
**Problem:** Date inputs use `hidden md:block` — invisible on mobile.

**Fix:** Add a calendar icon button (visible only on mobile via `md:hidden`) that opens a `Dialog` with date inputs + range toggle. Reuse Dialog pattern from `DeferPopover`.

**File:** [task-list.tsx:284-327](web/components/dashboard/task-list.tsx#L284-L327)

### Tests — Issue 1
**File:** `web/__tests__/components/task-list.test.tsx`

| Test | Type | Description |
|------|------|-------------|
| mobile date button opens dialog | green | Click calendar icon → Dialog with date input visible |
| mobile date dialog passes date to addTodo | green | Fill date in dialog → submit → `mockAddTodo` called with date |
| mobile date dialog supports range mode | green | Toggle range in dialog → both start_date and due_date inputs visible |
| mobile date dialog closes on submit | green | Submit → dialog no longer in DOM |
| mobile date dialog closes on cancel | green | Click cancel → dialog dismissed, no addTodo call |

---

## Issue 2: Default Due Date = Today
**Problem:** No date selected → `due_date` is null. User wants today as default.

**Fix:** Initialize `dueDate` state in `AddTaskForm` with `new Date().toISOString().split("T")[0]`. Reset to today (not empty) after successful submission.

**File:** [task-list.tsx:232](web/components/dashboard/task-list.tsx#L232)

### Tests — Issue 2
**File:** `web/__tests__/components/task-list.test.tsx`

| Test | Type | Description |
|------|------|-------------|
| date input pre-filled with today | green | Render → date input value matches today's YYYY-MM-DD |
| submit without changing date sends today | green | Type task + submit → `mockAddTodo` called with today's date string |
| user can clear date to submit without due_date | corner | Clear date input → submit → `mockAddTodo` called with `undefined` |
| date resets to today after submission | green | Submit → date input value is today again (not empty) |

---

## Issue 3: Undo Task Complete (Stale Closure Bug)
**Root cause:** `completeTodo` captures `undoComplete` from the current render. After optimistic update, the toast holds the OLD `undoComplete` which can't find the task in the pre-update `doneTodos`. `doneTodos.find()` returns `undefined` → silent no-op.

**Fix:** Inline the undo logic inside `completeTodo`, capturing the `todo` object directly instead of looking it up from state:

```typescript
const completeTodo = useCallback(async (id: string) => {
  const todo = openTodos.find((t) => t.id === id);
  if (!todo) return;
  // ... optimistic update ...
  try {
    await api("PATCH", `/v1/todos/${id}`, { status: "done" });
    toast("Task completed", {
      action: {
        label: "Undo",
        onClick: () => {
          setDoneTodos((prev) => prev.filter((t) => t.id !== id));
          setOpenTodos((prev) => sortOpenTodos([...prev, { ...todo, status: "open" }]));
          api("PATCH", `/v1/todos/${id}`, { status: "open" }).catch(() => {
            setOpenTodos((prev) => prev.filter((t) => t.id !== id));
            setDoneTodos((prev) => [{ ...todo, status: "done" }, ...prev]);
            toast.error("Failed to undo");
          });
        },
      },
      duration: 5000,
    });
  } catch { /* rollback */ }
}, [openTodos]);
```

Remove the separate `undoComplete` callback — no longer needed.

**File:** [use-todos.ts:88-130](web/hooks/use-todos.ts#L88-L130)

### Tests — Issue 3
**File:** `web/__tests__/hooks/use-todos.test.ts`

| Test | Type | Description |
|------|------|-------------|
| undo via toast restores task to open list | **red→green** | Complete task → extract undo callback from toast mock → call it → task back in openTodos. **This test fails on current code** (stale closure) and passes after fix. |
| undo via toast sends PATCH {status: "open"} | green | Complete → undo → verify fetch called with PATCH /v1/todos/{id} + status: "open" |
| undo API failure rolls back (task stays done) | corner | Complete → undo → PATCH fails → task remains in doneTodos, error toast shown |
| complete non-existent todo is no-op | corner | Call completeTodo("bogus-id") → no state change, no API call |
| rapid complete→undo→complete doesn't corrupt | corner | Complete → undo → complete again → openTodos/doneTodos are consistent |

---

## Issue 4: Labels (User-Created, Single Per Task)

### Backend — Schema Change
**New table `todo_labels`:**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| name | String(50) | unique, not null |
| color | String(7) | hex color, default `#6750A4` (primary) |
| created_at | DateTime | server_default=now() |

**Add to `todo_items`:**
| Column | Type | Notes |
|--------|------|-------|
| label | String(50) | nullable, no FK (soft reference by name) |

Soft reference (no FK) so deleting a label doesn't cascade-break tasks — orphaned labels on tasks just show as plain text.

**Files:**
- [models.py:366-395](src/core/models.py#L366-L395) — add `label` field to `TodoItem`, add `TodoLabel` model
- `alembic/versions/` — new migration for `todo_labels` table + `label` column on `todo_items`

### Backend — API
**New endpoints:**
- `GET /v1/todo-labels` — list all labels
- `POST /v1/todo-labels` — create label `{ name, color? }`
- `DELETE /v1/todo-labels/{name}` — delete label (does NOT touch tasks)

**Modify existing:**
- `TodoCreate` / `TodoUpdate` — add optional `label: str | None` field
- `TodoResponse` — add `label` field
- `GET /v1/todos` — add `label` query param filter

**Files:**
- [todos.py](src/api/routes/todos.py) — update Pydantic models + list endpoint filter
- New file: `src/api/routes/todo_labels.py` — label CRUD
- [todo_service.py](src/api/services/todo_service.py) — pass `label` through create/update

### Frontend — Labels
- Add `label` to `TodoItem` type in [types.ts](web/lib/types.ts)
- New hook `use-todo-labels.ts` — CRUD for labels, cache label list
- `AddTaskForm`: add label selector (dropdown with color dots + "New label..." option)
- `TaskRow`: show label as a small colored chip next to the due badge
- Label management: small popover/dialog accessible from a settings icon in the task list header

### Tests — Issue 4

#### Backend (pytest) — `tests/test_todo_labels.py` (new file)

| Test | Type | Description |
|------|------|-------------|
| POST /v1/todo-labels creates label | green | `{name: "Work", color: "#FF0000"}` → 201, response has name+color |
| POST /v1/todo-labels defaults color | green | `{name: "Personal"}` → 201, color is default `#6750A4` |
| POST /v1/todo-labels duplicate name → 409 | red | Create "Work" twice → second returns 409 Conflict |
| POST /v1/todo-labels empty name → 422 | red | `{name: ""}` → 422 |
| POST /v1/todo-labels name too long → 422 | red | 51 chars → 422 |
| POST /v1/todo-labels invalid color → 422 | red | `{color: "red"}` → 422 (not hex format) |
| GET /v1/todo-labels lists all | green | Create 3 → GET → 3 labels returned |
| GET /v1/todo-labels empty state | green | No labels → returns `[]` |
| DELETE /v1/todo-labels/{name} removes label | green | Create + delete → GET returns empty |
| DELETE /v1/todo-labels/nonexistent → 404 | red | Delete unknown name → 404 |
| All label endpoints require auth | red | No X-API-Key → 401 |

#### Backend (pytest) — additions to `tests/test_todos.py`

| Test | Type | Description |
|------|------|-------------|
| POST /v1/todos with label | green | `{description: "x", label: "Work"}` → 201, response.label == "Work" |
| POST /v1/todos without label → null | green | Default → label is null |
| PATCH /v1/todos with label | green | Update label → response reflects change |
| PATCH /v1/todos label → null clears it | corner | Set label to null → cleared |
| GET /v1/todos?label=Work filters | green | 2 Work + 1 Personal → ?label=Work returns 2 |
| GET /v1/todos?label=nonexistent → empty | corner | Returns total=0, empty list |
| Label appears in history snapshots | green | Change label → old_value/new_value contain label field |
| Label name too long in create → 422 | red | 51 chars → 422 |

#### Vitest — `web/__tests__/hooks/use-todo-labels.test.ts` (new file)

| Test | Type | Description |
|------|------|-------------|
| fetches labels on mount | green | Mock GET → labels populated |
| createLabel adds to list optimistically | green | Call createLabel → label in list before API resolves |
| createLabel API error rolls back | corner | API 409 → label removed from list, error toast |
| deleteLabel removes from list | green | Delete → label gone |
| deleteLabel API error rolls back | corner | API 500 → label restored |

#### Vitest — additions to `web/__tests__/components/task-list.test.tsx`

| Test | Type | Description |
|------|------|-------------|
| label chip renders on task with label | green | Todo with label="Work" → colored chip visible |
| no label chip on task without label | green | Todo with label=null → no chip |
| label selector in AddTaskForm | green | Form has label dropdown with available labels |
| selecting label passes it to addTodo | green | Select "Work" + submit → `mockAddTodo` called with label="Work" |

---

## Issue 5: Add Task Form Layout Cleanup
**Problem:** `flex-wrap` row makes elements float awkwardly at tablet widths.

**Fix:** Two-row layout:
```
Row 1: [Task input .................................]
Row 2: [Priority ▾] [Label ▾] [📅 Today] [+ Add]
```
- Row 1: full-width text input
- Row 2: controls clustered in a `flex items-center gap-2` row
- Date button shows readable text ("Today", "Apr 5") instead of raw input
- On mobile: date opens via dialog (Issue 1)

**File:** [task-list.tsx:260-339](web/components/dashboard/task-list.tsx#L260-L339)

### Tests — Issue 5
**File:** `web/__tests__/components/task-list.test.tsx`

| Test | Type | Description |
|------|------|-------------|
| form renders two rows | green | Input on first row, controls on second |
| date button shows "Today" by default | green | Default date = today → button text "Today" |
| date button shows formatted date | green | Set to Apr 10 → button shows "Apr 10" |
| priority, label, date, add in correct order | green | Controls appear left-to-right in second row |

---

## Issue 6: Filter Redesign

### Tab structure: Today | This Week | All
Replace current two tabs with three. Add `filterThisWeekTodos()` in [use-todos.ts](web/hooks/use-todos.ts).

### Search + Label Filter Chips
Above tab content:
```
[🔍 Search tasks...          ] [Personal ×] [Work ×] [clear]
```
Client-side text search on `description` + label chip toggles.

### Completed Tasks — Grouped by Time Period
Replace flat collapsible with grouped cascades:
```
▸ This Week (3)
▸ Last Week (5)
▸ March 2026 (12)
```
New utility `groupDoneTodos()` in [use-todos.ts](web/hooks/use-todos.ts).

### Files:
- [use-todos.ts](web/hooks/use-todos.ts) — `filterThisWeekTodos()`, search/label filter, `groupDoneTodos()`
- [task-list.tsx](web/components/dashboard/task-list.tsx) — filter bar, 3 tabs, grouped done section

### Tests — Issue 6

#### Vitest — `web/__tests__/hooks/use-todos.test.ts`

| Test | Type | Description |
|------|------|-------------|
| filterThisWeekTodos includes tasks due Mon-Sun | green | Tasks on Mon, Wed, Sun of current week → all included |
| filterThisWeekTodos excludes last week | red | Task from last Friday → excluded |
| filterThisWeekTodos excludes next week | red | Task for next Monday → excluded |
| filterThisWeekTodos includes overdue within week | corner | Overdue task from this Monday → included |
| filterThisWeekTodos handles week boundary (Sun→Mon) | corner | Task on Sunday end of week → included; Monday next week → excluded |
| groupDoneTodos groups "This Week" correctly | green | Done tasks from this week → grouped under "This Week" |
| groupDoneTodos groups "Last Week" correctly | green | Done tasks from last week → own group |
| groupDoneTodos groups older by month/year | green | Done task from Feb 2026 → "February 2026" group |
| groupDoneTodos returns empty groups for empty input | corner | `[]` → `[]` groups |
| groupDoneTodos sorted newest group first | green | Groups ordered: This Week, Last Week, March, Feb... |
| groupDoneTodos handles tasks with only updated_at | corner | No explicit completion date → uses updated_at for grouping |

#### Vitest — `web/__tests__/components/task-list.test.tsx`

| Test | Type | Description |
|------|------|-------------|
| renders 3 tabs: Today, This Week, All | green | Tab list has 3 tabs with correct labels |
| This Week tab shows this-week tasks | green | Click "This Week" → panel shows tasks due this week |
| This Week tab badge count correct | green | Badge reflects filtered count |
| search input filters tasks by description | green | Type "buy" → only matching tasks shown |
| search is case-insensitive | corner | Type "BUY" → matches "buy groceries" |
| search with no matches shows empty state | corner | Type "zzz" → empty message |
| label filter chips render for active labels | green | Tasks with "Work" and "Personal" labels → two chips |
| clicking label chip toggles filter | green | Click "Work" → only Work tasks shown; click again → unfiltered |
| combined search + label filter | corner | Search "buy" + label "Personal" → intersection only |
| clear button resets all filters | green | Apply search + label → click clear → all tasks shown |
| done tasks grouped by time period | green | Done tasks from various dates → grouped collapsibles |
| done group "This Week" contains recent completions | green | Task completed today → under "This Week" |
| done group shows count in header | green | "March 2026 (12)" format |
| empty done list shows no groups | corner | No done tasks → no collapsible section |

#### E2E — `web/e2e/todos.spec.ts` (additions)

| Test | Type | Description |
|------|------|-------------|
| add task → default date is today | green | Add task without touching date → task has "Today" badge |
| complete task → undo via toast → task restored | **red→green** | Complete → click toast Undo → task back in open list |
| search filters task list | green | Type in search → list updates |
| This Week tab shows correct tasks | green | Navigate to This Week tab → correct tasks visible |

---

## Implementation Order
1. **Bug fix first:** Issue 3 (undo closure bug) — write red test first, then fix
2. **Quick wins:** Issue 2 (default date) + Issue 1 (mobile date)
3. **Backend for labels:** Issue 4 backend (migration, model, API + all pytest)
4. **Form redesign:** Issue 5 (form layout) + Issue 4 frontend (label selector)
5. **Filter system:** Issue 6 (tabs, search, label chips, done grouping)
6. **E2E tests:** After all features land

---

## Test Summary
| Area | New Tests | File |
|------|-----------|------|
| Backend labels CRUD | 11 | `tests/test_todo_labels.py` (new) |
| Backend todos + label | 8 | `tests/test_todos.py` |
| Hook: undo fix | 5 | `web/__tests__/hooks/use-todos.test.ts` |
| Hook: labels | 5 | `web/__tests__/hooks/use-todo-labels.test.ts` (new) |
| Hook: filters | 11 | `web/__tests__/hooks/use-todos.test.ts` |
| Component: all issues | ~18 | `web/__tests__/components/task-list.test.tsx` |
| E2E: key flows | 4 | `web/e2e/todos.spec.ts` |
| **Total** | **~62** | |

## Verification
- `make test` — all backend tests pass (existing + 19 new)
- `cd web && npm test` — all Vitest pass (existing + ~39 new)
- `cd web && npx playwright test` — E2E pass (existing + 4 new)
- Manual: mobile viewport 375px, tablet 768px, desktop 1280px
