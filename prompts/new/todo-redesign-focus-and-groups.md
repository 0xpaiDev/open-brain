# Todo Tab Redesign — Focus Card + Project Groups (Multi-Agent)

> **Complexity verdict: HEAVY.** 6+ implementation steps spanning backend (model + migration + 3 routes + 1 new endpoint + sync pipeline), frontend (redesign of a 2,200-line component, new sub-components, settings rename UI, hooks/types), and tests on both sides. Schema change (new `todo_items.project` column) and a brand-new `PATCH /v1/project-labels/{name}` endpoint with cascade across two tables. Recommend executing in a fresh session to preserve context budget — this prompt is saved as the plan and should be re-loaded as the entry point of that session.
>
> **Final destination once plan mode exits:** `prompts/todo-redesign-focus-and-groups.md` (matches the project's existing `prompts/<slug>.md` convention). Copy on approval.

---

You will work through this task in sequential roles. Do not skip ahead.
Optional roles (marked "conditional") are included only when relevant — if absent, proceed to the next numbered role.
Review roles (5 and 6) may loop back for fixes, up to 2 cycles each.

The goal: opening the Todo tab on any device shows an empty-by-default Focus Card at the top and collapsible per-project groups below, every todo carries an optional `project` field (rendered under "Personal" when null), and renaming/deleting a project in Settings flows through to both memory and todo surfaces without orphaning data.

---

## Business context (read once, then put on your shelf)

Open Brain is Shu's single-user productivity backbone — a FastAPI + Next.js dashboard backed by Supabase, where todos and memories share infrastructure (project labels, ingestion pipeline, embeddings). Mobile is the primary capture surface (iOS Shortcuts → voice → API). The current todo list is a flat 2,200-line `task-list.tsx` with cramped mobile rows and no sense of priority — every open task lives in one anonymous bucket. This redesign introduces a single user-chosen Focus Card on top, project-scoped collapsible groups below, and (newly) a `project` field on todos that reuses the existing `project_labels` table already used by memories. After this ships, memories and todos will share one source of truth for "what life area is this about?" — Settings becomes the single place to manage that taxonomy.

---

## Project context (grounding for all roles)

### Relevant conventions (from CLAUDE.md, filtered to this task)

1. **Mobile input font-size ≥ 16px** — every `<input>`, `<textarea>`, `<select>` must use `text-base md:text-sm` (not bare `text-sm`) to avoid Safari/Chrome auto-zoom on focus. Base components (`input.tsx`, `textarea.tsx`, `select.tsx`) already follow this. **Project picker must comply.**
2. **No duplicate DOM for responsive layouts** — JSDOM ignores CSS `hidden`/`sm:hidden`, breaking tests. Use single DOM + `flex-wrap` + responsive classes. **Focus Card and group rows must be one DOM tree.**
3. **Tests run on SQLite, prod on PostgreSQL** — all ORM types need `.with_variant()` for cross-DB compat. New `todo_items.project` column is plain `String(100)`, no variant needed, but the migration must be reversible.
4. **`session.commit()` is required** — `flush()` alone does not persist; `AsyncSession` close = implicit rollback.
5. **`session.refresh(obj)` after commit** if the response uses `server_default`/`onupdate` columns.
6. **UUID columns + raw SQL on SQLite** — SQLite stores UUIDs as 32-char hex, no dashes. Use SQLAlchemy Core (`sa_update`) not `text()` if a backfill needs raw SQL.
7. **Alembic, not `create_all()`** for any column add.
8. **Every `/v1/*` route needs `@limiter.limit()`** — including the new `PATCH /v1/project-labels/{name}` rename endpoint.
9. **RLS enabled on all tables** — `todo_items` already has RLS (migration 0009), no new ALTER needed for a column add. Confirm.
10. **memory_type uses underscores** — n/a here, but applies if syncing extends to memory items.
11. **Todo edits cost a Voyage embedding each** — every `PATCH /v1/todos/{id}` that mutates `description`/`due_date` triggers `sync_todo_to_memory()`. **Adding `project` to the sync content string will turn project edits into embedding edits too — Architect must decide whether project is part of the embedded content or sidecar metadata only.**
12. **Todo hard-delete supersedes memory, doesn't re-embed** — reuse `supersede_memory_for_todo()` for delete; don't call `sync_todo_to_memory()` on delete paths.
13. **Bulk todo ops loop `update_todo()`** — not relevant for v1 of this redesign (no bulk move-to-project).
14. **Commit format: `type(scope): description`** — likely `feat(todos): focus card + project groups`.
15. **Voice command routing is deterministic, not LLM** — voice path stays unchanged; created todos default to `project=NULL` and render as "Personal".

### Architecture snapshot

**Backend (Python 3.12 / FastAPI / async SQLAlchemy / Supabase):**
- `todo_items` (`src/core/models.py:393-429`) — columns: `id` UUID PK, `description`, `priority`, `status`, `due_date`, `start_date`, `label` String(50) (existing soft-ref to `todo_labels.name`), `learning_item_id`, `discord_message_id`, `discord_channel_id`, timestamps. **No `project` column today.**
- `todo_history` — append-only state log; `event_type` auto-determined by `update_todo()`.
- `project_labels` (`src/core/models.py:382-391`) — `id` UUID, `name` String(100) UNIQUE, `color` String(7), `created_at`. Created in migration `0008_add_project_labels.py`.
- `memory_items.project` (`src/core/models.py:155`) — `String(100)`, indexed, nullable, soft reference (no FK to `project_labels`).
- Routes:
  - `src/api/routes/todos.py` — POST/GET/PATCH/DELETE `/v1/todos`, `GET /v1/todos/overdue-undeferred`, `POST /v1/todos/defer-all`. Pydantic `TodoCreate`/`TodoUpdate`/`TodoResponse` defined inline at lines 36–127.
  - `src/api/routes/project_labels.py` — POST/GET/DELETE `/v1/project-labels`. **No PATCH (rename) endpoint exists today.** DELETE does not cascade to `memory_items.project` — soft refs are left dangling.
  - `src/api/services/todo_service.py` — `create_todo()`, `update_todo()`. Both call `_try_sync()` to embed via `todo_sync.py`.
  - `src/api/services/voice_intent.py` + `src/api/routes/voice.py` — voice path; classifier extracts `description` + `due_date` only, never `project`.
- Pipeline:
  - `src/pipeline/todo_sync.py::sync_todo_to_memory()` — formats content from `description, priority, status, due_date, label`, generates Voyage embedding (1024-d), supersedes prior memory_items for that todo_id, creates new RawMemory + MemoryItem. **Currently does NOT set `MemoryItem.project`.**
- Migrations: numeric-prefixed under `alembic/versions/`. Latest at head is `0014` (per PROGRESS.md). Next is `0015`.

**Frontend (Next.js / React / Tailwind / shadcn/ui / Material Design 3 dark theme):**
- `web/components/dashboard/task-list.tsx` (~2,200 lines) — owns the entire todo surface: tabs (Today/This Week/All), `TaskRow`, `DoneTaskRow`, defer dialog, edit sheet, and inline `AddTaskForm` (lines 717–845). Will need decomposition.
- `web/hooks/use-todos.ts` — `openTodos`, `doneTodos`, actions: `addTodo`, `completeTodo`, `deferTodo`, `deferAll`, `editTodo`, `deleteTodo`. Filter helpers `filterTodayTodos` (line 86) and `filterThisWeekTodos` (line 35) — local-time semantics (Europe/Vilnius).
- `web/lib/types.ts:44` — `TodoItem`: `{id, description, priority, status, due_date, start_date, label, learning_item_id, ...}`. **No `project` field today.**
- `web/components/memory/smart-composer.tsx:157-169` — has a project picker for memory creation via `useProjectLabels()` (the precedent to copy).
- `web/hooks/use-project-labels.ts` — `useProjectLabels()` → `{labels, createLabel, deleteLabel}`. **No `renameLabel` today.**
- `web/app/settings/page.tsx:396` — Projects management section: list with color swatch + name + delete-on-hover, color input + name input + "Add Project" button. **No rename UI today.**
- Theme: Material Design 3 dark in `web/app/globals.css` — primary `#adc6ff`, surface `#131313`, surface-container `#201f1f`, on-surface `#e5e2e1`. Fonts: Space Grotesk (headline) / Inter (body). Streak accents: `#4ade80` (hit), `#f87171` (miss). **The prototype HTML uses a different palette (`#1c1c1e` / salmon `#e07060` / indigo `#7b8fc7` / Helvetica) — user instruction is explicit: keep the existing MD3 theme, translate only the LAYOUT/STRUCTURE from the prototype.**
- Tests: Vitest + React Testing Library + jsdom (`web/__tests__/setup.ts`). `vi.stubGlobal('fetch')` for HTTP, `vi.mock('sonner')` for toasts, `makeTodo()` factory pattern in `__tests__/hooks/use-todos.test.ts`.

### Recent changes (PROGRESS.md, last 14 days)

- **2026-04-25 — Bulk todo defer (`POST /v1/todos/defer-all`)** shipped. Sets the convention for batched todo mutations. Not directly affected, but the route file and service patterns are warm.
- **2026-04-25 — Signal-driven Morning Pulse Phase 1.** Touches `src/jobs/pulse.py`; not in this task's scope.
- **2026-04-15 — Learning Library V1.** Added `todo_items.learning_item_id` (migration 0013). Cron-generated learning todos must continue working: they have no project today and should render under "Personal" via the NULL fallback (or be left as a follow-up if Architect decides "Learning" is a seeded project).
- Migrations are at head `0014`. The new migration in this task will be `0015_add_project_to_todos.py`.

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover and verify against the snapshot above. Flag every divergence.

Find and read:

- **`src/core/models.py`** — confirm `TodoItem` has no `project` column; capture current column ordering and any existing `Index` definitions on `todo_items` (you'll need to know this when adding the new column + index).
- **`src/api/routes/todos.py`** — full file. Capture exact Pydantic shapes for `TodoCreate`, `TodoUpdate`, `TodoResponse`, all rate-limit decorators, and the response builder logic so you know where `project` plumbs through on each route.
- **`src/api/services/todo_service.py`** — `create_todo()` and `update_todo()` signatures; how `fields_set` distinguishes "not provided" from "explicit null"; how `_try_sync()` is invoked.
- **`src/pipeline/todo_sync.py`** — content-string formatting and the MemoryItem creation block. Decide whether `project` belongs in the embedded content (changes embedding cost dynamics) or as a sidecar `MemoryItem.project` field (cheap, no re-embed needed when only project changes).
- **`src/api/routes/project_labels.py`** — full file. Confirm no PATCH/PUT endpoint exists. Capture the rate-limit decorator, the validation pattern for `name`/`color`, and how DELETE currently behaves (does it 404 on dangling refs? does it touch `memory_items` at all?).
- **`alembic/versions/0008_add_project_labels.py`** and **`0013_add_learning_item_id.py`** — pattern reference for the new migration `0015_add_project_to_todos.py`.
- **`web/components/dashboard/task-list.tsx`** — full file. Identify decomposition boundaries: where the current Today/This Week/All filter is applied, how `AddTaskForm` is mounted, where `TaskRow` is keyed.
- **`web/hooks/use-todos.ts`** — full file. Capture sort logic (`sortOpenTodos`), optimistic insert behavior, and how `addTodo` shapes the POST body (so the new `project` field plumbs through).
- **`web/components/memory/smart-composer.tsx`** lines 89–169 — the existing project picker is the template for the new todo picker. Same shadcn `Select`? Same colour swatches?
- **`web/app/settings/page.tsx`** lines 23–26 (preset colours) and 396+ (Projects section) — confirm there is no rename affordance today and capture the exact list-row layout for symmetry when adding rename.
- **`web/hooks/use-project-labels.ts`** — confirm the hook surface and how it caches the list (so the new rename action invalidates correctly).
- **`web/__tests__/hooks/use-todos.test.ts`** and **`web/__tests__/components/task-list.test.ts`** — fixture patterns, mock-fetch idioms, `makeTodo()` factory shape.

Trace each item:
- Where it is created
- Where it is mutated
- Where it is consumed
- Any related tests

Map the data flow end-to-end: Settings rename → backend cascade → todo grouping refresh, AND todo create with project → DB row → todo_sync.py → memory_item.project.

Produce a findings report with:
- Exact file paths and line numbers
- Relevant code snippets (no more than 6 lines each)
- Data flow description
- Honest assessment of structural/quality concerns
- Surprises or mismatches vs the Architecture snapshot above (especially around the existing `TodoLabel` vs `ProjectLabel` parallelism)

Stop. Do not proceed to Role 2 until the findings report is complete.

---

## ROLE 2 — SKEPTIC

Read Role 1's findings. Your job is to break its assumptions — but only with evidence.

### Grounding rules
- Every challenge must cite specific evidence from the Explorer's findings (file path, code snippet, data shape).
- Label each challenge: **HIGH** (contradicting evidence found), **MEDIUM** (ambiguous evidence), **LOW** (speculation).
- For LOW challenges: go back to the codebase and upgrade to MEDIUM/HIGH, or drop with "Insufficient evidence, not blocking."
- Do not carry LOW challenges forward to the Architect.

### Pre-loaded challenges (already grounded — verify and expand)

1. **No rename endpoint exists today** — Success criterion #5 requires "renaming a project in Settings updates both memory and todo group headers without a manual refresh," but `src/api/routes/project_labels.py` exposes only POST/GET/DELETE. **HIGH** — adding `PATCH /v1/project-labels/{name}` is in-scope, not a wishlist.

2. **`memory_items.project` is a soft string reference, no FK** — `src/core/models.py:155` — meaning `project_labels.name` is the only enforcement of uniqueness; there is no DB-level cascade. Any rename or delete must update referencing rows in app code (within a transaction). The same will be true for `todo_items.project`. **HIGH**.

3. **`DELETE /v1/project-labels/{name}` leaves memory_items dangling today** — confirmed by Explorer notes. The new requirement says "deleting a project never orphans a todo: affected todos surface under Personal immediately." Two options: (a) backend cascades on delete by NULL-ing `memory_items.project` and `todo_items.project`, or (b) frontend renders any unknown/null project as "Personal". The spec sentence "fall back to Personal" reads as render-time fallback, but doing both is safer for memory consistency. **HIGH** — Architect must pick.

4. **Theme conflict** — prototype README in `docs/ToDo-redisign/README.md` lists tokens (`#1c1c1e`, salmon `#e07060`, indigo `#7b8fc7`, Helvetica) that contradict the in-app MD3 dark palette (`#131313`, primary blue `#adc6ff`, Space Grotesk/Inter). User instruction is explicit: "Don't change the current theme. Keep existing theme across all the app and future changes." **HIGH** — translate only the layout/structure (focus card geometry, group header arrangement, indent, mini progress bar widths), keep all colour/typography tokens from `globals.css`. Project colour swatches come from `project_labels.color` already.

5. **Tab filtering uses local-time semantics** — `filterTodayTodos` (use-todos.ts:86) is local-time Europe/Vilnius. Grouping must be applied AFTER tab filtering, otherwise group counts will mismatch the count chip in the tab header. **HIGH** — this also means `defer-all`'s server-side rejection of `scope="today"` (per CLAUDE.md) is the correct precedent.

6. **`sync_todo_to_memory()` doesn't carry project today** — `src/pipeline/todo_sync.py`. If we want memory and todo views to be project-consistent (a stated success criterion), the sync must propagate `todo.project` → `memory_item.project`. But the embedded content string is also where project text could live, which would re-trigger embeddings on every project change. **HIGH** — recommend setting `MemoryItem.project` (sidecar column) and NOT including project in the embedded content string, so project edits don't burn Voyage tokens.

7. **`learning_item_id` todos have no project** — Learning cron creates todos with `project=NULL` (since the column is new). That's consistent with the Personal-fallback rule. But if Architect decides a "Learning" project should be auto-seeded, the cron would need updating too. **MEDIUM** — recommend keeping learning todos under Personal-fallback for v1 to avoid widening scope.

8. **Voice path doesn't extract project** — `src/api/services/voice_intent.py` confirmed by Explorer. Spec says "Voice / Discord / iOS shortcut changes — voice keeps creating todos under the default project." Default = NULL = Personal at render time. No backend change needed. **HIGH** — but Architect should explicitly call this out in "what stays unchanged."

9. **Two parallel label systems exist** — `todo_labels` (TodoLabel, separate table, used by `todo_items.label`) and `project_labels` (ProjectLabel, used by `memory_items.project`). This redesign adds a third concept (project on todo, reusing project_labels). Risk: developers may later confuse `todo_items.label` with `todo_items.project`. **MEDIUM** — Architect should leave a comment or add a short ADR-style note in CLAUDE.md "footguns".

10. **The 2,200-line `task-list.tsx` is brittle to in-place changes** — Explorer confirmed. The current file mixes presentational and behavioral concerns. Decomposing into `<FocusCard>`, `<ProjectGroup>`, `<TaskRow>` as part of this task increases scope but is necessary for testability. **MEDIUM** — Architect should explicitly bound the decomposition (only what serves the redesign; don't refactor history/defer flows beyond what's required).

11. **localStorage scoping** — single-user app but the spec says "per user." With one user there's no real risk; but if API key rotation invalidates the session, `lastFocusedId` could point at a stale UUID. **MEDIUM** — render-time guard: if `lastFocusedId` doesn't match a current open todo, treat focus as empty. Cheap to implement.

12. **Personal seed in `project_labels`?** — If "Personal" must be a real selectable value in the picker, it needs to exist in `project_labels`. Two options: (a) seed it in the migration, (b) treat NULL as Personal at render time and don't seed anything. Spec says "defaulting to Personal" at create time, which strongly implies an actual `project_labels.name = 'Personal'` row picker can return. **HIGH** — recommend seeding Personal (idempotent INSERT in migration, with a default colour from the existing palette).

13. **Project picker validates against the real list** — spec says "free-text cannot create a phantom project." The picker must be a closed Select, not a Combobox-with-create. **HIGH**.

For each challenge, label HIGH | MEDIUM | LOW → upgraded/dropped. For anything MEDIUM or HIGH:
- Revisit the codebase if needed
- Update findings with corrected understanding

Stop. Present the reconciled findings (HIGH and MEDIUM items only) before Role 3 begins.

---

## ROLE 3 — SENIOR ARCHITECT

Read the reconciled findings. Design the implementation. Do not write code yet.

Produce a concrete implementation plan covering:

1. **Schema & migration** — design `0015_add_project_to_todos.py`:
   - Add `todo_items.project` column (`String(100)`, nullable, indexed, soft reference to `project_labels.name` — match the `memory_items.project` pattern exactly).
   - Idempotent INSERT of the seed `project_labels` row for "Personal" with a chosen MD3-friendly hex from the existing preset palette (e.g. `#adc6ff` primary, or pick a unique colour from `web/app/settings/page.tsx:23-26`). Document the chosen colour and rationale.
   - Decide whether to backfill existing rows: spec says "existing todos backfill to Personal" — this is render-time fallback, NOT a DB backfill (cleaner; preserves NULL semantics). Justify.
   - Reversible `downgrade()`: drop column + index. Do NOT drop the seeded row in downgrade (other tooling may have referenced it).

2. **Backend API surface** — three changes:
   - `POST /v1/todos` and `PATCH /v1/todos/{id}`: accept optional `project: str | None` (validated against `project_labels.name` — query within transaction, 422 if unknown).
   - `TodoResponse`: add `project: str | None`.
   - **New endpoint**: `PATCH /v1/project-labels/{name}` — accept `{new_name?: str, color?: str}`. In one transaction: update the `project_labels` row, then `UPDATE memory_items SET project = :new WHERE project = :old`, then `UPDATE todo_items SET project = :new WHERE project = :old`. 409 on `new_name` collision. Rate-limited via `@limiter.limit()`.
   - **Modify `DELETE /v1/project-labels/{name}`** — same transactional cascade: NULL out both `memory_items.project` and `todo_items.project` (or leave dangling and rely on render-time fallback — pick one and justify; cascading-to-NULL is the safer default).

3. **Service layer** — `create_todo()` and `update_todo()` accept `project`; pass to model; persist; sync to memory.

4. **Pipeline / sync** — `sync_todo_to_memory()`:
   - Set `MemoryItem.project = todo.project` (sidecar; do NOT add project to the embedded content string — protects Voyage budget).
   - Confirm: no embedding regeneration when only `project` changes? Trace `_try_sync()` to ensure project-only edits don't trigger an unnecessary embed. If they do, gate the embed call on a content-affecting field set.

5. **Frontend decomposition** — split `web/components/dashboard/task-list.tsx` into:
   - `task-list.tsx` (orchestrator: tab state, group computation, focus-card state, localStorage)
   - `focus-card.tsx` (empty + populated states; Done/Skip)
   - `project-group.tsx` (header with mini progress bar, count, chevron, collapse state; "Add to {Project}" row)
   - `task-row.tsx` (extract from current TaskRow)
   - `add-task-form.tsx` (extract; gain a project picker — Select sourced from `useProjectLabels()`, default to "Personal")
   - Bound the refactor: do not touch defer dialog or edit sheet beyond plumbing the new `project` field.

6. **Frontend state model** — explicitly:
   - `focusId: string | null` (UI-only; localStorage key `ob:todo:focusId`); if no match in current open list, treat as null.
   - `collapsedProjects: Set<string>` (localStorage key `ob:todo:collapsedProjects`, JSON-serialized array).
   - `groupBy(filteredTodos)` helper: groups by `todo.project ?? "Personal"`. Order: project_labels list order (alphabetical from API), then "Personal" pinned first or last (Architect picks; recommend pinned first for muscle memory).

7. **Theme adaptation** — concrete mapping from prototype tokens to MD3:
   - Prototype `bg #1c1c1e` → MD3 `var(--md-sys-color-surface)` `#131313`.
   - Prototype `surface #242426` → `var(--md-sys-color-surface-container)` `#201f1f`.
   - Prototype `border #333335` → `var(--md-sys-color-outline-variant)` (or current border token).
   - Prototype `salmon/indigo` → use the project's `color` field from `project_labels` (already user-defined per project).
   - Prototype `green #4caf7d` → `#4ade80` (existing streak-hit accent) for Done state.
   - Typography: keep Space Grotesk/Inter; map prototype's 13.5px task text to the closest existing scale (likely `text-sm`).
   - Border radii: keep current shadcn radii (`rounded-2xl` for focus card, `rounded-md` for chips). Document any deviation.

8. **Test plan** — what contracts must be tested:
   - **Backend pytest**:
     - `POST /v1/todos` with valid `project` → 201; with unknown `project` → 422; missing → 201, project=null.
     - `PATCH /v1/todos/{id}` updating `project` → row updated, history row written with `event_type="updated"`, sync called, `MemoryItem.project` matches.
     - `PATCH /v1/project-labels/{name}` rename → both `todo_items.project` and `memory_items.project` updated; collision → 409.
     - `DELETE /v1/project-labels/{name}` → cascade NULLs both tables (or asserts dangling, depending on Architect's pick); idempotent on missing.
     - `sync_todo_to_memory()` — `MemoryItem.project` set; embedded content string does NOT contain project text; project-only update does not regenerate embedding (if gated).
   - **Frontend Vitest**:
     - `groupBy` helper: NULL → "Personal"; counts match rendered rows.
     - Tab filter applied before group → group counts match tab badge.
     - Focus state: tap unfocused row → focusId set; tap focused row → focusId null; Done → completes + clears focus; Skip → clears focus only (no API call to `/v1/todos`).
     - localStorage round-trip: collapsed state and focusId persisted; stale focusId (no match) → render as empty.
     - AddTaskForm with project picker: defaults to "Personal", required validation (rejects empty), POST body includes `project`.
     - Project rename (Settings) → todo group header label updates after refetch; deletion → affected rows render under "Personal".
   - **Invariants**:
     - Every open todo renders under exactly one group; sum of group counts = filtered todo count.
     - Skip never mutates the database.
     - Mobile (390px) row tappable area ≥40px (assert via computed style or className tokens).
     - No input has `text-sm` without `text-base` modifier (regression guard).

9. **What stays unchanged**
   - Voice / Discord / iOS shortcut creation paths — no extraction, project always NULL.
   - Existing tabs and tab-level filtering (Today/This Week/All) — only the layout BELOW the tab bar changes.
   - The `todo_items.label` column (TodoLabel) is preserved — different concept from project; keep both.
   - The defer dialog, edit sheet, delete flow, history, and learning-item cascade — untouched beyond plumbing the `project` field.
   - Memory composer's existing project picker — unchanged.
   - All theme tokens in `globals.css` — unchanged.

10. **Constraints & Safety**
    - **Performance**: project picker queries `project_labels` once per page load (already cached by `useProjectLabels`); group computation is O(n) over filtered todos. Mini progress bars derived in render. No new DB indexes needed beyond the column-level index on `todo_items(project)`.
    - **Backward compatibility**: `project_id` is the spec's word but the column is `project` (string name) for symmetry with `memory_items.project`. Document this naming choice. Existing API consumers (iOS Shortcuts, Discord bot, voice path) ignore unknown response fields — no breaking change.
    - **Migration plan**: `alembic upgrade head` adds column + index + seeds Personal. Reversible via `alembic downgrade -1` (drops column + index, leaves seeded row).
    - **Failure modes**:
      - Rename collision → 409, no partial update (transaction rollback).
      - Delete cascade → if cascade fails mid-transaction, rollback; client retries.
      - localStorage full / disabled → degrade gracefully (focus and collapse states are in-memory only).
      - Stale focusId → render as empty (no error toast).
    - **Rollback strategy**: revert Alembic migration; revert frontend deploy. Existing `project_labels` rows remain untouched. `memory_items.project` and `todo_items.project` columns can be left in place during rollback (tolerated NULL).

For each decision: provide reasoning. If multiple approaches exist, list them and justify the chosen one.

Stop. Present the plan. Do not implement until Role 4 begins.

If recalled by Role 5 for an architectural revision: read the specific concern raised, update only the affected sections, note what changed and why, return to Role 4 to re-implement the affected parts.

---

## ROLE 3.5 — SENIOR UI/UX EXPERT

> This role requires the UI/UX Pro Max skill installed globally at `~/.claude/skills/ui-ux-pro-max/`.

Read the Architect's plan. Before any implementation begins, generate a design system for the new UI components in this task — but treat the existing Material Design 3 dark theme as a hard constraint, not a starting point.

### Step 1 — Generate design system (reference only)
Run the design system generator scoped to a productivity-app context for layout/interaction inspiration:
```bash
python3 ~/.claude/skills/ui-ux-pro-max/scripts/search.py "productivity dashboard mobile-first task focus card project groups dark theme" --design-system -p "open-brain"
```

### Step 2 — Evaluate and adapt against existing patterns
Reconcile the generated suggestions against:
- The Material Design 3 dark palette in `web/app/globals.css` (primary `#adc6ff`, surface `#131313`, surface-container `#201f1f`, on-surface `#e5e2e1`, on-surface-variant `#c2c6d6`, outline-variant for borders, accent `#4ade80` for done state).
- Space Grotesk (headlines) / Inter (body, labels).
- Existing shadcn/ui components: `Select`, `Dialog`, `Sheet`, `Button`, `Input`, `Tabs`, `Checkbox`, `Progress` (or build a tiny inline progress bar).
- The prototype's structural cues from `docs/ToDo-redisign/README.md` (focus-card geometry, group header arrangement, 38px task indent, 8×8 colour dot, mini progress bar 36×2.5px, chevron rotation, dashed-circle add row).

**Consistency rule:** The redesigned todo screen must look like a polished iteration of the existing app, not a foreign theme. If the generator suggests anything that conflicts with MD3 tokens, drop it.

### Step 3 — Produce a design brief

Output a concise design brief for the Implementer containing:
- **Colour mapping table** — every prototype token mapped to an MD3 variable from `globals.css`. Project accent comes from `project_labels.color` (per-row CSS custom property).
- **Typography** — concrete font sizes/weights for: section label (project name), focus title, task text (active vs default vs completed), tab text, count chip, button labels. Use existing Tailwind scale.
- **Component patterns**:
  - Focus Card empty state ("No focus selected — tap a task to set focus").
  - Focus Card populated state — done + skip buttons, project chip, due-date label.
  - Project Group header — colour dot, name, mini progress bar, count, chevron.
  - Task Row — checkbox, title, project-coloured focused-row background tint, completed strikethrough.
  - "Add to {Project}" row — dashed circle + project-coloured label.
- **Interaction patterns**: tap-to-focus animation (.18s), checkbox transition (.18s), progress-bar fill (.3s ease), chevron rotate (.2s), reduced-motion fallback (no transitions).
- **Anti-patterns to avoid**:
  - No two-line wraps from cramped padding on 390px viewport.
  - No input font-size <16px (Safari zoom).
  - No duplicate DOM trees for mobile/desktop (JSDOM test breakage).
  - No hardcoded colours — all per-project tints derive from `project_labels.color`.
  - No skeleton/loader states beyond what the existing list already does.
- **Pre-delivery checklist**:
  - Contrast ratio AA on body text against surface (the MD3 palette already passes; verify on the project-tinted focused row).
  - Cursor-pointer on every clickable row/button.
  - Focus-visible ring on keyboard nav.
  - 40px+ touch targets on all interactive rows on mobile.
  - Empty state messaging ("No tasks in {Project}", "No focus selected").
  - Reduced-motion respected.

The Implementer treats this brief as a constraint alongside the Architect's plan.

Stop. Present the design brief before Role 4 begins.

---

## ROLE 4 — IMPLEMENTER

Read the Architect's plan and the design brief. Implement exactly as specified.

### Step 1 — Write tests first (mandatory)

Based on the Architect's test plan:

**Backend (pytest)** — new/updated test files:
- `tests/api/test_todos_project.py` (new) — POST/PATCH with project (valid, invalid, null); response shape includes `project`.
- `tests/api/test_project_labels_rename.py` (new) — PATCH rename, collision, color-only edit; cascades into `todo_items` and `memory_items`.
- `tests/api/test_project_labels.py` (existing, extend) — DELETE cascade behavior (NULL out, or assert dangling — match Architect's pick).
- `tests/pipeline/test_todo_sync.py` (existing, extend) — `MemoryItem.project` propagation; embedding NOT regenerated on project-only edits.
- `tests/jobs/test_learning_daily.py` (existing) — confirm learning todos still work with `project=None` (regression guard).

**Frontend (Vitest)** — new/updated test files:
- `web/__tests__/components/focus-card.test.tsx` (new).
- `web/__tests__/components/project-group.test.tsx` (new).
- `web/__tests__/components/task-list.test.tsx` (existing one is a unit-test of `getDueBadge`; add render-level tests for grouping + focus state).
- `web/__tests__/hooks/use-todos.test.ts` (existing, extend) — `addTodo` posts `project`, optimistic insert positions correctly.
- `web/__tests__/hooks/use-project-labels.test.ts` (new or extend if exists) — `renameLabel` flow, optimistic update.

Run the tests (`make test` for backend, `cd web && npm test` for frontend). Confirm they fail for the expected reasons (missing implementation), NOT for setup/import errors. If unexpected failures occur, STOP and reconcile.

### Step 2+ — Implement production code

Order from lowest-risk/foundational to highest-risk/integration:

1. **Migration** — `alembic/versions/0015_add_project_to_todos.py`. Add column + index, idempotent seed of "Personal" project label. Run `alembic upgrade head` against local; run downgrade and back up to verify reversibility.
2. **Model** — add `project` to `TodoItem` in `src/core/models.py`.
3. **Schemas + service** — `TodoCreate`, `TodoUpdate`, `TodoResponse` in `src/api/routes/todos.py`; `create_todo`, `update_todo` in `src/api/services/todo_service.py`. Validate `project` against `project_labels.name` inside the same session.
4. **Pipeline** — `src/pipeline/todo_sync.py`: set `MemoryItem.project`; gate the embed regeneration on content-affecting fields only (decide whether `project` is content-affecting per Architect's call — recommend NO).
5. **New endpoint** — `PATCH /v1/project-labels/{name}` in `src/api/routes/project_labels.py`. Transactional cascade. Rate-limited.
6. **DELETE cascade** — modify `DELETE /v1/project-labels/{name}` to NULL out the column in both tables (per Architect's pick).
7. **Frontend types** — `web/lib/types.ts`: add `project: string | null` to `TodoItem`.
8. **Frontend hook** — `web/hooks/use-project-labels.ts`: add `renameLabel(oldName, newName, color?)`.
9. **Frontend hook** — `web/hooks/use-todos.ts`: thread `project` through `addTodo` and `editTodo` payloads.
10. **Component decomposition** — extract `<TaskRow>`, `<AddTaskForm>` from the monolith; add `<FocusCard>`, `<ProjectGroup>`. New file paths: `web/components/dashboard/focus-card.tsx`, `web/components/dashboard/project-group.tsx`, `web/components/dashboard/task-row.tsx`, `web/components/dashboard/add-task-form.tsx`.
11. **Orchestration** — rewire `web/components/dashboard/task-list.tsx` to compose the new components, manage `focusId` and `collapsedProjects` (with localStorage), and apply `groupBy` after tab-filtering.
12. **Settings rename UI** — extend `web/app/settings/page.tsx` Projects section: inline rename affordance (pencil icon → input → save) wired to `renameLabel`.
13. **Manual mobile verification** — open on 390px viewport (Chrome DevTools or real iPhone): every row reads cleanly, no two-line wraps from cramped padding, no zoom-on-focus.

After each step:
- Run the relevant test suite slice.
- Fix failures before continuing.

### Final verification
- `make test` (full backend suite — all ~957 tests).
- `cd web && npm test` (full Vitest suite — ~247 tests).
- `make lint` (ruff + black --check + mypy).
- Run `make start`, hit the local dashboard, walk through the to-be experience: open todo tab → focus card empty → tap "Reply to Anna" → it lifts to focus → Done → empty again → "+ add" → project picker defaults to Personal → save → renders in Personal group. Rename "Personal" to "Self" in Settings → group header updates without manual reload. Delete a non-Personal project → its todos shift to Personal.
- Re-read business context: every open todo renders under exactly one group; counts match; focus is fully reversible with zero DB writes; no input zoom on tap.

Especially validate: **Skip never silently completes a todo. Tap-to-clear-focus never mutates the DB. Voice creation continues to work and lands under Personal.**

Stop. Do not consider the task complete until reviewed.

If recalled by Role 5 or Role 6 for fixes: apply fixes to the affected code only, do not refactor unrelated code, summarize what changed and why, return to Role 5 for re-review.

---

## ROLE 5 — REVIEWER

Review the implementation as if this were a production PR. Be critical and precise.

**Review cycle: 1 of 2 maximum.**

Inputs: Architect's plan, full diff, Implementer's summary.

Evaluate across:

1. **Correctness** — does it satisfy the plan? Logical errors? Missing cases?
2. **Scope adherence** — anything unnecessary? Anything required but missing?
3. **Code quality** — readability, structure, naming, consistency with existing patterns.
4. **Safety** — null handling, async timing, race conditions, backward compatibility, failure paths.
5. **System impact** — hidden coupling, performance.
6. **Tests & validation** — sufficient and meaningful? Critical paths covered?
7. **Skeptic's concerns (cross-reference Role 2)** — every MEDIUM/HIGH item addressed or consciously accepted with rationale.
8. **Plan fidelity (cross-reference Role 3)** — every deviation justified.
9. **Convention compliance (cross-reference Project Context)** — every checklist item satisfied.
10. **Design compliance (cross-reference Role 3.5)** — design brief honoured; MD3 tokens preserved; no theme drift.

Output: issues grouped by CRITICAL / MAJOR / MINOR with concrete fixes; CRITICAL classified as IMPLEMENTATION or ARCHITECTURAL.

Loop-back rules:
- **CRITICAL IMPLEMENTATION** → Role 4, return here, increment cycle.
- **CRITICAL ARCHITECTURAL** → Role 3 → Role 4, return here, increment cycle.
- **Cycle 2 + unresolved CRITICAL** → mark **BLOCKED**, list issues, stop.
- **No CRITICAL** → proceed to Role 6.

---

## ROLE 6 — SECURITY REVIEWER

Review the entire implementation through a security lens.

**Review cycle: 1 of 2 maximum.**

Evaluate for this task specifically:
- **Project name injection** — `project` is user-supplied text. It is stored in DB, rendered in UI, and (post-sync) in `MemoryItem.project`. Confirm: HTML-escaped on render? Validated against length cap? Enforced via the closed Select picker so free-text can't reach the API?
- **Rename endpoint authorization** — `PATCH /v1/project-labels/{name}` is rate-limited (`@limiter.limit()`), behind `X-API-Key` middleware, and inside a transaction that cannot leak partial state on collision.
- **Cascade leak risk** — DELETE/PATCH on `project_labels` affects N rows in `memory_items` and `todo_items`. Worst-case: a misuse renames every memory/todo project. Mitigation: 409 on collision, transactional rollback, audit log entry (consider a `todo_history` row per affected todo? — only if cheap and Architect approves).
- **localStorage exposure** — `focusId` is a UUID, `collapsedProjects` is an array of strings; not sensitive but document.
- **Voice path regression** — confirm the voice → todo creation path still functions and continues to NOT extract project (no new injection surface).

Standard checklist:
- AuthN/AuthZ on new route.
- Input validation (length cap on project name 100 chars; hex colour regex).
- Rate limiting on `PATCH /v1/project-labels/{name}`.
- Prompt injection — n/a here (no LLM in this path beyond existing voice extractor).
- Dependencies — confirm no new packages added.

Output: **CRITICAL** / **ADVISORY** / **HARDENING**.

Loop-back rules:
- **CRITICAL** → Role 4 → Role 5 → return here, increment cycle.
- **Cycle 2 + unresolved CRITICAL** → mark **BLOCKED**, stop.
- **No CRITICAL** → final security sign-off.

---

## Completion

**TASK COMPLETE** when Role 5 and Role 6 both approve with no CRITICAL issues.
**BLOCKED** if any reviewer's cycle cap (2) is reached with unresolved CRITICAL issues — stop and escalate to the user.

---

## Verification (end-to-end manual + automated)

After Role 5 and Role 6 sign off:

1. `make test` → all backend tests green (existing ~957 + new project tests).
2. `cd web && npm test` → all Vitest tests green (existing ~247 + new component tests).
3. `make lint` → ruff + black --check + mypy clean.
4. `make start` → walk the to-be experience on http://localhost:3000:
   - Open Todo tab → Focus Card empty.
   - Tap unfocused todo → it lifts into Focus Card.
   - Tap focused row → Focus Card empties; no DB write.
   - Done → completes; Focus Card empties.
   - Skip → Focus Card empties; no DB write; row remains.
   - "+ Add" → project picker defaults to Personal → save → row appears under Personal.
   - "Add to OB" row inside OB group → opens form pre-filled with OB.
   - Settings → rename "OB" to "Open Brain" → group header updates after refetch (no manual reload of dashboard).
   - Settings → delete "Open Brain" → its todos render under Personal.
5. Mobile (390px Chrome DevTools): no two-line wraps, no zoom-on-input, all rows ≥40px tall.
6. Reload page → focusId and collapsed-groups state persist; stale focusId (after a complete) → renders as empty.
7. Run `alembic downgrade -1` → confirm `todo_items.project` column drops cleanly; run `alembic upgrade head` → restored.
