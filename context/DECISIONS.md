# Decisions

Append-only architectural decision log. Dated entries, newest at the top.
Hard cap: 5,000 characters. Trim or summarise the oldest entries when adding
would overflow. Manual + agent-on-request only — the daily / weekly curators
do not touch this file.

Read at session start as part of the tier-0 frozen snapshot.

## 2026-05-25 — No HTTP request tracing (middleware removed)

`ObservabilityMiddleware` opened a DB connection per `/v1/*` request, exhausting the pool (size 3 + overflow 2) when the dashboard made ~10 concurrent calls. Removed permanently. Cron and worker traces via `run_tracked` are sufficient — per-request HTTP traces add noise not signal in a single-user system, and the e2-medium pool cannot support it. Do not re-add HTTP middleware without pool resizing.

## 2026-05-25 — Execution Explorer: success-only sweep (not not-failed)

The retention sweeper uses `status == "success"` (allowlist) rather than `status != "failed"` (blocklist) to select traces eligible for raw payload sweep. This exempts orphaned `"running"` traces (e.g. process-killed jobs) in addition to `"failed"` ones, preserving post-mortem data for any non-terminal trace state.

## 2026-05-25 — Execution Explorer: hybrid schema (typed tables + Event JSONB)

Five typed tables (`traces`, `cron_steps`, `llm_calls`, `tool_calls`, `events`) rather than a single JSONB blob table. Hot-path entities (`Trace`, `LLMCall`) are fully queryable (indexed by started_at, status, trace_id). Cold-path payloads (`raw_request`, `raw_response`, `args`, `result`) are JSONB on the typed rows, swept after TTL. `events` table handles arbitrary untyped side-effects.

## 2026-05-24 — Tool-use loop always uses Sonnet, not user's selected model

Chat tool-use (`run_tool_loop`) hardcodes `claude-sonnet-4-6` regardless of the model the user has selected (Haiku by default). Tool-use requires reliable structured output (JSON `tool_use` blocks) and multi-turn loop coherence. Haiku sometimes produces malformed tool calls under iteration; Sonnet is reliable. The user's model preference governs RAG-only responses; tool-dispatched responses always use Sonnet.

## 2026-05-24 — Hard rules that must survive skill invocations live in CLAUDE.md, not docs/

The `docs/README.md` override clause (spec output → `docs/backlog/`) was ignored by the `writing-plans` skill because `docs/README.md` is only in the tier-0 "also read" list — it isn't in active context when a skill executes. Any rule that must hold during a skill invocation (model selection, file placement, naming) must be a direct section in CLAUDE.md, not a pointer to an external file.

## 2026-05-24 — Domain glossary: lazy population triggered by term resolution

Added `context/GLOSSARY.md` seeded with 5 known-resolved terms. Decided against upfront filling — terms are added only when they resolve in conversation (a name chosen, an ambiguous concept clarified, or a correction made), not in bulk. Instruction in CLAUDE.md triggers the update immediately mid-session, not at session end. Format: canonical term + 1-2 sentence definition + Avoid list of drift-back aliases.

## 2026-05-21 — Morning Pulse: multi-signal briefing over single-winner

Replaced the "pick the highest-urgency signal, render one LLM question" model with "run all detectors, collect all above threshold, assemble a bullet briefing." `select_signals` (plural) returns the full list; `build_briefing` iterates it — template for deadline/named_day/open, LLM only for focus/opportunity/commitment_pace. All new-format pulses store `signal_type="briefing"`. The `open` detector now always fires at urgency 5.0 to guarantee at least one bullet on quiet days. Migration 0022 drops the `notes` column; pulse cron shifted to 04:00 UTC.

## 2026-05-17 — Architecture Decisions Baseline

Key decisions (code is source of truth; see CLAUDE.md footguns for enforcement notes):
- **Sync**: todo/pulse sync best-effort into `memory_items`; training sync bypasses refinement queue (direct RawMemory+MemoryItem, no LLM).
- **Memory expand**: `/v1/memory/{id}/expand` returns full content + raw_text + 3 same-source neighbors.
- **Voice**: deterministic regex classifier; Haiku only invoked after intent is locked; web + iOS share `POST /v1/voice/command`.
- **Commitments**: entries pre-generated upfront; aggregate progress always recomputed from scratch (never incremented); `commitment.status = period ended`, not goal reached; multi-exercise day "hit" = all exercises logged; exercise logs soft-deleted.
- **Strava**: webhook public (handshake-verified, no HMAC); tokens DB-backed with auto-refresh; TSS computed (not from Strava), power-based with HR fallback.
- **Learning**: todos use dedicated FK (`learning_item_id`), not label; data does NOT sync to memory_items; bulk import two-step (dry_run then commit).
- **Claude Code Memory Flywheel**: two-layer markdown (personal `~/.claude/.../memory/` + project `context/`) + SessionEnd auto-capture + tier-0/1/2/3 retrieval contract.
