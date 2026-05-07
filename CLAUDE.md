# CLAUDE.md

## Quick Start

```bash
# Backend (local, no Docker)
make start          # API + worker + Discord bot (logs: /tmp/ob-*.log)
make stop
make test           # pytest
make lint           # ruff + black --check + mypy

# Frontend
cd web && npm test           # Vitest
cd web && npx playwright test  # E2E

# Docker (production) — profiles are mandatory
make up             # api + worker + discord + scheduler
docker compose --profile web up -d        # Next.js dashboard
docker compose --profile caddy up -d      # TLS reverse proxy
docker compose --profile migrate run --rm migrate  # Alembic migrations
```

## Escalate Before Proceeding

- Schema changes (add/remove/rename tables or columns) — critical files: `src/core/models.py`, `alembic/versions/*`
- Architecture shifts (technology swaps, new external services)
- API contract changes (request/response shape)
- Security (auth methods, encryption, key management)
- Ranking formula changes (`src/retrieval/search.py`)
- Extraction prompt changes (`src/llm/prompts.py`)

## Git

- Branch: `master`. Commit format: `type(scope): description` (e.g. `feat(web): add defer popover`)
- Types: feat, fix, refactor, test, docs, chore

## Architecture Decisions

- **Todo sync to memory**: Todo mutations sync into `memory_items` via `src/pipeline/todo_sync.py`. This makes todos searchable through RAG chat. The sync is best-effort (wrapped in try/except) — todo writes always succeed even if sync fails.
- **Pulse sync to memory**: Completed/parsed pulses sync into `memory_items` via `src/pipeline/pulse_sync.py`. Triggers in `PATCH /v1/pulse/today` when status reaches "completed" or "parsed". Same best-effort pattern as todo sync.
- **Auto-capture importance capping**: Sources in `AUTO_CAPTURE_SOURCES` (`src/pipeline/constants.py`) have importance capped. Add new auto-capture sources there, not as hardcoded strings.
- **Task gating**: Sources in `TASK_SKIP_SOURCES` (`src/pipeline/constants.py`) skip Task row creation. This is `AUTO_CAPTURE_SOURCES | {"claude-code-manual", "daily-pulse", "training-weekly", "strava-activity", "commitment-summary"}` — manual ingestions, pulse syncs, and training data get full importance but no stale tasks.
- **Immutability**: `raw_memory` is append-only. Corrections create new `memory_items` with `supersedes_memory_id`. No soft deletes.
- **importance_score is GENERATED**: never UPDATE it directly. Set `base_importance` or `dynamic_importance` and the column recomputes.
- **Prompt injection defense**: all user input wrapped in `<user_input>...</user_input>` delimiters in LLM prompts.
- **Settings from env only**: no config files. `SecretStr` for API keys (never log raw). See @.env.example for all vars.
- **Supabase direct connection (port 5432)**: never use the PgBouncer pooler (port 6543) — `SELECT FOR UPDATE SKIP LOCKED` breaks.
- **Tests run on SQLite, prod on PostgreSQL**: all ORM types need `.with_variant()` for cross-DB compat (JSONB→JSON, Vector→JSON).
- **Every `/v1/*` route needs `@limiter.limit()`**: no global fallback — undecorated routes are unprotected.
- **RLS enabled on all tables**: Migration 0009 (base tables) + 0010 (training tables) enable Row-Level Security with deny-all (no policies). App connects as `postgres` superuser (bypasses RLS). New tables must include `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` in their migration.
- **Voice command routing is deterministic, not LLM**: `POST /v1/voice/command` (`src/api/routes/voice.py`) classifies intent (create/complete/memory) via regex in `src/api/services/voice_intent.py`. Haiku is only invoked *after* the intent is locked, to extract fields. Keeps the non-LLM path fast and keeps mutations predictable.
- **Web voice uses the same deterministic endpoint as iOS**: `SmartComposer` voice tab posts to `POST /v1/voice/command` via `submitVoiceCommand` in `web/hooks/use-memories.ts`. Memory list refresh fires only for `action === "memory"` — create/complete only touch todos, not `memory_items`. Ambiguous responses show a warning toast and preserve the transcript.
- **Memory ingest lives in a service**: `src/api/services/memory_service.py` `ingest_memory()` is the shared helper for `/v1/memory` and `/v1/voice/command`. Do not re-inline dedup/RawMemory/RefinementQueue logic in new routes.
- **Todo hard-delete supersedes memory, doesn't re-embed**: `DELETE /v1/todos/{id}` calls `supersede_memory_for_todo()` in `src/pipeline/todo_sync.py` — flips `is_superseded=True` on matching memory_items without writing a new embedding. Reuse this helper for any "remove from hybrid search but keep audit trail" case. Do NOT call `sync_todo_to_memory()` for deletes — it would write a fresh embedding for a vanished todo.
- **Todo edits cost a Voyage embedding each**: every `PATCH /v1/todos/{id}` that mutates description/due_date triggers `sync_todo_to_memory()`, which generates a new 1024-d vector. Append-only by design — no in-place embedding update exists. Rate-limit or batch-edit flows should keep this cost in mind.
- **Training sync bypasses refinement queue**: `src/pipeline/training_sync.py` follows the pulse_sync/todo_sync direct-create pattern (RawMemory + MemoryItem + embedding in one transaction). Functions: `sync_weekly_training()` (source: `training-weekly`), `sync_strava_activity_to_memory()` (source: `strava-activity`), `sync_commitment_summary_to_memory()` (source: `commitment-summary`). Weekly summaries are pre-structured — routing them through `ingest_memory()` would waste an LLM call and risk mangling the format.
- **Strava webhook is public, verified by subscription handshake**: `/v1/strava/webhook` is in `_PUBLIC_PATHS` (no API key). GET verifies subscription with `strava_verify_token` (timing-safe comparison). POST does NOT receive HMAC signatures from Strava — security relies on the verify_token handshake during subscription creation. Both are rate-limited.
- **Strava tokens are DB-backed with auto-refresh**: `strava_tokens` table (migration 0012) stores OAuth tokens. `_get_valid_access_token()` in `src/api/routes/strava.py` bootstraps from env vars on first use, then refreshes automatically when expired. Never read tokens from env vars directly in route handlers.
- **TSS is calculated, not from Strava API**: Strava doesn't provide TSS. Primary method: `weighted_average_watts` (NP) + `STRAVA_FTP` → `TSS = (duration × NP × IF) / (FTP × 3600) × 100`. Fallback when no power meter: HR-based TSS using `STRAVA_MAX_HR` and `STRAVA_RESTING_HR` env vars — `rpe = (avg_hr − resting_hr) / (max_hr − resting_hr)`, `hrTSS = (duration_h × rpe × 100)`. Both vars default to 0 (disabled). Set both to enable fallback (`src/api/routes/strava.py` `_fetch_and_upsert_activity()`). Logs `tss_method="power"` or `"hr_estimate"`. Warns `strava_tss_unavailable` when neither path produces a value.
- **Commitment entries are pre-generated (daily cadence only)**: `POST /v1/commitments` creates all `commitment_entries` rows for the full date range upfront for `cadence="daily"`. Aggregate commitments skip entry pre-generation — progress comes from linked Strava activities. The miss detection cron (`src/jobs/commitment_miss.py`) flips yesterday's pending→miss for daily, and flips *both* daily and aggregate commitments with `end_date <= yesterday` from `active`→`completed` (the `<=` — not `==` — catches up after a missed cron run). Completed aggregates trigger `sync_commitment_summary_to_memory()` best-effort.
- **`commitment.status` means "period ended", not "goal reached"**: The status enum stays `active|completed|abandoned` — `completed` fires on end_date regardless of whether the target was met. The UI distinguishes via `CommitmentResponse.goal_reached` (derived, `bool | None`), computed in `_compute_goal_reached()` (`src/api/routes/commitments.py`): `None` while active in-period; `True` once every aggregate target is met (or every daily entry is `"hit"`); `False` otherwise. Render "Not Reached" state when `status="completed" && goal_reached=false`. Do NOT add a new `"not_reached"` status value — keep the schema binary and derive the outcome.
- **Aggregate commitment progress is always recalculated from scratch**: `update_commitment_progress()` in `src/api/routes/strava.py` sums metrics from all linked activities via the `commitment_activities` junction table. Never increment/decrement — always recompute. This is safe against race conditions and Strava update/delete events.
- **Strava webhook links activities to aggregate commitments**: After `_fetch_and_upsert_activity()`, the handler calls `_link_activity_to_commitments()` which finds active aggregate commitments whose date window contains the activity's `started_at`, inserts junction rows (dedup via unique constraint), and recalculates progress. Delete events unlink and recalculate. After linking, the webhook also calls `sync_strava_activity_to_memory()` best-effort (try/except) — embedding failure never blocks the 200 response to Strava.
- **memory_items.tags is JSONB with GIN index**: Array of colon-namespaced strings (e.g. `["training:weekly"]`). Query with PostgreSQL `@>` operator. SQLite tests use JSON functions. Set during sync operations, not user-facing yet.
- **Learning todos use a dedicated FK, not a label**: `todo_items.learning_item_id` (FK → `learning_items.id`, ON DELETE SET NULL) marks todos created by the learning cron. Do NOT reuse the `label` column — filtering is equality-only and collides with user labels. Cascade on `status="done"` wired via `_try_cascade_learning_item()` in `src/api/services/todo_service.py`; best-effort, never blocks the todo update. `sync_todo_to_memory()` ignores `learning_item_id` so learning todos embed like any other todo.
- **Learning cron idempotency = query-before-create**: `src/jobs/learning_daily.py::run_learning_selection` counts today's `learning_item_id IS NOT NULL` todos and only fills the gap to `learning_daily_todo_count`. Safe to re-run; shared with `POST /v1/learning/refresh`. Fallback when LLM fails is DETERMINISTIC (oldest pending items sorted by `created_at + id`), never random — same inputs produce same todos within a day.
- **Learning data does NOT sync to memory_items**: `learning_topics/sections/items` are groomed curriculum state. Only the derived todos sync (via existing `todo_sync.py`). Do not route learning CRUD through `memory_service.ingest_memory()`.
- **Bulk todo ops loop `update_todo()`, take IDs, and report skipped items**: `POST /v1/todos/defer-all` (`src/api/routes/todos.py`) accepts an explicit `todo_ids` list (1–50) and iterates the existing service function — history rows, memory re-embed, and `event_type="deferred"` detection stay identical to single-defer. Rejected: a filter-based endpoint (`scope="today"`) — frontend `filterTodayTodos` uses local-time semantics (Europe/Vilnius) and replicating that server-side is a TZ footgun. Non-open or missing IDs go into `skipped: [{todo_id, reason: "not_found"|"not_open"}]` rather than aborting the batch. Follow the same pattern for any future bulk mutations (bulk-complete, bulk-cancel).
- **Project field on todos + memories (soft reference, no FK)**: `todo_items.project` and `memory_items.project` are `String(100)` nullable columns (no foreign key). Valid values are `project_labels.name` (validated in `TodoCreate`/`TodoUpdate`); NULL renders as "Personal" at render time. Rename cascades via `PATCH /v1/project-labels/{name}` — atomically updates both tables in one transaction, returns 409 on collision. Delete cascades to NULL via modified `DELETE` route. This keeps the schema simple (no junction table) and allows todos + memories to share one project taxonomy.
- **Embedding cost optimization via `content_dirty` flag**: When a todo's `project` field changes but content (description/priority/status/due_date/label) does NOT, skip the Voyage embedding regeneration. In `update_todo()`, detect dirty fields via `_CONTENT_FIELDS = ("description", "priority", "status", "due_date", "label")` set, pass `content_dirty` bool to `sync_todo_to_memory()`. If `content_dirty=False`, update `memory_items.project` in-place (no supersede, no embedding); if `True`, full supersede + new embedding as normal. This saves Voyage API cost on project-only edits while preserving all other sync semantics.
- **Focus state + collapsed groups persist to localStorage**: `task-list.tsx` maintains `focusId` and `collapsedProjects` state in localStorage (`ob:todo:focusId`, `ob:todo:collapsedProjects`). On render, apply a stale-id guard: if the persisted `focusId` no longer exists in the current open list, treat as null (no error path). Collapsed state is a `Set<string>` of project keys, toggled via project-group header click, persisted as JSON array.
- **Learning bulk import is two-step (dry-run then commit)**: `POST /v1/learning/import?dry_run=true` returns counts with zero DB writes; `?dry_run=false` commits atomically. Schema at `src/api/schemas/learning_import.py`. Service: `import_curriculum()` in `src/api/services/learning_service.py`. `position` is forbidden in payloads (`extra="forbid"`); server auto-assigns from array order.
- **Learning materials are one-to-one with topics**: `learning_materials` table (migration 0016) has `UniqueConstraint("topic_id")`. GET material returns `null` (not 404) when topic exists but has no material. `has_material: bool` is only emitted by `topic_to_dict()` when `include_children=True` (to avoid lazy-load MissingGreenlet on create/update routes that don't eagerly load the relationship).
- **Multi-exercise commitments: three kinds**: `kind="single"` (legacy, one exercise, use `/log` endpoint), `kind="routine"` (1–5 exercises every day, use `/exercises/{id}/log`), `kind="plan"` (imported schedule with workout/rest days, same log endpoint as routine). `commitment.exercise` is now nullable. Plan kind is created only via `POST /v1/commitments/import?dry_run=...` — never via `POST /v1/commitments`.
- **Plan import uses SHA-256 idempotency hash**: `Commitment.import_hash` stores SHA-256 of canonicalized `CommitmentImportRequest` JSON. Re-import with same hash returns 200 with `already_exists: true` and zero DB writes. Index `ix_commitments_import_hash` exists for the lookup. Hash is NOT a security guarantee — no unique constraint, just an index.
- **Multi-exercise day "hit" = all exercises logged**: `_check_and_flip_entry()` in `commitments.py` fires after every exercise log and soft-delete. It queries distinct `exercise_id`s with non-deleted logs today, compares to total exercises. Flip to "hit" when complete, revert to "pending" when a log is deleted and the set is no longer full.
- **`ExerciseResponse.logged_today` is required for correct UI state**: The list/detail/PATCH routes query today's active logs and pass them to `_commitment_to_response()` → `_exercise_to_response()`. Without this, `MultiExerciseCommitmentCard` cannot show per-exercise completion. Do NOT remove this query or stub it out — it was the critical bug caught in review.
- **Plan kind: workout-day-only entry pre-generation**: `import_commitment_plan()` creates `CommitmentEntry` rows only for workout days. Rest days have no entry. The existing "No entry for today" error naturally serves as rest-day rejection — no special status needed.
- **Exercise logs are soft-deleted, not hard-deleted**: `CommitmentExerciseLog.deleted_at` is set on "delete". All queries filter `deleted_at.is_(None)`. Hard deletes are rejected. This preserves audit trail.
- **Plan import deduplicates exercises by `(name, sets)`, not just `name`**: `import_commitment_plan()` (`src/api/services/commitment_import_service.py`) uses `dict[tuple[str, int | None], CommitmentExercise]`. Same exercise with different set counts → separate `CommitmentExercise` rows. Unique constraint on `commitment_exercises` is `(commitment_id, name, sets)` — name is `uq_commitment_exercise_name_sets` (migration 0018). `exercise_count` in `CommitmentImportResult` is distinct `(name, sets)` pairs, not `max(exercises per day)`.

## Footguns

These patterns can be re-introduced by new code. The fixes exist but aren't enforced by linters.

- **No `register_vector(conn)`** — conflicts with `pgvector.sqlalchemy.Vector`. Adding the asyncpg codec breaks inserts.
- **`session.commit()` is required** — `flush()` alone does not persist. `AsyncSession` close = implicit rollback. Every terminal operation must commit.
- **`session.refresh(obj)` after commit** — `server_default`/`onupdate` columns expire after flush. Accessing in async triggers `MissingGreenlet`.
- **`_get_settings()` lazy helper** — module-level `from src.core.config import settings` captures `None` or stale prod values. Use `_get_settings()` in middleware/routes.
- **UUID + raw SQL on SQLite** — SQLite stores UUIDs as 32-char hex (no dashes). Use SQLAlchemy Core (`sa_delete`, `sa_update`) not `text()`.
- **Alembic, not `create_all()`** — embedding column is JSONB in ORM but `vector(1024)` in DDL. `create_all()` skips the conversion.
- **Google deps are optional** — guard `google.auth`/`googleapiclient` imports with `try/except ImportError`.
- **Mobile input font-size ≥ 16px** — Safari/Chrome auto-zoom on inputs with `font-size < 16px`. All `<input>`, `<textarea>`, `<select>` must use `text-base md:text-sm` (not bare `text-sm`). Base components (`input.tsx`, `textarea.tsx`, `select.tsx`) already follow this pattern.
- **memory_type uses underscores** — backend stores `daily_pulse`, `todo_completion`, `todo` (not hyphens). Frontend `TYPE_CONFIG` keys must match exactly.
- **No duplicate DOM for responsive layouts** — JSDOM ignores CSS `hidden`/`sm:hidden`, so duplicate elements (e.g. mobile+desktop controls) break tests. Use single DOM + `flex-wrap` with responsive classes instead.
- **Haiku training cutoff breaks relative dates** — Haiku (`claude-haiku-4-5`) resolves "today"/"tomorrow"/"Friday" to its training-cutoff date (~April 2025), not the real current date, unless the system prompt explicitly anchors on today's ISO date. Any prompt that accepts relative date references must inject `date.today()` at call time. See `src/llm/prompts.py::build_voice_create_system_prompt` for the pattern.
- **Commitment route params must be `uuid.UUID`, not `str`** — SQLite stores UUIDs as 32-char hex. Passing a string `commitment_id` to `select().where(Commitment.id == commitment_id)` breaks on SQLite with `'str' object has no attribute 'hex'`. Use `session.get(Model, id)` with `id: uuid.UUID` in the route signature (same pattern as todos).
- **Haiku tolerates Siri dictation variety, the classifier must too** — Siri transcribes voice commands with loose phrasings: "Create a task", "Make a to-do", "Make it to do" (mishearing "make a"), hyphenated "to-do". The `voice_intent.py` regex accepts `(create|make|add|new) + optional (a|an|it) + (todo|task)` and `_normalize()` collapses `to-do`/`to do` → `todo`. When adding new triggers, extend both.
- **`supercronic` does NOT support `@reboot`** — tested against the live container; `supercronic -test` returns `fatal: bad crontab line` for any `@reboot` entry. Startup-only tasks (e.g. one-shot sweeps on container boot) must be added to the Docker `command:` wrapper, not `crontab`.
- **`MAX(...) or -1` is a Python falsy bug** — `sql_max_result or -1` returns `-1` when the MAX is `0` because `0` is falsy. Always use `result if result is not None else -1` for SQL aggregate null checks (e.g. `select(func.max(LearningTopic.position))`).
- **`expire_on_commit=False` causes identity map staleness in shared-session tests** — Tests share `async_session` with route handlers via `override_get_db`. After a handler commits a new relationship row (e.g. `LearningMaterial`), the parent object's relationship attribute stays cached at its pre-commit value (e.g. `None`). Subsequent `selectinload` queries skip the relationship because it appears already loaded. Fix: call `session.expire_all()` in the test before the next GET request.
- **Check `alembic/versions/` before assigning a migration number** — PROGRESS.md deployment notes reflect the live Supabase DB state (may be ahead of `master`). Always `ls alembic/versions/` to find the true latest revision before creating a new one.
- **`Button` does not support `asChild`** — `web/components/ui/button.tsx` uses `@base-ui/react/button`, not Radix. There is no `asChild` prop. To render a Link that looks like a Button, apply `buttonVariants({ variant })` as a className on the `<Link>` directly: `<Link href="..." className={buttonVariants({ variant: "outline" })}>`.
- **Tailwind v4 — no `tailwind.config.ts`** — This project uses Tailwind v4 with PostCSS. There is no `tailwind.config.ts`. Plugin registration uses the `@plugin` CSS directive in `web/app/globals.css` (e.g., `@plugin "@tailwindcss/typography"`), not a JS config object.
- **React 19 dynamic route `params` is a Promise** — Next.js 16 + React 19: `params` in `page.tsx` must be typed as `Promise<{ id: string }>` and unwrapped with `use(params)` in client components. The first `[id]` route is `web/app/learning/topics/[id]/page.tsx` — use it as the reference pattern.

Check directory structure before creating new top-level modules or folders.

## Project Docs

- `PROGRESS.md` — current status, open tech debt, deployment info
- `HISTORY.md` — completed phases and session notes (read-only reference)
- `ARCHITECTURE.md` — system architecture, module ownership, data flow
