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
- **Task gating**: Sources in `TASK_SKIP_SOURCES` (`src/pipeline/constants.py`) skip Task row creation. This is `AUTO_CAPTURE_SOURCES | {"claude-code-manual", "daily-pulse"}` — manual ingestions and pulse syncs get full importance but no stale tasks.
- **Immutability**: `raw_memory` is append-only. Corrections create new `memory_items` with `supersedes_memory_id`. No soft deletes.
- **importance_score is GENERATED**: never UPDATE it directly. Set `base_importance` or `dynamic_importance` and the column recomputes.
- **Prompt injection defense**: all user input wrapped in `<user_input>...</user_input>` delimiters in LLM prompts.
- **Settings from env only**: no config files. `SecretStr` for API keys (never log raw). See @.env.example for all vars.
- **Supabase direct connection (port 5432)**: never use the PgBouncer pooler (port 6543) — `SELECT FOR UPDATE SKIP LOCKED` breaks.
- **Tests run on SQLite, prod on PostgreSQL**: all ORM types need `.with_variant()` for cross-DB compat (JSONB→JSON, Vector→JSON).
- **Every `/v1/*` route needs `@limiter.limit()`**: no global fallback — undecorated routes are unprotected.
- **RLS enabled on all tables**: Migration 0009 enables Row-Level Security with deny-all (no policies). App connects as `postgres` superuser (bypasses RLS). New tables must include `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` in their migration.

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

Check directory structure before creating new top-level modules or folders.

## Project Docs

- `PROGRESS.md` — current status, open tech debt, deployment info
- `HISTORY.md` — completed phases and session notes (read-only reference)
- `ARCHITECTURE.md` — system architecture, module ownership, data flow
