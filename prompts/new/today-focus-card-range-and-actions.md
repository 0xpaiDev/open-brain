# Today Focus Card — Range Display, Single Picker, Action Consolidation — Multi-Agent

You will work through this task in sequential roles. Do not skip ahead.
Optional roles (marked "conditional") are included only when relevant — if absent, proceed to the next numbered role.
Review roles (5 and 6) may loop back for fixes, up to 2 cycles each.
The goal: the Today dashboard's focus card correctly displays date-range todos, owns the Done/Defer/Delete actions for the active todo, and the composer offers a single start-then-end date-range picker — with no "Invalid Date" reaching the UI.

---

## Business context (read once, then put on your shelf)

Open Brain is a single-user organizational memory system. The Today dashboard at `web/app/dashboard/page.tsx` is the daily driver: a "focus card" pins the user's currently-active todo, and a list view shows the rest of the open todos grouped by project. Today's UI mishandles date-range todos (renders "Invalid Date – Invalid Date"), the range picker exposes the two endpoints in a counter-intuitive end-then-start order as separate fields, and per-row Defer/Delete clutter the list while the focus card itself only offers Done + a low-value Skip. This sprint moves Done/Defer/Delete onto the focus card, removes Skip, fixes range rendering, replaces the two-field range picker with a single start→end picker, and pushes project + date badges to the right of the title on the focus card.

---

## Project context (grounding for all roles)

### Relevant conventions

1. **Mobile input font-size ≥ 16px** — every `<input>`/`<textarea>`/`<select>` must use `text-base md:text-sm`, not bare `text-sm` (Safari/Chrome auto-zoom otherwise). Base components in `web/components/ui/` already follow this; any new picker input must too.
2. **No duplicate DOM for responsive layouts** — JSDOM ignores `hidden`/`sm:hidden`, so duplicate elements break tests. Use a single DOM with `flex-wrap` + responsive utilities, not two parallel render branches for mobile/desktop.
3. **Vitest + Testing Library** for component tests (`web/__tests__/components/*.test.tsx`); existing files for the affected components are `focus-card.test.tsx`, `task-list.test.tsx`, `project-group.test.tsx`. Run `cd web && npm test`.
4. **Playwright** for E2E (`web && npx playwright test`) — only update if existing E2E flows are broken; do not add new E2E for v1.
5. **No new backend round-trips** — focus-card actions must reuse existing todo mutation endpoints (`PATCH /v1/todos/{id}`, `DELETE /v1/todos/{id}`, deferral via `PATCH` with new `due_date`).
6. **Todo edits already cost a Voyage embedding** per `PATCH` mutating description/due_date — defer = `due_date` change, so each defer costs an embedding (already true today; no new cost from this sprint).
7. **Commit format**: `feat(web): ...` / `fix(web): ...`; branch is `master`.
8. **Project field validation**: `todo_items.project` is a `String(100)` soft reference to `project_labels.name`; NULL renders as "Personal" at render time. No change to this in v1.

### Architecture snapshot

The Today UI is composed of the following components and helpers, all under `web/`:

- [web/app/dashboard/page.tsx](web/app/dashboard/page.tsx) — page shell; passes todos and mutation handlers down.
- [web/components/dashboard/focus-card.tsx](web/components/dashboard/focus-card.tsx) — current focus card. Renders title, project + date badges (currently left-aligned), a Done button, and a Skip button (`aria-label="Skip focus (no completion)"` line 89-93). Reads `todo.due_date` and `todo.start_date`. Calls `getFocusDateLabel(todo.due_date, todo.start_date)` from `task-utils.ts` to compute the date pill — this is the source of "Invalid Date – Invalid Date" rendering.
- [web/components/dashboard/task-utils.ts](web/components/dashboard/task-utils.ts) — `getFocusDateLabel(dueDate, startDate)` formats the focus date pill (this function is where "Invalid Date" is currently produced).
- [web/components/dashboard/task-row.tsx](web/components/dashboard/task-row.tsx) — inline list row. Currently embeds `DeferPopover` (lines 31-100) and a Delete button (lines 203-212); these are the per-row actions to remove.
- [web/components/dashboard/task-list.tsx](web/components/dashboard/task-list.tsx) — renders the project-grouped open-todos list; owns `focusId` localStorage state and stale-id guard (per CLAUDE.md).
- [web/components/dashboard/add-task-form.tsx](web/components/dashboard/add-task-form.tsx) — composer. Currently has a "Date range" mode (line 90) with two separate inputs and a counter-intuitive end-then-start order (the picker UX to replace).
- [web/hooks/use-todos.ts](web/hooks/use-todos.ts) — todo mutation hooks; provides existing handlers for create/update/delete/defer that the focus card must reuse.
- [web/lib/types.ts](web/lib/types.ts) — `TodoItem` includes both `due_date: string | null` and `start_date: string | null`; `TodoCreate` and `TodoUpdate` accept `start_date` as optional. The backend (`src/api/services/todo_service.py`) supports `start_date` end-to-end (lines 74, 91, 112, 141, 184–187).
- [web/components/ui/](web/components/ui/) — shadcn primitives. A `popover.tsx` and `dialog.tsx` exist; check whether `calendar.tsx` (range mode) is already present before adding a new dependency.

