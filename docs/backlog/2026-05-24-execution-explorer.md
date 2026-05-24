---
status: in-progress
created: 2026-05-24
---

# Execution Explorer — Foundational Observability

## Context

The current `/logs` page is a quick-build tester, not foundation. Three concrete gaps it can't be patched into solving:

1. **No execution detail.** `JobRun` records one row per cron tick. No way to see *what* the job did — which LLM calls, which prompts, which tools, which DB writes.
2. **No cost or token visibility, anywhere.** `response.usage` from Anthropic is discarded in all 3 methods of `src/llm/client.py`. ~10 LLM call sites; zero record of what was spent, what got cached, or which model ran.
3. **Retry semantics are tangled and partial.** The `/logs` "retry" button only re-enqueues `RefinementQueue` rows. Failed `JobRun` rows have no retry path. `chat_logs` table (migration 0023) stores tool/LLM calls as JSONB blobs that can't be queried for cost or filtered for failures.

The aim: a foundational **Execution Explorer** that models executions (not outcomes), gives hierarchical visibility from trigger → LLM call → tool call → DB action, surfaces cost per call, and supports rerun of full traces or replay of failed spans. Multi-session implementation; V1 is the smallest cut that doesn't lie by omission.

---

## Decisions Locked (2026-05-24)

| # | Decision | Choice |
|---|---|---|
| 1 | Data model shape | **Hybrid:** typed tables for hot entities (`Trace`, `LLMCall`, `CronStep`, `ToolCall`) + generic `Event` JSONB for arbitrary/raw payloads. All linked by `trace_id` + `span_id` + `parent_span_id`. |
| 2 | Trace boundaries | **Trigger-rooted with `causal_parent_trace_id`** across async handoffs. Each external trigger = new trace. Worker handoffs across `RefinementQueue` start a new trace with a causal link. |
| 3 | Replay/rerun | **Trace-level rerun (ii) + dead-letter span replay (iii)**. No span-level edit-and-replay (iv). |
| 4 | Retention | **Postgres + sweeper, 90d default for raw payloads.** Summary spans kept indefinitely. Failed traces exempt from sweep. |
| 5 | Cost tracking | **At-write computation** from hardcoded `src/llm/pricing.py` dict. Store full Anthropic usage breakdown + `pricing_version` + `cost_usd` per `LLMCall`. |
| 6a | UI layout | **Unified trace stream (α)** — single chronological trace list with filters, click-through to split-pane span tree + detail. |
| 6b | Updates | **Polling + manual refresh** with optional 5s/30s/off auto-refresh toggle. No SSE in V1. |
| 6c | V1 scope | **Full V1 as proposed** (all 10 items below). |
| 6d | Backfill | **No backfill, start fresh.** Old `/logs` becomes a read-only "legacy" tab for one release cycle, then dropped. |

---

## Architecture

### Trace model

```
Trace                          (root: trigger metadata, top-level cost rollup, status)
 ├── CronStep / ChatTurn / ApiRequest  (mid-tier spans, type-specific)
 │    ├── LLMCall              (typed: model, tokens, cost, raw payloads)
 │    │    └── (loop continues with more LLMCalls if it's a tool loop)
 │    ├── ToolCall             (typed: tool_name, args, result, duration)
 │    │    └── Event (DB)      (untyped JSONB for arbitrary side-effects)
 │    └── Event                (untyped: anything else worth recording)
 └── (more siblings)
```

- **Hot path** (queryable, indexed): `Trace`, `LLMCall`, `CronStep`, `ToolCall`
- **Cold path** (lazy-loaded JSONB): `raw_request` / `raw_response` on `LLMCall`, `args`/`result` on `ToolCall`, `payload` on `Event`

### Schema

#### `traces`
```
id UUID PK, trigger_type TEXT, trigger_name TEXT, trigger_metadata JSONB,
status TEXT, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, duration_ms INT,
total_cost_usd NUMERIC(10,6), total_input_tokens INT, total_output_tokens INT,
total_cache_read_tokens INT, total_cache_creation_tokens INT,
llm_call_count INT, tool_call_count INT, error_message TEXT, error_class TEXT,
causal_parent_trace_id UUID REFERENCES traces(id),
rerun_of_trace_id UUID REFERENCES traces(id),
cost_alert_threshold_usd NUMERIC(10,6), created_at, updated_at
```
Indexes: `(started_at DESC)`, `(trigger_type, started_at DESC)`, `(status, started_at DESC)`, `(causal_parent_trace_id)`, `(rerun_of_trace_id)`.

