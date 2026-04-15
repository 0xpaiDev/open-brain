# Todo Edit and Delete — Multi-Agent

You will work through this task in seven roles, sequentially. Do not skip ahead.
Review roles (5, 6, and 7) may loop back for fixes, up to 2 cycles each.
The goal: Users can edit the title and due date of any open todo and permanently delete one from both desktop (hover-reveal inline form) and mobile (tap-to-sheet + swipe-delete), without leaving the current view.

---

## Business context (read once, then put on your shelf)

Open Brain is a personal knowledge and task management system where todos are created via web dashboard, voice command, or Discord bot. Once created, todos have had no correction path — a typo in the title or a wrong due date could only be "fixed" by completing the item, which pollutes the done list with noise. This change adds inline edit and permanent delete to the web dashboard, closing the only remaining gap in the todo lifecycle and making the system usable for real daily task management.

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- The `TodoItem` model and `TodoHistory` model in `src/core/models.py` — fields, relationships, cascade behavior
- All todo API routes in `src/api/routes/todos.py` — especially whether a DELETE endpoint exists (it may not)
- `update_todo()` in `src/api/services/todo_service.py` — how history rows are written, how memory sync is triggered, what `fields_set` does
- `sync_todo_to_memory()` in `src/pipeline/todo_sync.py` — how it marks existing memory_items as superseded using `todo_id` metadata
- `TaskRow` component in `web/components/dashboard/task-list.tsx` — hover-reveal pattern for DeferPopover, touch target sizing, current state shape
- `useTodos` hook in `web/hooks/use-todos.ts` — all mutation functions: completeTodo, addTodo, deferTodo; how optimistic updates work

Also trace for each item:
- Where it is created
- Where it is mutated
- Where it is consumed
- Any related tests

Map the data flow end-to-end where applicable.

Produce a findings report with:
- Exact file paths and line numbers
- Relevant code snippets
- Data flow description
- Your honest assessment of structure and quality

Note any surprises or mismatches vs expectations — especially: does a DELETE endpoint exist? What happens to memory_items when a todo is deleted?

Stop. Do not proceed to Role 2 until the findings report is complete.

---

## ROLE 2 — SKEPTIC

Read Role 1's findings report. Your job is to break its assumptions.

Challenge specifically:
- The assumption that `PATCH /v1/todos/{todo_id}` is sufficient for edit — verify that `description` and `due_date` are both updatable fields and that `fields_set` correctly handles setting due_date to null (clearing it)
- The assumption that a new `DELETE /v1/todos/{todo_id}` endpoint can hard-delete without leaving orphaned memory_items — trace what `todo_id` FK references exist in `memory_items` / `raw_memory` and whether cascade covers them
- The assumption that the existing `Dialog` component can serve as a mobile bottom sheet — check whether it supports bottom-anchored positioning or whether a separate Drawer/Sheet component is needed
- The assumption that pointer-event swipe can be built without an external library — check if there are existing touch gesture utilities or if `touch-action: pan-y` conflicts need to be handled

Additionally challenge:
- Hidden dependencies or coupling (does `todo_sync.py` supersession query assume the todo still exists in DB?)
- Data shape assumptions (does the frontend `TodoItem` type include all editable fields?)
- Edge cases (null due_date, concurrent edits, what if swipe starts on the checkbox area?)
- Backward compatibility risks (does adding a DELETE endpoint break any existing behavior or tests?)
- Missing or weak test coverage (are there tests for `update_todo()` event_type="updated"? For the memory supersession path?)

For each challenge, label:
CONFIRMED | REVISED | UNKNOWN

For anything REVISED or UNKNOWN:
- Revisit the codebase
- Update findings with corrected understanding

Stop. Present the reconciled findings before Role 3 begins.

---

## ROLE 3 — SENIOR ARCHITECT

Read the reconciled findings. Design the implementation. Do not write code yet.

Produce a concrete implementation plan covering:

1. **DELETE /v1/todos/{todo_id} endpoint** — Hard-delete the TodoItem row (TodoHistory cascades automatically via `cascade="all, delete-orphan"`). Before deletion, mark all memory_items for this `todo_id` as `is_superseded=True` using the same supersession query in `todo_sync.py` — this mirrors the update path and leaves no orphaned embeddings. The endpoint must carry `@limiter.limit()` (project rule: every `/v1/*` route must be rate-limited). Return 204 No Content on success.

2. **`deleteTodo(id)` in `useTodos` hook** — Optimistic removal: immediately remove the item from `openTodos` state before the API call. On error, restore the item and show a toast. Reuse the `X-API-Key` header pattern from existing mutations.