Key insight from exploration: `start_date` is fully wired backend-side. The "Invalid Date" rendering is therefore a **frontend formatter bug** in `task-utils.ts`/`focus-card.tsx`, not a missing data field. The Skeptic should still confirm this, but no schema or API work is required.

### Recent changes

- 2026-04-30 — Todo redesign (focus card + project groups) + UI polish sprint deployed (commits `350cb23`, `e599864`). The current focus card was added in this work; the same files (`task-row.tsx`, `focus-card.tsx`, `task-utils.ts`, `use-todos.ts`) are the deltas. **Implication: this sprint is iterating on freshly-shipped code; assume the patterns there are intentional, not legacy. Confirm before refactoring style.**
- 2026-04-30 — Migration 0015 added `todo_items.project` (soft ref to `project_labels.name`). Project field is in scope as a render concern (right-side badge), not a schema change.
- No backend changes recently in todo service or schema relevant to this sprint.

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- [web/components/dashboard/focus-card.tsx](web/components/dashboard/focus-card.tsx) — the full file. Note the current actions (Done, Skip), how it reads `todo.due_date` / `todo.start_date`, where the badges render relative to the title, and how it calls into `task-utils.ts`.
- [web/components/dashboard/task-utils.ts](web/components/dashboard/task-utils.ts) — `getFocusDateLabel`. Identify exactly *why* it returns "Invalid Date – Invalid Date" for ranged todos. Inspect any `new Date()` / `Intl.DateTimeFormat` / `toLocaleDateString` usage — is it tripping on `null`, on ISO format with timezone, or on the absence of one endpoint?
- [web/components/dashboard/task-row.tsx](web/components/dashboard/task-row.tsx) — full file. Locate `DeferPopover` (lines ~31–100) and the inline Delete button (~lines 203–212). Trace what props/handlers they consume and how they're invoked from `task-list.tsx`.
- [web/components/dashboard/add-task-form.tsx](web/components/dashboard/add-task-form.tsx) — full file. Identify the "Date range" toggle (~line 90), the two-field input rendering, and the field order. Confirm whether a single `<input type="date">` flow exists for single-date and how range mode diverges from it.
- [web/components/dashboard/task-list.tsx](web/components/dashboard/task-list.tsx) — focus on how it propagates `onDefer` / `onDelete` into `task-row.tsx` and how `focusId` is selected/persisted. Confirm whether removing inline defer/delete handlers from rows breaks any other consumer.
- [web/hooks/use-todos.ts](web/hooks/use-todos.ts) — list every mutation it exposes. Confirm there's an existing `defer`/`update` action that takes `(id, due_date)` and an existing `delete` action; the focus card will reuse these (no new endpoint).
- [web/components/ui/](web/components/ui/) — list the available primitives. Critically: is there a `calendar.tsx` (e.g. shadcn react-day-picker wrapper) already installed, or will the picker need a new dependency? Same for `tooltip.tsx` (needed for Defer/Delete help affordances).
- [web/__tests__/components/focus-card.test.tsx](web/__tests__/components/focus-card.test.tsx), `task-list.test.tsx`, `task-row.test.tsx` (if it exists) — read every test. List which tests will need to change (Skip removed, Defer/Delete moved to focus card, badge position).
- [web/lib/types.ts](web/lib/types.ts) — confirm `TodoItem.start_date` and `TodoItem.due_date` types. Confirm `TodoCreate` accepts `start_date` (it does — line 120) so the composer just needs to pass it.