#### `cron_steps`
```
id UUID PK, trace_id UUID FK→traces, span_id TEXT, parent_span_id TEXT,
step_name TEXT, status TEXT, started_at, finished_at, duration_ms,
error_message, error_class, metadata JSONB
```

#### `llm_calls`
```
id UUID PK, trace_id UUID FK→traces, span_id TEXT, parent_span_id TEXT,
call_site TEXT, model TEXT, provider TEXT DEFAULT 'anthropic', status TEXT,
started_at, finished_at, duration_ms,
input_tokens INT, output_tokens INT, cache_read_input_tokens INT, cache_creation_input_tokens INT,
stop_reason TEXT, cost_usd NUMERIC(10,6) DEFAULT 0, pricing_version TEXT,
raw_request JSONB, raw_response JSONB,
request_summary JSONB NOT NULL, response_summary JSONB,
error_message TEXT, error_class TEXT, created_at
```

#### `tool_calls`
```
id UUID PK, trace_id UUID FK→traces, span_id TEXT, parent_span_id TEXT,
tool_name TEXT, status TEXT, started_at, finished_at, duration_ms,
args JSONB NOT NULL, result JSONB, is_error BOOLEAN DEFAULT FALSE,
error_message TEXT, created_at
```

#### `events`
```
id UUID PK, trace_id UUID FK→traces, span_id TEXT, parent_span_id TEXT,
event_type TEXT, level TEXT DEFAULT 'info', payload JSONB, occurred_at TIMESTAMPTZ DEFAULT now()
```

RLS deny-all on all 5 tables (per migration 0009/0010 pattern).

### Instrumentation points (4 files cover all ~10 LLM call sites)

1. **`src/llm/client.py`** — wraps all 3 methods; one change covers all downstream call sites
2. **`src/jobs/runner.py`** — `run_tracked` opens Trace with `trigger_type='cron'`
3. **`src/llm/tool_agent.py`** — `run_tool_loop` emits proper spans instead of `chat_logs` blobs
4. **`src/pipeline/worker.py`** — picks up `causal_parent_trace_id` from `RefinementQueue.trace_id`
5. **`src/api/middleware/observability.py`** (new) — catch-all for `/v1/*` HTTP traces

### Cost tracking

`src/llm/pricing.py` — hardcoded dict, computed at write time, `pricing_version` stored per row.

### Retention sweeper

Daily cron at `0 4 * * *` — nulls `raw_request`/`raw_response` on successful traces older than `OB_OBSERVABILITY_RAW_TTL_DAYS` (default 90). Failed traces exempt.

### Replay model

- **Trace-level rerun:** `POST /v1/traces/{id}/rerun` — new trace with `rerun_of_trace_id` set. Per-trigger handlers in `src/observability/rerun.py`.
- **Dead-letter span replay:** `POST /v1/spans/{table}/{id}/replay` — re-executes one failed `llm_call`/`tool_call` span from stored `raw_request`. New sibling span in same trace.

### UI

Route stays `/logs`, renames to "Execution Explorer." Old UI → `/logs/legacy` for one release cycle.

- **Top bar:** today's cost (7-day sparkline), 24h cache-hit-rate, 24h failure count, oldest dead-letter
- **Trace list:** chronological, paginated. Filters: trigger_type, status, date range, cost range, model, trigger_name. Auto-refresh off/5s/30s toggle.
- **Trace detail — split pane:** 40% span tree (indented, collapsible) + 60% detail (tabs: Summary / Inputs / Output / Raw / Children). Header: Rerun (always) + Replay (failed llm_call/tool_call spans only).

---

## V1 Scope

All 10 required for the system to be honest end-to-end:

