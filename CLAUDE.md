# CLAUDE.md

## Session Context

At session start, also read these project-bound state files in addition to the
auto-loaded `~/.claude/projects/.../memory/MEMORY.md`:

- `context/STATE.md` — active threads, current sprint, in-flight decisions
- `context/DECISIONS.md` — architectural decisions (dated, append-only)

These three together form the **tier-0 frozen snapshot** (~3,000 tokens). Mid-session
writes to any of them persist to disk but only take effect next session.

## Memory Retrieval

When the user asks about past context, conversations, or decisions, escalate
retrieval tiers in order. Only move to the next tier if the previous one didn't
answer.

- **Tier 0** — already in context (free, instant): `MEMORY.md` + supporting
  files in `~/.claude/projects/.../memory/`, plus `context/STATE.md` and
  `context/DECISIONS.md`. Try this first — most "what's our prod domain?" style
  questions are answered here without a tool call.

- **Tier 1** — `mcp__open-brain__search_memory("query", limit=5)`: hybrid vector
  + keyword search across all `memory_items`. Returns top chunks with memory_ids.

- **Tier 2** — `mcp__open-brain__memory_expand(memory_id)`: full content of one
  item + parent `RawMemory.raw_text` + up to 3 same-source neighbors. Use when a
  T1 hit looks relevant but the snippet is truncated.

- **Tier 3** — `mcp__open-brain__get_context("query", limit=20)`: token-budgeted
  broad dump (~8,000 tokens max). Last resort, expensive — use only when T0–T2
  failed.

If all four tiers come up empty: "I don't have a record of that. Want me to
search the web?"

## Quick Start

```bash
# Backend (local, no Docker)
make start          # API + worker (logs: /tmp/ob-api.log /tmp/ob-worker.log)
make stop
make test           # pytest
make lint           # ruff + black --check + mypy

# Frontend
cd web && npm test           # Vitest
cd web && npx playwright test  # E2E

# Docker (production) — profiles are mandatory
make up             # api + worker + scheduler
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

## Footguns

These patterns can be re-introduced by new code. The fixes exist but aren't enforced by linters. Target: ≤35 entries — trim stale ones before adding new ones. See `context/DECISIONS.md` for architectural decisions (why things are the way they are).

- **`importance_score` is GENERATED** — never `UPDATE` it directly. Set `base_importance` or `dynamic_importance`; the column recomputes (`src/core/models.py`).
- **Settings from env only** — no config files. `SecretStr` for API keys (never log raw). See `.env.example`.
- **Supabase direct connection port 5432** — never use the PgBouncer pooler (port 6543); `SELECT FOR UPDATE SKIP LOCKED` breaks.
- **Tests run on SQLite, prod on PostgreSQL** — all ORM types need `.with_variant()` for cross-DB compat (JSONB→JSON, Vector→JSON).
- **Every `/v1/*` route needs `@limiter.limit()`** — no global fallback; undecorated routes are unprotected.
- **RLS on all new tables** — migrations 0009/0010 set deny-all RLS. Every new table must include `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` (`alembic/versions/`).
- **`raw_memory` is append-only** — corrections create new `memory_items` with `supersedes_memory_id`. No soft-deletes.
- **Memory ingest lives in `ingest_memory()`** — `src/api/services/memory_service.py`. Do not re-inline dedup/RawMemory/RefinementQueue logic in new routes.
- **Prompt injection defense** — wrap all user input in `<user_input>…</user_input>` delimiters in LLM prompts (`src/llm/prompts.py`).
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
- **SQLite stores datetimes naive, Postgres stores them tz-aware** — subtracting one from the other inside the same test session raises `TypeError: can't subtract offset-naive and offset-aware datetimes`. When you need cross-DB time arithmetic (e.g. neighbor distance), use a helper like `_as_utc_timestamp()` in `src/api/services/memory_service.py` that coerces both sides to UTC POSIX timestamps before differencing. Don't rely on `EXTRACT(EPOCH FROM ...)` — Postgres-only and silently breaks SQLite tests.
- **`/schedule` slash command runs on Anthropic-hosted runtime, NOT your laptop** — markdown specs in `cron/jobs/*.md` describe behaviour, but `/schedule create` can't reach `~/.claude/projects/.../memory/` or `context/sessions/`. Local memory cron MUST go through `make memory-install-cron` (writes `/etc/cron.d/ob-memory-flywheel` + anacron entries) or `make memory-distill`/`memory-curate` on demand. The SessionStart hook is the in-session catch-up belt.
- **SessionStart hook self-scopes by cwd vs script repo** — `scripts/claude-code/session-start-distill.sh` exits silently if `cwd != $(repo containing the script)`. Safe to install as a global `~/.claude/hooks/session-start-distill.sh` symlink — it no-ops in every other repo. Only fires on `source=startup` (not resume/clear/compact). Uses `flock` for single-fire across parallel CC windows + throttle via `context/.last-distill` mtime ≥ `OB_SESSION_START_MIN_HOURS` (default 6h).

Check directory structure before creating new top-level modules or folders.

## Project Docs

- `PROGRESS.md` — current status, open tech debt, deployment info
- `HISTORY.md` — completed phases and session notes (read-only reference)
- `ARCHITECTURE.md` — system architecture, module ownership, data flow
- `context/DECISIONS.md` — architectural decisions log (why we chose X; append-only, newest first)