Also trace for each item:
- Where it is created
- Where it is mutated
- Where it is consumed
- Any related tests

Map the data flow end-to-end where applicable: composer → `useTodos.create()` → backend → render in focus-card / task-list.

Produce a findings report with:
- Exact file paths
- Relevant code snippets (especially the broken `getFocusDateLabel` body)
- Data flow description
- Your honest assessment of structure and quality

Note any surprises or mismatches vs the Architecture snapshot above. In particular: does `start_date` actually arrive in the DOM (i.e., is it returned by the API and present on `TodoItem` instances), or is it stripped somewhere?

Stop. Do not proceed to Role 2 until the findings report is complete.

---

## ROLE 2 — SKEPTIC

Read Role 1's findings report. Your job is to break its assumptions — but only with evidence.

### Grounding rules
- Every challenge must cite specific evidence from the Explorer's findings (file path, code snippet, data shape)
- Label each challenge: **HIGH** (contradicting evidence found), **MEDIUM** (ambiguous evidence), **LOW** (speculation)
- For LOW challenges: go back to the codebase and upgrade to MEDIUM/HIGH, or drop with "Insufficient evidence, not blocking"
- Do not carry LOW challenges forward to the Architect

Challenge specifically:
- **"Invalid Date is purely a render bug"** — is `start_date` actually present in API responses and on `TodoItem` instances at render time, or is it absent/stripped, in which case the formatter is correct to bail and the real fix is upstream? Confirm by tracing one concrete ranged todo from `POST /v1/todos` → `useTodos` cache → focus-card prop. Cite the response schema + cache shape.
- **"`start_date` ≤ `due_date` is enforced"** — does any layer (composer, backend service, DB constraint) reject `start_date > due_date`? If not, the success criterion "start ≤ end at submit" requires a new client-side guard. Cite `src/api/services/todo_service.py` and the `TodoCreate` Pydantic model.
- **"No backend change is needed"** — confirm this. If the picker emits ISO datetimes vs ISO dates, does `todo_service.create_todo` accept both? Cite the type of `start_date` / `due_date` parameters and how `add-task-form.tsx` currently formats them.
- **"Removing inline Defer/Delete doesn't strand other consumers"** — is `task-row.tsx`'s `DeferPopover`/Delete used anywhere outside `task-list.tsx`? Grep for imports of `DeferPopover` from other files. If a separate flow uses it (e.g., overdue modal, focus card itself today), the removal scope changes.
- **"The composer's range mode is the only place ranges are entered"** — confirm. Is there a voice-command path or a quick-add path that also writes `start_date`? Cite the voice intent service and any other create entry points.
- **"shadcn `calendar.tsx` is available for range mode"** — verify by listing `web/components/ui/`. If not present, range mode requires installing react-day-picker or building a minimal dual-input picker; the picker scope expands.
- **"Tooltip primitive is available"** — same check for `tooltip.tsx`. The help-affordance requirement (hover on desktop, long-press on mobile) is much simpler with shadcn `Tooltip`; without it, the spec must define a fallback (info dot opening a small popover).
- **"Focus card actions reuse existing hooks"** — confirm `useTodos` exposes `defer` (or `update` accepting partial `due_date`) and `delete`. If the existing focus card today reaches into a different action surface, document the gap.

Additionally challenge:
- Hidden dependencies or coupling
- Data shape assumptions (esp. `due_date` ISO format vs date-only)
- Edge cases (todo with `start_date` set but `due_date` null; vice versa; both null; equal dates)
- Backward compatibility risks for single-date todos
- Missing or weak test coverage (focus-card defer flow, range submit guard)

For each challenge, label:
**HIGH** | **MEDIUM** | **LOW** → [upgraded/dropped]

For anything MEDIUM or HIGH:
- Revisit the codebase if needed
- Update findings with corrected understanding

Stop. Present the reconciled findings (HIGH and MEDIUM items only) before Role 3 begins.

---

## ROLE 3 — SENIOR ARCHITECT