1. Alembic migration `0024` — 5 tables + `refinement_queue.trace_id` + RLS
2. `src/observability/` module — context managers, recording API, structlog.contextvars propagation
3. `structlog.configure()` at boot — JSON prod, key-value dev, contextvars processor
4. Instrument `src/llm/client.py` — 3 methods, capture `response.usage`, compute cost
5. `src/llm/pricing.py` — pricing dict + `compute_cost_usd()`
6. Instrument `src/jobs/runner.py` — `run_tracked` opens Trace; keep `JobRun` dual-write
7. Instrument `src/llm/tool_agent.py` — proper spans instead of `chat_logs` blobs; keep dual-write
8. Instrument `src/pipeline/worker.py` — pick up `causal_parent_trace_id`; update `ingest_memory` to write `trace_id`
9. API routes `src/api/routes/observability.py` — 5 routes with `@limiter.limit()`
10. Web Execution Explorer page — trace list, split-pane detail, rerun + replay buttons

**Also in V1:** retention sweeper, `OB_OBSERVABILITY_RAW_TTL_DAYS` env var, docs updates.

**Out of V1:** SSE, per-trigger TTLs, span-level edit-replay, budget alerting, backfill, OpenTelemetry.

---

## V2 Scope (next session after V1)

- Cost trends dashboard (per-day, per-trigger-type, per-model), cache-hit-rate panel
- Free-text search over raw payloads
- Drop `JobRun` + `chat_logs` tables; remove "Legacy" tab
- Backfill best-effort: map historical `JobRun` rows into shallow `traces`
- Fix `_OVERDUE_THRESHOLDS` in `src/api/routes/jobs.py:45-49` (misses learning_daily, commitment_miss, training_weekly)

---

## Critical Files

**Create:**
- `alembic/versions/0024_execution_explorer.py`
- `src/observability/__init__.py`, `context.py`, `recording.py`, `rerun.py`
- `src/llm/pricing.py`
- `src/jobs/observability_sweep.py`
- `src/api/routes/observability.py`
- `src/api/middleware/observability.py`
- `web/app/logs/page.tsx` (rewrite; current → `web/app/logs/legacy/page.tsx`)
- `web/components/observability/trace-list.tsx`, `trace-detail.tsx`, `span-tree.tsx`, `kpi-tiles.tsx`
- `web/hooks/use-traces.ts`, `use-trace-detail.ts`

**Modify:**
- `src/core/models.py` — 5 new models with `.with_variant()` for SQLite compat
- `src/llm/client.py` — wrap 3 methods
- `src/jobs/runner.py` — open Trace in `run_tracked`
- `src/llm/tool_agent.py` — proper span emission
- `src/pipeline/worker.py` — causal_parent_trace_id
- `src/api/services/memory_service.py::ingest_memory` — write `trace_id` to queue
- `src/core/config.py` — `observability_raw_ttl_days`
- `crontab` — add sweeper at `0 4 * * *`
- `.env.example` — `OB_OBSERVABILITY_RAW_TTL_DAYS=90`
- `ARCHITECTURE.md`, `PROGRESS.md`, `context/DECISIONS.md`

**Patterns to reuse:**
- `JobRun` lifecycle in `src/jobs/runner.py`
- Alembic RLS deny-all from `0009`/`0010`
- `@limiter.limit()` on every `/v1/*` route
- `web/hooks/use-job-history.ts` shape → starting template for `use-traces.ts`
- `_get_settings()` lazy helper for env access

---

## Plan

### Session structure (5 sessions)

After each session: run `/endsession`, commit, open fresh session. Resume prompt:
> Continue Execution Explorer V1 — Phase N. Read `docs/backlog/2026-05-24-execution-explorer.md`. Check `context/STATE.md` for current progress. Pick up at Phase N.

### Phase 1 — Foundation (Schema + Recording API) — Session 1

Sequential (each step depends on previous):

1. Migration `0024_execution_explorer.py` — 5 tables, RLS, `refinement_queue.trace_id`
2. ORM models in `src/core/models.py` — `Trace`, `CronStep`, `LLMCall`, `ToolCall`, `Event`
3. `src/llm/pricing.py` — pricing dict + `compute_cost_usd(model, usage)`
4. `src/observability/` module — `context.py` + `recording.py` + `__init__.py`
5. Wire `structlog.configure()` at boot
6. `src/observability/rerun.py` — registry skeleton
7. Unit tests for all of the above

**Gate:** `make lint && make test` green. Migration applies clean on SQLite.

🛑 SESSION STOP — end after Phase 1

