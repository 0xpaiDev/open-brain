# Decisions

Append-only architectural decision log. Dated entries, newest at the top.
Hard cap: 5,000 characters. Trim or summarise the oldest entries when adding
would overflow. Manual + agent-on-request only — the daily / weekly curators
do not touch this file.

Read at session start as part of the tier-0 frozen snapshot.

## 2026-05-17 — Architecture Decisions Baseline

Migrated from CLAUDE.md static bullets; code is source of truth for details.

**Sync pipeline**
- **Todo sync**: mutations sync best-effort into `memory_items` (`todo_sync.py`); todo writes always succeed.
- **Pulse sync**: completed/parsed pulses sync via `pulse_sync.py`; triggered in `PATCH /v1/pulse/today`.
- **Training sync bypasses refinement queue**: direct RawMemory+MemoryItem (no LLM) in `src/pipeline/training_sync.py` — weekly/strava/commitment-summary sources.
- **Auto-capture importance capping**: add new auto-capture sources to `AUTO_CAPTURE_SOURCES` (`src/pipeline/constants.py`), not as hardcoded strings.
- **Task gating**: `TASK_SKIP_SOURCES` skips Task row creation for auto-captured and manual-ingest sources.
- **Todo hard-delete supersedes memory**: flips `is_superseded` without re-embedding (`supersede_memory_for_todo()`); reuse for "remove from search, keep audit" pattern.
- **Todo edits cost a Voyage embedding each**: content-mutating PATCH triggers new 1024-d vector; `content_dirty` flag skips embedding on project-only edits.

**Memory & retrieval**
- **`/v1/memory/{id}/expand` is tier-2 disclosure**: full content + raw_text + 3 same-source neighbors by `created_at`.
- **`memory_items.tags` is JSONB+GIN**: colon-namespaced strings, query with `@>`, not yet user-facing.
- **SessionEnd hook backend**: `OB_SESSION_END_BACKEND` — `cli`/`api`/`auto`.

**Voice**
- **Voice routing is deterministic, not LLM**: regex intent classifier (`voice_intent.py`); Haiku only invoked after intent is locked.
- **Web + iOS share the same voice endpoint**: `POST /v1/voice/command`; memory refresh only fires for `action === "memory"`.

**Commitments**
- **Commitment entries pre-generated (daily only)**: upfront at `POST /v1/commitments`; aggregates derive progress from Strava activities.
- **`commitment.status` = period ended, not goal reached**: `completed` fires on end_date; `goal_reached` is a derived bool, not a status value.
- **Aggregate progress always recalculated from scratch**: never increment/decrement; recompute from all linked activities.
- **Strava webhook links activities to aggregate commitments**: `_link_activity_to_commitments()` after upsert; delete events unlink and recalculate.
- **Multi-exercise kinds**: `single` (legacy), `routine` (daily), `plan` (imported schedule); `commitment.exercise` nullable.
- **Plan import SHA-256 idempotency hash**: `Commitment.import_hash` index, no UNIQUE constraint (single-user acceptable).
- **Multi-exercise day "hit" = all exercises logged**: `_check_and_flip_entry()` flips/reverts after every log or soft-delete.
- **Exercise logs soft-deleted**: `CommitmentExerciseLog.deleted_at`; hard deletes rejected.
- **Plan import deduplicates exercises by `(name, sets)`**: unique constraint `uq_commitment_exercise_name_sets` (migration 0018).
- **Strava webhook public, verified by handshake**: POST has no HMAC; security relies on `strava_verify_token` subscription handshake.
- **Strava tokens DB-backed with auto-refresh**: bootstraps from env on first use; never read tokens from env in handlers.
- **TSS calculated (not from Strava)**: power-based (`NP/FTP`), HR-based fallback (`STRAVA_MAX_HR`/`STRAVA_RESTING_HR`), both disabled by default.

**Learning**
- **Learning todos use dedicated FK, not label**: `todo_items.learning_item_id`; cascade on done via `_try_cascade_learning_item()`.
- **Learning cron has two orthogonal dedup checks**: same-day gate + cross-day open-item filter (`src/jobs/learning_daily.py`).
- **`TodoItem.learning_item` uses `lazy="raise"`**: every read path must eager-load via `_with_learning_topic()`.
- **Learning data does NOT sync to memory_items**: only derived todos sync.
- **Learning bulk import is two-step**: `dry_run=true` counts; `dry_run=false` commits atomically.
- **Learning materials one-to-one with topics**: `UniqueConstraint("topic_id")`; GET returns `null` (not 404) when absent.

**Todos & projects**
- **Bulk todo ops take explicit IDs**: `POST /v1/todos/defer-all` loops `update_todo()`; skipped items in `skipped:[{reason}]`.
- **Project field is soft reference, no FK**: `String(100)` nullable; rename cascades atomically via `PATCH /v1/project-labels/{name}`.
- **Focus + collapsed state persist to localStorage**: `ob:todo:focusId`, `ob:todo:collapsedProjects`; stale-id guard on render.

---

## 2026-05-17 — Claude Code Memory Flywheel

Two-layer markdown (personal `~/.claude/.../memory/` + project `context/`) + SessionEnd auto-capture + tier-0/1/2/3 retrieval contract. Design spec: `docs/superpowers/specs/2026-05-17-claude-code-memory-flywheel-design.md`.