Read the reconciled findings. Design the implementation. Do not write code yet.

Produce a concrete implementation plan covering:

1. **Range formatter (`task-utils.ts`)** — design `getFocusDateLabel(dueDate, startDate)` to handle: both null (no badge), `due_date` only (single-date label, current behavior), `start_date` only (defensive — render the start as a single-date label), both set (locale-respecting range like "Mon 5 May – Fri 9 May", short month names, year only when not current year, equal start/end collapses to single-date). Pick a formatting library: `Intl.DateTimeFormat` (zero deps) is preferred unless the codebase already uses `date-fns`. Decide whether to lowercase or capitalize weekdays. Specify exactly when each format variant fires.

2. **Range picker in the composer** — design a single picker that emits two dates in start-then-end order. Two viable approaches:
   (a) shadcn `Calendar` in `mode="range"` inside a `Popover` — preferred if both primitives already exist. One trigger button labeled by the current selection ("Pick dates"); two clicks complete the range; second click before first swaps to make `start ≤ end`.
   (b) Two adjacent `<input type="date">` fields rendered side-by-side, with `min` on the second tied to the first — fallback if shadcn calendar isn't installed.
   Pick the approach grounded in what the Explorer found in `web/components/ui/`. Specify: trigger label format, empty-state placeholder, submit guard (`start ≤ end`, both required if range mode is on), and how single-date mode toggles back (a small "Single date" link).

3. **Focus card action set + layout** — three buttons: Done (primary, e.g. existing solid style), Defer (secondary outline), Delete (secondary outline destructive). Skip is removed entirely (its handler can be deleted; do not leave a `_skip` no-op). Defer reuses `useTodos.defer` (or `update` with `due_date`); Delete reuses `useTodos.delete`. Delete requires a confirm — pick mechanism (native `confirm()` is the cheapest acceptable; shadcn `AlertDialog` is cleaner if installed). Defer presents the same date input UX as the row's previous popover (single-date input) and on submit shows a toast "Deferred to Tue 6 May" using the existing toast surface (find it in `web/components/ui/`). Layout: title left, project + date pills right, with `flex justify-between` on the header row; pills wrap onto a new line on phone-width via `flex-wrap`. No duplicate DOM (per project conventions).

4. **Inline-row simplification (`task-row.tsx`)** — remove `DeferPopover`, the Delete button, and any handlers used solely by them. Keep the body of the row (title, project pill, focus toggle, edit). Remove the now-unused `onDefer` / `onDelete` props on `task-row.tsx` and adjust the call site in `task-list.tsx`. **Do not** remove the underlying mutations from `use-todos.ts` — they're still used by the focus card. Confirm no other consumer imports `DeferPopover`.

5. **Help affordances on Defer + Delete** — wrap each focus-card secondary button in a shadcn `Tooltip` (on hover) and ensure mobile fallback (tooltip on focus + long-press, or a tiny info dot icon next to each label). Tooltip text should be one short sentence each (e.g. "Push this todo to a later day", "Permanently delete this todo"). Cite the exact `Tooltip` API used.

6. **Test plan**
   - **`task-utils.test.ts` (new or extended)**: unit tests for `getFocusDateLabel` covering: both null, due-only, start-only, both equal, valid range, range with start > end (formatter must not crash; spec the chosen behavior — recommend swapping or returning the due-only label).
   - **`focus-card.test.tsx`**: assert Done/Defer/Delete render and Skip does not; assert Defer opens a date input and on submit calls the defer handler and shows a toast; assert Delete opens a confirm and on confirm calls the delete handler; assert badges render to the right of the title (use snapshot or check DOM order).
   - **`task-row.test.tsx`** (extend or update): assert no Defer button, no Delete button rendered.
   - **`task-list.test.tsx`**: existing tests should still pass; if any test asserted inline defer/delete, update it.
   - **`add-task-form.test.tsx`** (extend or new): assert range mode shows one picker (one trigger or two adjacent inputs in start-then-end order); assert submit with `start > end` is blocked; assert single-date mode is unchanged.
   - **Invariants**: `getFocusDateLabel` never returns a string containing "Invalid"; focus-card buttons never disappear when `start_date` is set; single-date todo creation flow is byte-identical to current behavior.
   - The Implementer will write these tests FIRST, before any production code.

