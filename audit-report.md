# Open Brain — Codebase Audit Report

**Date**: 2026-03-25
**Method**: Two-role (Auditor → Devil's Advocate)
**Scope**: Full codebase — `src/`, `cli/`, `tests/`, `alembic/`, `scripts/`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `README.md`, `DEPLOY.md`, `ARCHITECTURE.md`

---

## Critical Fixes

> High severity, confirmed. Fix before next deployment.

---

**[CRITICAL-1] Dockerfile healthcheck uses `/health` not `/ready`**
File: [`Dockerfile:48`](Dockerfile#L48) vs [`docker-compose.yml:40`](docker-compose.yml#L40)
What: Dockerfile healthcheck hits `/health` (always returns 200, never checks DB). docker-compose correctly overrides to `/ready` (returns 503 when DB is down). But the Dockerfile is the authoritative image definition — anyone running `docker build + docker run` without compose gets a container that permanently reports "healthy" even when the database is unreachable.
Why it matters: Silently masks production failures. Orchestrators (ECS, Kubernetes, Fly.io) rely on HEALTHCHECK — they will not restart a broken container if it claims healthy.
Suggested fix: Change `Dockerfile:48` from `/health` to `/ready`.

---

**[CRITICAL-2] Direct module-level `settings` import in 4 modules — inconsistent with codebase pattern**
Files: [`src/core/database.py:14`](src/core/database.py#L14), [`src/pipeline/entity_resolver.py:7`](src/pipeline/entity_resolver.py#L7), [`src/pipeline/worker.py:24`](src/pipeline/worker.py#L24), [`src/llm/client.py:22`](src/llm/client.py#L22)
What: These modules do `from src.core.config import settings` at the top level, capturing whatever value `settings` has at import time. `config.py` sets `settings = None` on any initialization error. A developer cloning the repo without a `.env` file, then running targeted tests, gets `AttributeError: 'NoneType' object has no attribute '...'` deep inside call stacks rather than a clear "settings not configured" error.
Why it matters: 15+ other modules use a lazy `_get_settings()` helper (auth.py, ranking.py, rate_limit.py, context_builder.py, etc.) specifically to avoid this. These four are the inconsistent exceptions. The `if settings is None` guards in `llm/client.py:257-290` are also misleading — they check the stale None reference, not the live config module value.
Suggested fix: Replace direct import with the lazy helper pattern already used in `auth.py`:
```python
def _get_settings():
    from src.core import config
    if config.settings is None:
        config.settings = config.Settings()
    return config.settings
```
*Devil's Advocate note*: The test suite's autouse conftest fixture re-initializes settings before each test, so tests pass in practice. Risk is real for developers running individual tests without the fixture active, and for any future code path that calls these modules at import time.

---

## Cleanup Backlog

> Confirmed findings, grouped by category. Not blocking, but accumulating technical debt.

---

### Dead Config

**[DC-1] `api_host` and `api_port` defined in Settings, never wired to uvicorn**
File: [`src/core/config.py:18-19`](src/core/config.py#L18)
Severity: medium
What: `api_host: str = "localhost"` and `api_port: int = 8000` are in `Settings` but never accessed via `settings.api_host` / `settings.api_port` anywhere in production code. Uvicorn startup in `docker-compose.yml` hardcodes `--host 0.0.0.0 --port 8000`.
Why it matters: Operators who set `API_HOST=0.0.0.0` in `.env` expecting an effect get silently ignored.
Suggested fix: Either thread them into the uvicorn startup command, or remove the fields.

**[DC-2] `importance_base_default` defined in Settings, extractor ignores it**
File: [`src/core/config.py:40`](src/core/config.py#L40)
Severity: medium
What: `importance_base_default: float = 0.5` exists in Settings. The extractor hardcodes `base_importance=0.5` independently. No code path reads `settings.importance_base_default`.
Why it matters: Implies extraction importance is tunable when it isn't.
Suggested fix: Wire the setting into the extractor, or remove the config field.

**[DC-3] `search_default_limit` defined in Settings, routes use their own defaults**
File: [`src/core/config.py:47`](src/core/config.py#L47)
Severity: medium
What: `search_default_limit: int = 10` exists in Settings. No route or retrieval function reads `settings.search_default_limit`.
Why it matters: Implies search pagination is globally tunable when it isn't.
Suggested fix: Wire into search routes as the default `limit` parameter, or remove.

**[DC-4] `environment` field exists, gates no behavior**
File: [`src/core/config.py:32`](src/core/config.py#L32)
Severity: low
What: `environment: str = "development"` is in Settings. Only appears in `tests/test_config.py:95` to verify the default. No production code path reads it to change any behavior.
Why it matters: Suggests dev/prod branching that doesn't exist.
Suggested fix: Remove, or use it to gate debug-level logging.

**[DC-5] `PULSE_SEND_TIME` in `.env` — no matching field in Settings, no code reads it**
File: `.env` (and `.env.example` if present)
Severity: low
What: `PULSE_SEND_TIME=07:00` is set in `.env` but there is no `pulse_send_time` field in `Settings` and no `os.environ.get("PULSE_SEND_TIME")` anywhere. Pulse timing is driven entirely by the external host cron job.
Why it matters: Dead env var confuses operators who may think the var controls when pulse fires.
Suggested fix: Remove from `.env`.

**[DC-6] Rate limits inconsistent: 3 routes configurable, all others hardcoded**
File: [`src/api/middleware/rate_limit.py:30-78`](src/api/middleware/rate_limit.py#L30)
Severity: low
What: `rate_limit_memory_per_minute`, `rate_limit_search_per_minute`, `rate_limit_dead_letters_per_minute` are tunable via env vars. Entity, todo, task, decision, queue, and pulse route limits are hardcoded strings (e.g., `"60/minute"`) with no config equivalent.
Why it matters: Inconsistent — operators can tune some limits but not others with no documentation of the distinction.
Suggested fix: Add a comment block in `rate_limit.py` marking which limits are fixed vs configurable, or add config fields for the remainder.

**[DC-7] 6 config fields absent from `.env.example`**
File: `.env.example`
Severity: low
What: The following fields are in `config.py` and actively used in code, but not in `.env.example`:
- `DISCORD_TODO_CHANNEL_ID` — used in `discord_bot.py:107-108`
- `PULSE_ACCEPT_FREETEXT` — gates legacy DM fallback in `pulse_cog.py:430`
- `RAG_CONVERSATION_BUFFER_SIZE` — used in `rag_cog.py:301`
- `RAG_CONVERSATION_TTL_HOURS` — used in `rag_cog.py:186`
- `RAG_SAVE_QA_AS_MEMORY` — used in `rag_cog.py:330`
- `RAG_SONNET_MODEL` — used in `rag_cog.py:55`

Why it matters: New deployers don't know these knobs exist.
Suggested fix: Add all six to `.env.example` with explanatory comments.

---

### Dead Code / Fragile Patterns

**[FR-1] Silent `except: pass` in `_fetch_ob_context()` — no log trace**
File: [`cli/ob.py:336-337`](cli/ob.py#L336)
Severity: medium
What: Any exception during context fetch (network failure, API timeout, malformed response) is swallowed with `pass`. The function returns an empty string and the chat continues with no memory context and no indication anything failed.
Why it matters: Users can't distinguish "no relevant memory found" from "API call completely failed." No observability.
Suggested fix: Add `typer.echo(f"[ob] context fetch failed: {e}", err=True)` before `pass`, or use a structlog debug call.

**[FR-2] Silent `except: pass` in `_post_to_ob()` — silent chat ingestion failure**
File: [`cli/ob.py:405-415`](cli/ob.py#L405)
Severity: medium
What: After a chat session, the conversation is POSTed to Open Brain for ingestion. All exceptions are swallowed silently. The docstring acknowledges intentional silence but emits no trace whatsoever.
Why it matters: User believes their chat was saved. It wasn't. No warning, no log. Silent data loss.
Suggested fix: Add at minimum `typer.echo("Warning: failed to save chat to memory", err=True)` on exception.

**[FR-3] `_get_settings()` lazy helper duplicated across 7+ files**
Files: `src/jobs/synthesis.py:48`, `src/jobs/importance.py:42`, `src/integrations/kernel.py:18`, `src/api/middleware/auth.py`, `src/retrieval/ranking.py`, `src/retrieval/context_builder.py`, `src/api/middleware/rate_limit.py`
Severity: low
What: Identical 4-line `_get_settings()` pattern is copy-pasted into each file independently.
Why it matters: If the pattern needs updating (e.g., thread-safety, logging), it must be changed in 7+ places.
Suggested fix: Export a `get_settings()` function from `src/core/config.py` and have all modules import it.

**[FR-4] Backup script URL substitution without validation**
File: [`scripts/backup.sh`](scripts/backup.sh) (~line 38)
Severity: low
What: `PG_URL="${SQLALCHEMY_URL/+asyncpg/}"` strips `+asyncpg` from the SQLAlchemy URL. If the URL format ever changes (e.g., `+psycopg`, `+asyncpg2`), the substitution silently no-ops and `pg_dump` receives the raw SQLAlchemy URL.
Why it matters: Backup fails silently or connects to the wrong target.
Suggested fix: After substitution, validate: `[[ "$PG_URL" == postgresql://* ]] || { echo "ERROR: unexpected URL format" >&2; exit 1; }`

**[FR-5] SSL mode hardcoded in database connect_args**
File: [`src/core/database.py:31`](src/core/database.py#L31)
Severity: medium *(Devil's Advocate addition)*
What: `"ssl": "require"` is hardcoded in the asyncpg connect args. There is no config toggle to run against a local PostgreSQL instance (which doesn't require SSL).
Why it matters: Developers spinning up a local Postgres for integration testing get cryptic SSL handshake errors with no obvious config knob to turn off.
Suggested fix: Add `db_ssl_mode: str = "require"` to Settings and use `settings.db_ssl_mode` here.

---

### Config ↔ Behavior Mismatches

**[MB-1] `Retry-After: "60"` hardcoded regardless of actual rate limit window**
File: [`src/api/middleware/rate_limit.py:26`](src/api/middleware/rate_limit.py#L26)
Severity: low
What: Every 429 response includes `Retry-After: 60` regardless of the endpoint's actual limit. The memory endpoint allows 50 req/minute — the correct retry window is ~1.2 seconds, not 60.
Why it matters: Well-behaved API clients implementing RFC 7231 Retry-After semantics will wait 60× longer than necessary.
Suggested fix: Calculate dynamically, or document as a conservative upper bound.

**[MB-2] Synthesis model defaults to Haiku with no startup warning**
File: [`src/core/config.py:63`](src/core/config.py#L63)
Severity: low
What: `synthesis_model` defaults to `claude-haiku-4-5-20251001`. README recommends switching to `claude-opus-4-6` for production quality. There is no runtime warning when the synthesis job runs with Haiku.
Why it matters: A production deployment using all defaults silently produces low-quality weekly synthesis output.
Suggested fix: Add a `logger.warning("synthesis_model_is_haiku", ...)` at job startup if model contains `"haiku"`.

---

### Docker / Deployment Gaps

**[DK-1] Caddy service missing `env_file` passthrough and healthcheck**
File: [`docker-compose.yml:97-113`](docker-compose.yml#L97)
Severity: low
What: The `caddy` service is defined but: (a) `DOMAIN` env var is not passed from `.env` to the container, so `{$DOMAIN}` in `Caddyfile` resolves to empty string; (b) no healthcheck is defined for the reverse proxy itself.
Why it matters: Caddy fails to start with a cryptic error if `DOMAIN` is missing; no health monitoring for the TLS terminator.
Suggested fix: Add `env_file: .env` to the caddy service; add a healthcheck; document in `DEPLOY.md` that `DOMAIN` is required with `--profile caddy`.

**[DK-2] New routes added without `@limiter.limit()` are unprotected**
File: [`src/api/middleware/rate_limit.py`](src/api/middleware/rate_limit.py) — no global fallback
Severity: low *(Devil's Advocate addition)*
What: Rate limiting requires an explicit `@limiter.limit("X/minute")` decorator per route. There is no global default limiter. A developer adding a new route without the decorator silently bypasses all rate limiting.
Why it matters: Potential DoS vector on new endpoints.
Suggested fix: Add a high-cap global limiter (e.g., `@app.middleware("http")` with a 1000/minute default), or document in `CLAUDE.md` that all routes MUST have explicit `@limiter.limit()`.

---

### Documentation Drift

**[DO-1] Rate limit tunability not documented in README**
File: `README.md`
Severity: low
What: README lists API endpoints and mentions rate limits exist, but doesn't specify which limits are tunable via env vars (`RATE_LIMIT_MEMORY_PER_MINUTE`, etc.) vs which are fixed in code.
Suggested fix: Add a "Rate Limiting" note to README with the three configurable env vars.

---

## Dismissed (False Positives)

| Finding | Reason |
|---------|--------|
| `pyproject.toml:74` entry point `cli.ob:main` | `def main()` exists at `cli/ob.py:509`. Entry point is correct. |
| Direct `settings` import causing test failures | autouse `conftest.py` fixture re-initializes settings before each test; tests pass. Risk is medium for new devs, not a current bug. |
| `_create_anthropic_client()` / `_create_voyage_client()` `if settings is None` guards | The guards run at call time, not import time. If production startup succeeds (settings non-None), these functions work correctly. Only problematic if settings=None persists, which is covered by CRITICAL-2. |
| `getattr(settings, ...)` in Discord cogs silently swallowing field typos | Low risk: all field names match config.py exactly in current code. Flagged for awareness only. |
| Cron jobs not auto-scheduled in docker-compose | By design. Pulse, importance, and synthesis jobs are one-shot entry points meant for host cron. Not a gap. |

---

## Recommendations

> Patterns to adopt to prevent recurrence.

**R-1: Export `get_settings()` from `src/core/config.py`**
Eliminate the copy-pasted lazy helper. One import, one implementation:
```python
# src/core/config.py (add at bottom)
def get_settings() -> Settings:
    global settings
    if settings is None:
        settings = Settings()
    return settings
```
All modules: `from src.core.config import get_settings` instead of inlining.

**R-2: Add a pre-commit hook banning direct module-level `settings` import**
```bash
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: no-direct-settings-import
      name: Warn on direct settings import
      entry: bash -c 'grep -rn "^from src.core.config import settings" src/ && exit 1 || exit 0'
      language: system
      pass_filenames: false
```

**R-3: Add a CI check diffing `config.py` fields against `.env.example`**
A simple script that extracts all field names from `Settings` and verifies each has a corresponding entry in `.env.example`. Prevents the 6-field gap from happening again.

**R-4: Document in `CLAUDE.md` that all new FastAPI routes MUST have `@limiter.limit()`**
Add to the "Common Pitfalls" section:
> ❌ **Don't**: Add a new route without `@limiter.limit("X/minute")`
> ✅ **Do**: Every route in `src/api/routes/` must have an explicit rate limit decorator

---

## Finding Summary

| ID | Category | Severity | Status |
|----|----------|----------|--------|
| CRITICAL-1 | Docker/Config Mismatch | high | Confirmed |
| CRITICAL-2 | Dead Code / Fragile | high | Confirmed |
| DC-1 | Dead Config | medium | Confirmed |
| DC-2 | Dead Config | medium | Confirmed |
| DC-3 | Dead Config | medium | Confirmed |
| DC-4 | Dead Config | low | Confirmed |
| DC-5 | Dead Config | low | Confirmed |
| DC-6 | Dead Config | low | Confirmed |
| DC-7 | Dead Config | low | Confirmed |
| FR-1 | Fragile Pattern | medium | Confirmed |
| FR-2 | Fragile Pattern | medium | Confirmed |
| FR-3 | Naming / Consistency | low | Confirmed |
| FR-4 | Fragile Pattern | low | Confirmed |
| FR-5 | Fragile Pattern | medium | Confirmed (missed by Auditor) |
| MB-1 | Config↔Behavior | low | Confirmed |
| MB-2 | Config↔Behavior | low | Confirmed |
| DK-1 | Docker / Deployment | low | Confirmed |
| DK-2 | Fragile Pattern | low | Confirmed (missed by Auditor) |
| DO-1 | Documentation Drift | low | Confirmed |
