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
- **Commitment entries are pre-generated (daily cadence only)**: `POST /v1/commitments` creates all `commitment_entries` rows for the full date range upfront for `cadence="daily"`. Aggregate commitments skip entry pre-generation — progress comes from linked Strava activities. The miss detection cron (`src/jobs/commitment_miss.py`) flips yesterday's pending→miss for daily, completes aggregate commitments whose `end_date == yesterday`, and triggers `sync_commitment_summary_to_memory()` best-effort for completed aggregates.
- **Aggregate commitment progress is always recalculated from scratch**: `update_commitment_progress()` in `src/api/routes/strava.py` sums metrics from all linked activities via the `commitment_activities` junction table. Never increment/decrement — always recompute. This is safe against race conditions and Strava update/delete events.
- **Strava webhook links activities to aggregate commitments**: After `_fetch_and_upsert_activity()`, the handler calls `_link_activity_to_commitments()` which finds active aggregate commitments whose date window contains the activity's `started_at`, inserts junction rows (dedup via unique constraint), and recalculates progress. Delete events unlink and recalculate. After linking, the webhook also calls `sync_strava_activity_to_memory()` best-effort (try/except) — embedding failure never blocks the 200 response to Strava.
- **memory_items.tags is JSONB with GIN index**: Array of colon-namespaced strings (e.g. `["training:weekly"]`). Query with PostgreSQL `@>` operator. SQLite tests use JSON functions. Set during sync operations, not user-facing yet.
- **Learning todos use a dedicated FK, not a label**: `todo_items.learning_item_id` (FK → `learning_items.id`, ON DELETE SET NULL) marks todos created by the learning cron. Do NOT reuse the `label` column — filtering is equality-only and collides with user labels. Cascade on `status="done"` wired via `_try_cascade_learning_item()` in `src/api/services/todo_service.py`; best-effort, never blocks the todo update. `sync_todo_to_memory()` ignores `learning_item_id` so learning todos embed like any other todo.
- **Learning cron idempotency = query-before-create**: `src/jobs/learning_daily.py::run_learning_selection` counts today's `learning_item_id IS NOT NULL` todos and only fills the gap to `learning_daily_todo_count`. Safe to re-run; shared with `POST /v1/learning/refresh`. Fallback when LLM fails is DETERMINISTIC (oldest pending items sorted by `created_at + id`), never random — same inputs produce same todos within a day.
- **Learning data does NOT sync to memory_items**: `learning_topics/sections/items` are groomed curriculum state. Only the derived todos sync (via existing `todo_sync.py`). Do not route learning CRUD through `memory_service.ingest_memory()`.

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

Check directory structure before creating new top-level modules or folders.

## Project Docs

- `PROGRESS.md` — current status, open tech debt, deployment info
- `HISTORY.md` — completed phases and session notes (read-only reference)
- `ARCHITECTURE.md` — system architecture, module ownership, data flow