7. **What stays unchanged**
   - Backend: `src/api/services/todo_service.py`, `src/core/models.py`, `src/api/schemas/`, all migrations.
   - Voice command path (`/v1/voice/command`).
   - `useTodos` hook signature — only its callers change.
   - Single-date todo creation, completion, and rendering.
   - Project-group rendering, focus toggling, localStorage keys (`ob:todo:focusId`, `ob:todo:collapsedProjects`).
   - Memory sync (`sync_todo_to_memory`) — defer continues to trigger an embedding regeneration as before.

8. **Constraints & Safety**
   - **Performance**: no new round-trips; defer = one `PATCH`, delete = one `DELETE`. Tooltip primitives are render-only.
   - **Backward compatibility**: existing single-date todos must still render their single-date pill on the focus card with no visual regression.
   - **Migration plan**: none — no schema or API changes.
   - **Failure modes**: defer with invalid date → button disabled; delete confirm dismissed → no-op; toast surface absent → silent fallback (log warn, do not block the mutation).
   - **Rollback strategy**: this is a frontend-only sprint; revert the commit. No data shape changes mean rollback is safe instantly.
   - **Mobile parity**: secondary buttons stay reachable at 360px viewport — verify by running at narrow width; badges wrap rather than overlap.
   - **Accessibility**: each button has a clear `aria-label`; tooltips use `aria-describedby` (shadcn `Tooltip` does this for free); confirm dialog focus-traps.

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

## ROLE 3.5 — SENIOR UI/UX EXPERT (conditional — included because this task has UI surface)

> This role requires the UI/UX Pro Max skill installed globally at `~/.claude/skills/ui-ux-pro-max/`.

Read the Architect's plan. Before any implementation begins, generate a design system for the UI components in this task.

### Step 1 — Generate design system

```bash
python3 ~/.claude/skills/ui-ux-pro-max/scripts/search.py "productivity todo dashboard focus card range picker tooltip" --design-system -p "Open Brain"
```

### Step 2 — Evaluate and adapt

Review the generated design system against:
- The existing UI patterns in `web/components/dashboard/` (focus-card, task-row, project-group) discovered by the Explorer.
- The project's current design language: shadcn/ui primitives (`web/components/ui/`), Tailwind tokens, the type scale already established for the focus card title and badges.
- The Architect's plan constraints: title-left-badges-right layout, three-button action row, single-picker range mode.

**Consistency rule:** A new feature must look like it belongs in the existing app, not like a redesign. Specifically:

- Keep existing color tokens, typography, and spacing — focus card title style, project pill colors (from `project_labels.color`), date pill style.
- Keep the existing button hierarchy: primary (filled), secondary (outline), destructive variant for Delete.
- Keep responsive utilities and the no-duplicate-DOM rule.
- Adopt only the recommendations that fill gaps:
  - Tooltip styling and positioning if not already standardized.
  - Mobile long-press / info-dot fallback pattern.
  - Date-range picker visual treatment (selected range highlight, hover preview) if a range calendar is added.
  - Toast styling consistency for the "Deferred to …" message.

### Step 3 — Produce a design brief

Output a concise design brief for the Implementer containing:
- **Color tokens** — explicitly mapped to existing CSS variables / Tailwind classes used in the focus card today; new tokens only if a true gap exists.
- **Typography** — only if introducing new text styles (likely none).
- **Component patterns**:
  - Focus card header: `flex items-start justify-between gap-3` with title block left, badge cluster right, `flex-wrap` on the badge cluster for mobile.
  - Action row: three buttons in a single `flex gap-2 flex-wrap` row, primary first, secondary two next.
  - Range picker: trigger button styled like the existing date input affordance.
- **Interaction patterns**:
  - Tooltip on hover (desktop) + on focus (keyboard); long-press on mobile (or info dot icon).
  - Defer toast appears bottom of viewport, dismisses in 3s.
  - Delete confirm uses the project's existing dialog primitive.
  - Range calendar: hover highlights the prospective range; tapping a date before the start swaps endpoints.
- **Anti-patterns**:
  - Do not introduce a third button visual style for the new buttons.
  - Do not use a different date-pill format on the focus card vs. inline rows for single-date todos.
  - Do not stack the three action buttons vertically on mobile — keep them on one wrapping row so the visual hierarchy is preserved.