3. **`editTodo(id, description, dueDate)` in `useTodos` hook** — Call `PATCH /v1/todos/{todo_id}` with `{description, due_date}`. Optimistic update: immediately replace the row in state. On error, restore and toast. Handle `due_date: null` correctly (clearing it).

4. **`TaskRow` component — unified desktop + mobile interaction** — Single DOM element with responsive CSS. Desktop: `group` class on row, buttons appear via `group-hover:flex hidden` (mirrors the existing DeferPopover reveal pattern). Mobile: swipe gesture via `onPointerDown/Move/Up`; when swipe exceeds threshold (~60px), reveal a red "Delete" button that slides in from the right. Tapping the row body (not checkbox, not any button) when NOT in swipe mode opens the edit dialog. All interactive elements use `min-h-11 min-w-11` touch targets. No duplicate DOM — same elements, responsive visibility classes.

5. **Edit dialog / inline form** — Desktop: row transforms into an inline edit form (replace description text with `<input>`, show DatePickerDialog trigger, Save/Cancel buttons). Mobile: use `Dialog` from `web/components/ui/dialog.tsx` with a CSS class anchoring it to the bottom (`fixed bottom-0 inset-x-0 rounded-t-2xl`). Both surfaces share the same form state: `editDescription` (string, min 1 char) and `editDueDate` (string | null). Save button disabled when description is empty. Cancel restores original values. Reuse the existing `DatePickerDialog` component for date selection.

6. **What stays unchanged**
   - `raw_memory` append-only semantics — delete cleans memory_items via supersession, not physical delete of RawMemory rows
   - TodoHistory cascade — no change to schema, existing history rows are deleted naturally when parent TodoItem is hard-deleted
   - `todo_sync.py` supersession query — reuse as-is; just call it before deletion
   - `AddTaskForm` and create flow — untouched
   - Complete/defer flows — untouched
   - All existing tests — must remain green