### Phase 2 — Instrumentation (5 callsites) — Session 2

5 parallel subagents (dispatching-parallel-agents):

- A: `src/llm/client.py` — 3 methods, usage capture, cost, raw payloads, summaries
- B: `src/jobs/runner.py` — Trace per cron run, `start_step()` per phase, cron rerun handler
- C: `src/llm/tool_agent.py` — `tool_calls` rows, dual-write `chat_logs`, chat rerun handler
- D: `src/pipeline/worker.py` + `memory_service.py::ingest_memory` — causal trace link
- E: `src/api/middleware/observability.py` — HTTP catch-all trace

**Gate:** `make lint && make test` green. Manual smoke: synthesis job produces `traces`+`llm_calls` rows, cost non-zero, `JobRun` still written.

🛑 SESSION STOP — end after Phase 2 (may split mid-phase if context gets tight)

### Phase 3 — API Routes — Session 3

Sequential:
1. `src/api/routes/observability.py` — 5 routes, all with `@limiter.limit()`
2. Register router in app
3. Tests in `tests/api/test_observability.py`

**Gate:** Routes return correct shapes. Rerun + replay verified with test fixtures.

🛑 SESSION STOP — end after Phase 3

### Phase 4 — Web (Execution Explorer) — Session 4

1. Move `/logs` → `/logs/legacy`
2. `use-traces.ts`, `use-trace-detail.ts` hooks
3. `kpi-tiles.tsx`, `trace-list.tsx`, `span-tree.tsx`, `trace-detail.tsx` components
4. New `web/app/logs/page.tsx`
5. Vitest tests + 1 E2E

**Gate:** Page renders against real backend. Smoke flows pass.

🛑 SESSION STOP — end after Phase 4

### Phase 5 — Operations + Docs — Session 5

1. `src/jobs/observability_sweep.py` + crontab entry
2. Config + `.env.example`
3. Docs: `ARCHITECTURE.md`, `PROGRESS.md`, `context/DECISIONS.md`, `context/STATE.md`
4. Full 10-step verification plan

**Gate (V1 complete):** All 10 verification checks pass.

🛑 SESSION STOP — V1 SHIPPED. Move this file to `docs/archive/`.

---

## Verification Plan

1. Migration applies on Postgres (SQLite already covered by test suite)
2. Cron run → `traces` row + child spans + non-zero cost; `JobRun` still present
3. Chat with tools → `tool_calls` row with correct `parent_span_id`
4. Voice ingest → refinement worker = two linked traces via `causal_parent_trace_id`
5. Rerun button → new trace with `rerun_of_trace_id` set
6. Span replay → sibling span appears with success; original `raw_request` re-sent
7. Cost vs Anthropic dashboard: within 5% over a day's traffic
8. Sweeper purges `raw_request` on success traces, exempts failed traces
9. Rate limits → 429 past limit
10. `make lint && make test` green; new tests cover span lifecycle, cost, causal propagation, rerun dispatch, sweeper exemptions, RLS

---

## Progress

### Session 1 — Phase 1 (completed 2026-05-24)

- [x] Promote to backlog
- [x] Migration 0024 (`alembic/versions/0024_execution_explorer.py`) — 5 tables + RLS + `refinement_queue.trace_id`
- [x] ORM models (`Trace`, `CronStep`, `LLMCall`, `ToolCall`, `ObsEvent`) + `RefinementQueue.trace_id`
- [x] `src/llm/pricing.py` — cost computation, PRICING_VERSION 2026-05
- [x] `src/observability/` module (context.py, recording.py, __init__.py)
- [x] `structlog.configure()` in `src/core/logging.py`, wired in `main.py` and `runner.py`
- [x] `src/observability/rerun.py` — registry skeleton
- [x] Unit tests (`tests/test_observability.py`) — 16 tests, 5 pricing + 11 observability
- [x] Gate: 971 passed, 0 failed. No new lint errors introduced.

Notes:
- `CronStep.metadata` renamed to `step_metadata` (SQLAlchemy reserves `metadata` attribute)
- `observability_raw_ttl_days` added to `INTENTIONAL_UNUSED` in `check_config.py` (sweeper created in Phase 5)
- Observability uses its own dedicated session (independent commit from business logic — failure traces persist even when caller rolls back)