- **Pre-delivery checklist**:
  - Contrast ratio ≥ 4.5:1 on all buttons and pills (especially destructive).
  - `cursor-pointer` on every clickable.
  - Visible `:focus-visible` ring on every interactive.
  - Reduced-motion: no animation on the card-swap if `prefers-reduced-motion: reduce`.
  - Text scales to 200% without overflow at 360px viewport.

The Implementer treats this brief as a constraint alongside the Architect's plan.

Stop. Present the design brief before Role 4 begins.

---

## ROLE 4 — IMPLEMENTER

Read the architect's plan. If Role 3.5 produced a design brief, read that too — it is a binding constraint for all UI work.

Implement exactly as specified.

### Step 1 — Write tests first (mandatory)

Based on the Architect's test plan:
- Write/extend `web/__tests__/lib/task-utils.test.ts` (or wherever utils tests live) for `getFocusDateLabel`.
- Update `web/__tests__/components/focus-card.test.tsx` to assert the new action set, badge position, and tooltip presence.
- Update `web/__tests__/components/task-row.test.tsx` (create if missing) to assert Defer/Delete are gone from rows.
- Update or add `web/__tests__/components/add-task-form.test.tsx` to assert single-picker range mode and the start ≤ end submit guard.
- Follow existing project conventions: Vitest + Testing Library, `text-base md:text-sm` rule, no duplicate DOM in fixtures.
- Run `cd web && npm test`.
- Confirm tests fail for the expected reasons (formatter not yet fixed, focus card still has Skip, range picker still two fields, row still has Defer/Delete). If they fail for unexpected reasons (import errors, broken setup), STOP and reconcile.

### Step 2+ — Implement production code

Work in this order (lowest-risk first):

1. **Fix `getFocusDateLabel` in `web/components/dashboard/task-utils.ts`** — handle null/single/range/equal/inverted-range cases per the Architect's plan. Make the unit tests pass.
2. **Update `web/components/dashboard/focus-card.tsx`** — replace Skip with a Done/Defer/Delete button row; move project + date badges from left to right of the title (title-left, badges-right header layout); wrap Defer + Delete in tooltips; wire Defer to a small inline date-input flow + toast; wire Delete to a confirm flow; reuse `useTodos` mutations.
3. **Strip `DeferPopover` and the inline Delete button from `web/components/dashboard/task-row.tsx`**, remove the now-unused props, and update the `task-list.tsx` call site.
4. **Replace the two-field range picker in `web/components/dashboard/add-task-form.tsx`** with a single picker (shadcn range Calendar inside a Popover if available, else two side-by-side `<input type="date">` with `min` chained from the start). Add a submit guard rejecting `start > end`. Keep single-date mode unchanged as the default.
5. **Verify tooltip + toast primitives** are imported once at the top of the relevant files (no per-button duplicate setup).