7. **Constraints & Safety**
   - Performance: supersession query touches at most a handful of rows per todo; no full-table scan concern
   - Backward compatibility: adding DELETE endpoint is additive; PATCH already exists; no schema migration needed
   - Migration plan: no schema changes required (TodoItem, TodoHistory, RawMemory, MemoryItem all unchanged)
   - Failure modes: if supersession query fails, abort the delete (don't leave zombie memory_items); wrap in single transaction
   - Rollback strategy: if frontend API call fails, restore optimistic state and show error toast

For each decision:
- Provide reasoning
- If multiple approaches exist, list them and justify the chosen one

Stop. Present the plan. Do not implement until Role 4 begins.

If recalled by Role 5 for an architectural revision:
- Read the specific concern raised
- Update only the affected sections of the plan
- Note what changed and why
- Return to Role 4 to re-implement the affected parts

---

## ROLE 4 — IMPLEMENTER

Read the architect's plan. Implement it exactly as specified.

Work in this order:
1. **Backend: `DELETE /v1/todos/{todo_id}` endpoint** — Add route to `src/api/routes/todos.py`. In the handler: load the TodoItem (404 if not found), call supersession helper from `todo_sync.py` to mark memory_items superseded, then `session.delete(todo)` + `session.commit()`. Apply `@limiter.limit()`. Return 204.
2. **Backend tests** — Add tests in the existing todo test file for: 404 on unknown id, 204 on success, verifying the item no longer appears in GET /v1/todos, verifying memory_items are superseded.
3. **Frontend hook: `deleteTodo` and `editTodo`** — Add to `web/hooks/use-todos.ts`. Follow the optimistic-update + rollback-on-error pattern of `completeTodo`.
4. **Frontend: `TaskRow` swipe and hover buttons** — Modify `TaskRow` in `web/components/dashboard/task-list.tsx`. Add pointer-event handlers for swipe. Add group-hover edit/delete icon buttons. Ensure touch targets ≥ 44px and `font-size ≥ 16px` on all inputs (use `text-base md:text-sm`).
5. **Frontend: edit form (inline + bottom sheet)** — Add inline form state to `TaskRow`. For mobile, use `Dialog` with bottom-anchored positioning. Reuse `DatePickerDialog`. Disable Save when description is empty.
6. **Frontend tests** — Add/update Vitest tests in the existing task-list test file: edit saves correctly, delete removes row, cancel restores values, save disabled on empty title.

After each step:
- Run the existing test suite
- Fix any failures before continuing

After implementation:
- Perform manual verification (if applicable)
- Validate outputs/logs for correctness
- Identify any remaining risks or edge cases

Final check:
- Re-read the business context
- Verify the implementation matches the original intent
- Especially validate: no accidental deletions — the swipe-reveal "Delete" button must require a deliberate tap to confirm; a single accidental swipe must not delete anything

Stop. Do not consider the task complete until reviewed.

If recalled by Role 5 or Role 6 for fixes:
- Read the specific issues listed
- Apply fixes to the affected code only
- Do not refactor or change unrelated code
- Summarize what changed and why
- Return to Role 5 for re-review

---

## ROLE 5 — REVIEWER

Review the implementation as if this were a production PR. Be critical and precise.

**Review cycle: 1 of 2 maximum.**

Inputs:
- Architect's plan
- Full diff of changes
- Implementer's summary

Evaluate across:

1. **Correctness**
   - Does the implementation fully satisfy the plan?
   - Any logical errors or missing cases?

2. **Scope adherence**
   - Any unnecessary changes?
   - Anything missing that was explicitly required?

3. **Code quality**
   - Readability, structure, naming
   - Consistency with existing patterns

4. **Safety**
   - Edge cases (null, async, race conditions)
   - Backward compatibility
   - Failure handling

5. **System impact**
   - Hidden coupling or side effects
   - Performance implications

6. **Tests & validation**
   - Are tests sufficient and meaningful?
   - What critical paths are untested?

7. **Skeptic's concerns (cross-reference Role 2)**
   - Review each REVISED and UNKNOWN finding from Role 2
   - Is each concern addressed in the implementation, or consciously accepted with documented rationale?
   - Flag any REVISED/UNKNOWN item that was silently ignored

8. **Plan fidelity (cross-reference Role 3)**
   - Does the implementation match the Architect's plan?
   - Were any deviations from the plan justified and documented by the Implementer?
   - Flag any undocumented deviation as a scope issue

Output:
- List of issues grouped by severity:
  - CRITICAL (must fix before merge)
  - MAJOR (should fix)
  - MINOR (nice to improve)
- Concrete suggested fixes for each CRITICAL and MAJOR issue
- For each CRITICAL, classify as: **IMPLEMENTATION** (code bug) or **ARCHITECTURAL** (design flaw)

Loop-back rules:
- **CRITICAL IMPLEMENTATION issues** → return to ROLE 4 with explicit fixes required. After fixes, return here (ROLE 5) and increment review cycle.
- **CRITICAL ARCHITECTURAL issues** → return to ROLE 3 with the specific concern. After ROLE 3 revises the plan, ROLE 4 re-implements the affected parts, then return here (ROLE 5) and increment review cycle.
- **Review cycle 2 with unresolved CRITICAL issues** → mark the task **BLOCKED**. List all unresolved issues with context. Stop — these need human decision-making.
- **No CRITICAL issues** → proceed to ROLE 6.

---

## ROLE 6 — SECURITY REVIEWER

Review the entire implementation through a security lens.

**Review cycle: 1 of 2 maximum.**

Evaluate for this task specifically:
- **Unauthorized delete** — the new `DELETE /v1/todos/{todo_id}` endpoint must enforce the same X-API-Key authentication as all other `/v1/*` routes; verify the auth dependency is applied and that there is no path to delete another user's todo (single-tenant system, but confirm)
- **Edit input injection** — `description` field user input flows through Pydantic validation (1-500 chars) and into `update_todo()` which writes it to the DB; verify no raw SQL or f-string interpolation anywhere in the update path, and that the history snapshot serialization does not expose raw user input to an LLM without delimiters
- **Swipe gesture CSRF surface** — the delete action is a frontend-initiated `DELETE` request; confirm the API key header requirement makes CSRF a non-issue for this endpoint (no cookie-based auth)

Additionally evaluate (standard checklist):
- Authentication & authorization — are new/modified routes properly protected?
- Input validation & injection — SQL, XSS, prompt injection (is user input wrapped in `<user_input>` delimiters before LLM calls?)
- Rate limiting & abuse — are new endpoints rate-limited? What's the worst-case cost exposure from LLM/API calls?
- Data at rest & in transit — secrets in logs, PII handling, HTTPS enforcement
- Dependencies — any new packages with known vulnerabilities?

Output:
- **CRITICAL** — must fix before deployment (auth bypass, injection, data exposure)
- **ADVISORY** — risks to document and accept consciously (third-party data flows, platform limitations)
- **HARDENING** — optional defense-in-depth improvements (daily caps, key rotation, audit logging)

For each CRITICAL issue, provide a concrete remediation.

Loop-back rules:
- **CRITICAL issues** → return to ROLE 4 with explicit fixes required. After fixes, return to ROLE 5 for re-review, then return here (ROLE 6) and increment review cycle.
- **Review cycle 2 with unresolved CRITICAL issues** → mark the task **BLOCKED**. List all unresolved issues with context. Stop.
- **No CRITICAL issues** → provide final security sign-off.

---

## ROLE 7 — UI/UX EXPERT

Review the entire frontend implementation for theme fit, visual polish, and production readiness. Be precise about what looks off, not just what's broken.

**Review cycle: 1 of 2 maximum.**

Evaluate for this task specifically:
- **Theme consistency** — new components must use the existing MD3 dark token set (`surface-container`, `surface-container-high`, `surface-container-highest`, `primary`, `on-primary`, `error`, `on-error`, `on-surface`, `on-surface-variant`). No hardcoded hex colors or Tailwind primitives (e.g., `red-500`) where semantic tokens exist. Check `globals.css` for the full token list.
- **Motion & transitions** — swipe reveal, inline form expand, and bottom sheet enter/exit must use `transition-*` classes consistent with existing animations (`transition-colors`, `transition-all`, `duration-150`–`duration-300`). The bottom sheet should feel like it rises from the bottom (translate-y) rather than fading in like a centered modal.
- **Hover and focus states** — edit/delete hover buttons must use `hover:bg-surface-container-high` (the same token used by DeferPopover and other row actions). All focusable elements must have a visible focus ring (`focus-visible:ring-2 focus-visible:ring-primary`).
- **Icon consistency** — edit and delete icons must use `material-symbols-outlined` (same icon font as the rest of the app). Appropriate icon names: `edit` for edit, `delete` for delete. Icon size should match existing action icons (typically `text-[18px]` or `text-[20px]`).
- **Bottom sheet polish** — handle bar indicator at top (`w-10 h-1 rounded-full bg-on-surface/20 mx-auto mb-4`), safe area bottom padding (`pb-safe` or equivalent), rounded top corners (`rounded-t-2xl`). Background must use `bg-surface-container` to contrast with the page background.
- **Swipe reveal** — delete button background must use `bg-error`, text `text-on-error`, minimum width wide enough for the label + icon (at least 80px). Partial swipe (< threshold) should spring back with a smooth transition.
- **Inline edit form** — description input must visually sit in the same horizontal position as the text it replaces (no layout shift). Save/Cancel buttons should use `Button` variants `default` (Save) and `ghost` (Cancel), consistent with other action buttons in the form row.
- **Mobile input compliance** — all `<input>` and `<textarea>` in the new UI must use `text-base md:text-sm` (font-size ≥ 16px on mobile, per project rule).

Additionally evaluate:
- Spacing and alignment — do new elements respect the existing 4px grid used throughout the dashboard?
- Empty state and edge cases — what does the inline form look like with a very long description? Does it clip, wrap, or overflow gracefully?
- Loading/disabled states — is the Save button visually disabled (not just functionally) when description is empty? Does it show a spinner during the async call?
- Accessibility — are delete/edit buttons labeled with `aria-label`? Does the bottom sheet trap focus? Does ESC close it?
- Dark-only compliance — the app is dark-mode only; no light-mode fallback is needed, but verify no `dark:` prefix is accidentally required

Output:
- **PRODUCTION BLOCKER** — visual issues that would look broken or off-brand in a real release (wrong colors, broken animations, misaligned layout)
- **POLISH** — issues that would be noticed by a careful user but aren't blocking (icon size slightly off, transition duration inconsistent)
- **MINOR** — nitpicks (aria-label wording, spacing 1px off)

For each PRODUCTION BLOCKER, provide the exact Tailwind class change or component fix needed.

Loop-back rules:
- **PRODUCTION BLOCKER issues** → return to ROLE 4 with explicit fixes required. After fixes, return to ROLE 5 for re-review, then ROLE 6, then return here (ROLE 7) and increment review cycle.
- **Review cycle 2 with unresolved PRODUCTION BLOCKER issues** → mark the task **BLOCKED**. List all unresolved issues. Stop.
- **No PRODUCTION BLOCKER issues** → provide final UI/UX sign-off.

---

## Completion

**TASK COMPLETE** when Role 5, Role 6, and Role 7 all approve with no CRITICAL / PRODUCTION BLOCKER issues.
**BLOCKED** if any reviewer's cycle cap (2) is reached with unresolved issues — stop and escalate to the user.