After each step:
- Run `cd web && npm test` (vitest)
- Fix any failures before continuing
- Run `cd web && npm run lint` (or the project's lint command)

### Final verification

- Run the full test suite: `cd web && npm test`
- Verify each convention from the Project Context checklist (text-base on inputs, no duplicate DOM, mobile font-size compliance)
- Manual verification:
  - Create a single-date todo → renders correctly on focus card (no regression)
  - Create a range todo "5 May" – "9 May" → focus card pill reads "Mon 5 May – Fri 9 May" (or equivalent locale-respecting form), no "Invalid Date"
  - Try to submit a range with start > end → blocked at submit
  - On focus card: click Defer, pick a date, see toast, card moves on
  - On focus card: click Delete, confirm, card moves on
  - Inline list rows: confirm no Defer or Delete buttons present
  - Hover Defer/Delete on desktop → tooltip
  - At 360px viewport: badges + buttons wrap cleanly, all reachable, no overlap with title
- Run `npx playwright test` if any Today-page E2E exists; do not add new ones.

Final check:
- Re-read the business context
- Verify the implementation matches the original intent
- Especially validate: **zero "Invalid Date" strings rendered for any ranged todo on the focus card**, and **single-date todos behave identically to before**.

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
   - Does `getFocusDateLabel` handle every case (null, single, range, equal, inverted)?
   - Does Defer trigger a real `PATCH` and toast? Does Delete actually delete after confirm?
   - Does the range picker reject `start > end` at submit?
   - Are inline-row Defer/Delete actually gone, not just `display: none`?

2. **Scope adherence**
   - Any unnecessary changes (e.g., to project-group, calendar-strip, morning-pulse)?
   - Skip button truly removed (no dead handler left behind)?

3. **Code quality**
   - Readability, structure, naming
   - Consistency with existing patterns in the same file

4. **Safety**
   - Edge cases: ranged todo with only `start_date` set, only `due_date` set, equal dates
   - Race conditions on rapid Defer-then-Defer
   - Confirm dismissal handled

5. **System impact**
   - Hidden coupling: did `task-row.tsx` prop changes break anything?
   - Performance: no extra renders in the list view from the changes

6. **Tests & validation**
   - Are the new tests meaningful and not just snapshot churn?
   - Coverage of: invalid range submit guard, focus-card delete confirm path, formatter edge cases

7. **Skeptic's concerns (cross-reference Role 2)**
   - Each MEDIUM/HIGH item from Role 2 — addressed or consciously deferred with rationale?

8. **Plan fidelity (cross-reference Role 3)**
   - Implementation matches the plan — any undocumented deviation flagged

9. **Convention compliance (cross-reference Project Context)**
   - All inputs use `text-base md:text-sm`
   - No duplicate DOM
   - Commit message follows `feat(web):` / `fix(web):` format

10. **Design compliance (cross-reference Role 3.5)**
    - Title-left / badges-right layout matches the design brief on desktop and mobile
    - Three-button action row uses primary + secondary + destructive (no new visual styles)
    - Tooltips on Defer + Delete; mobile fallback present
    - Range calendar / inputs visually consistent with existing date affordances
    - Pre-delivery checklist items satisfied (contrast, cursor, focus-visible, reduced-motion, 200% zoom)

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
- **Delete from focus card** — confirm step is enforced client-side AND that the `DELETE /v1/todos/{id}` endpoint is still rate-limited and auth-gated (it should be, no change there). Verify the confirm UI cannot be bypassed by keyboard-Enter without selection.
- **Date-range submit guard is client-side only** — if the backend doesn't enforce `start_date ≤ due_date` and a malicious client sent `start > due`, would anything corrupt? Check `src/api/services/todo_service.py`. If unenforced, advise an ADVISORY (not CRITICAL) since this is a single-user app with API key auth.
- **Tooltip / toast text** — confirm no user-supplied `description` is interpolated unescaped into a tooltip via `dangerouslySetInnerHTML`. React string-children escape by default; flag any deviation.

Additionally evaluate (standard checklist):
- Authentication & authorization — all calls go through the existing `useTodos` hook which already includes the API key header; no new endpoints added.
- Input validation & injection — todo `description` already passes through the existing prompt-injection-defense path on memory-sync.
- Rate limiting & abuse — no new endpoints; existing `/v1/todos/*` rate limits cover defer/delete.
- Data at rest & in transit — no new fields; `start_date` already covered.
- Dependencies — if the implementer adds `react-day-picker` or any new package, confirm it's a maintained release with no known CVEs.

Output:
- **CRITICAL** — must fix before deployment (auth bypass, injection, data exposure)
- **ADVISORY** — risks to document and accept consciously (e.g., client-only range guard)
- **HARDENING** — optional defense-in-depth (e.g., backend `start_date <= due_date` validator)

For each CRITICAL issue, provide a concrete remediation.

Loop-back rules:
- **CRITICAL issues** → return to ROLE 4 with explicit fixes required. After fixes, return to ROLE 5 for re-review, then return here (ROLE 6) and increment review cycle.
- **Review cycle 2 with unresolved CRITICAL issues** → mark the task **BLOCKED**. List all unresolved issues with context. Stop.
- **No CRITICAL issues** → provide final security sign-off.

---

## Completion

**TASK COMPLETE** when Role 5 and Role 6 both approve with no CRITICAL issues.
**BLOCKED** if any reviewer's cycle cap (2) is reached with unresolved CRITICAL issues — stop and escalate to the user.
