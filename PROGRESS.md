# Open Brain — Progress

**Status**: All phases + dashboard + training/commitments + Strava live + Learning Library V1 + commitment completion bugfix + bulk todo defer + signal-driven pulse Phase 1 + scheduler boot sweep + todo redesign (focus card + project groups) + UI polish sprint + Learning V2 fully shipped (backend + frontend) + Learning UI redesign (2026-05-02) + multi-exercise commitments (routine + plan kinds, 2026-05-04) + Commitments first-class tab (2026-05-05) + commitment plan import with per-exercise sets (2026-05-07) + Discord integration fully removed (2026-05-16) + Learning cron cross-day dedup + topic context on todo responses (2026-05-17) + **Claude Code Memory Flywheel V1 (SessionEnd hook + SessionStart catch-up + memory_expand MCP tool + tier-0/1/2/3 retrieval contract + local memory cron, 2026-05-17)** + **nav scroll-hide + memory card badge polish (2026-05-18)** + **Exercise Library + Per-Day Schedule + Import Wizard + Plan CRUD (Spec B, 2026-05-19)** + **Inline exercise log form with metric-matched fields + last_logged summary (Spec A, 2026-05-19)** + **Morning Pulse Briefing Redesign: multi-signal bullet briefing, 3 new detectors, migration 0022, cron -1h (2026-05-21)** + **Chat Tools Library: hybrid intent classifier + tool-use loop + 7 domain tools (search_memory_filtered, expand_memory, list_todos, create_todo, complete_todo, defer_todo, edit_todo) + ChatLog model/migration 0023 + ToolsToggle UI (PR1+PR2+PR3, 2026-05-24)** + **Execution Explorer V1: 5-table observability schema (traces/llm_calls/tool_calls/cron_steps/events), cost tracking, recording API, 5 API routes, retention sweeper, full web UI (trace list, span tree, KPI tiles, rerun/replay), 1007 backend + 330 frontend tests (2026-05-25)** — 955 backend tests, 315 Vitest tests
**Project**: 2026-03-13 → 2026-04-30 | See [HISTORY.md](HISTORY.md) for completed phases and session notes

---

## Deployment (LIVE since 2026-03-16)

**Server**: GCP e2-medium, Ubuntu 24.04, `34.118.15.81` (static IP: `open-brain-ip`)
**Domain**: `0xpai.com` (DNS at Spaceship, A record → `34.118.15.81`)
**MCP**: `.mcp.json` → `https://0xpai.com` (routes through Caddy; port 8000 is localhost-only)
**Database**: Supabase (session-mode pooler, port 5432) — migrations at head (0015 — todo project field + project_labels Personal seed, deployed 2026-04-30); 0016 (learning_materials) + 0017 (multi-exercise commitments) + 0018 (commitment_exercises.sets + widened unique constraint) + **0019 (drop rag_conversations table + discord_message_id/discord_channel_id columns from todo_items/daily_pulse)** + **0020 (exercise library table + exercises FK on commitment_exercises) + 0021 (commitment_entry_exercises junction table)** + **0022 (drop notes column from daily_pulse)** + **0023 (chat_logs table + RLS)** + **0024 (execution_explorer: traces, cron_steps, llm_calls, tool_calls, events + refinement_queue.trace_id)** pending deploy
**Services**: API + Worker + Web + Caddy (Docker Compose) — Discord bot removed

**Strava**: Webhook subscription active (ID: 340388), callback `https://0xpai.com/v1/strava/webhook`, auto-refresh tokens in `strava_tokens` table, FTP=190w, MAX_HR=195, RESTING_HR=57 (HR-based TSS fallback enabled)

**Cron jobs (VM, supercronic via `crontab`)**:
- `importance` — 01:00 UTC daily
- `synthesis` — 00:00 UTC Sunday
- `backup` — 03:30 AM daily
- `pulse` — **04:00 UTC** daily (shifted -1h 2026-05-21; signal-driven Phase 2 — multi-signal bullet briefing)
- `commitment_miss` — 00:30 UTC daily + once on scheduler container boot (`docker-compose.yml` command wrapper)
- `training_weekly` — 01:00 UTC Monday
- `learning_daily` — 04:30 UTC daily (runs before pulse)
- `observability_sweep` — 04:00 UTC daily (sweeps raw LLM payloads >90d on successful traces)

**Memory flywheel cron (WSL2 local, per-machine via `make memory-install-cron`)**:
- `daily-memory-distill` — 23:00 local daily + anacron catch-up on next boot (`scripts/memory/run-distill.sh`, `cron/jobs/daily-memory-distill.md`); sentinel-anchored window (`context/.last-distill`) so missed days are processed oldest→newest on next run
- `weekly-memory-curator` — Sunday 09:00 local + anacron weekly catch-up (`scripts/memory/run-curate.sh`, `cron/jobs/weekly-memory-curator.md`); stateless, prunes `~/.claude/projects/.../memory/*.md` to per-file caps
- SessionStart hook fires daily distill opportunistically in-session (`scripts/claude-code/session-start-distill.sh`), throttled to once per `OB_SESSION_START_MIN_HOURS` (default 6h)

---

## Open Tech Debt

- **L3**: Hardcoded LIMIT 100 in search CTEs (`src/retrieval/search.py`). Revisit at 10k+ memories.
- **L4**: `merge_entities()` is 162 lines (`src/api/routes/entities.py`). Revisit if >200 lines.
- **S1**: Narrow `--forwarded-allow-ips=172.0.0.0/8` to exact Docker subnet after verifying Caddy setup.
- **V1**: Voice-command classifier regex is hand-tuned to real Siri phrasings seen in prod.
- **M1**: `sync_todo_to_memory()` flips `is_superseded=True` but does NOT set `supersedes_memory_id` pointer.
- **T3**: `hybrid_search()` tag filtering (tags @> query) not yet wired — column and GIN index exist but no API surface.
- **T4**: Settings form only supports single-metric aggregate commitments; backend supports multi-metric via JSONB `targets`.
- **T5**: ~~completed-but-not-reached aggregates only visible on settings~~ — **resolved**: now visible in Commitments tab History view (`web/app/commitments/page.tsx`).
- **C1**: ~~No link from dashboard card to detail page~~ — **resolved**: Commitments tab cards have overlay nav links to `/commitments/[id]` (`web/app/commitments/page.tsx`). Dashboard cards still have no direct link — address separately if needed (`web/components/dashboard/commitment-list.tsx`).
- **C2**: ~~Exercise logging from dashboard is a simple "Done" tap (empty body `{}`)~~ — **resolved 2026-05-19**: inline expand form on `ExerciseRow` collects reps/sets/weight/duration; backend surfaces `last_logged` on exercise responses for prefill + summary display (`web/components/dashboard/commitment-list.tsx`, `src/api/routes/commitments.py`).
- **C3**: `import_hash` has an index but no `UNIQUE` constraint — concurrent identical imports could create duplicates in theory. Acceptable for single-user; add constraint if multi-user.
- **L5**: Learning cron uses two-commit pattern in `_create_learning_todo` (`src/jobs/learning_daily.py`) — todo created then FK set. Non-atomic but low-probability; worst case one extra todo on next run. Consolidate into one transaction if this ever manifests.
- **L6**: Web sidebar `/learning` link is hardcoded, not gated by `/v1/modules`. When `module_learning_enabled=False` clicking shows 404 gracefully. Acceptable for single-user; fix if multi-user.
- **L7**: `/v1/learning/*` routes return `dict[str, Any]` rather than Pydantic response models. Matches modules endpoint style; tighten to models if stricter OpenAPI spec is needed.
- **P1**: ~~Pulse `_fetch_yesterday_pulse` only looks back exactly 1 day~~ — less relevant now; briefing is template-driven and doesn't rely on yesterday's alternation hint. Revisit if yesterday context is ever re-added to a detector.
- **P3**: Commitment pace detector returns only the first off-pace commitment; if multiple aggregate commitments are behind simultaneously, only one fires per morning (`src/pulse_signals/detectors/commitment_pace.py`). Acceptable for single-user; revisit if multi-commitment households arise.
- **MF1**: Personal memory layer at `~/.claude/projects/-home-shu-projects-open-brain/memory/` is severely over caps as of 2026-05-17 (`learning.md` 1637%, `project_sequence.md` 296%, `project_web_dashboard.md` 230%, `feedback_multi_agent_workflow.md` 112%) per `make memory-state`. First real `make memory-curate` run should consolidate. Inspect before deploying any auto-prune logic.
- **MF2**: `OB_SESSION_END_BACKEND` and `OB_SESSION_START_MIN_HOURS` need to be documented in `.env.example` (currently only in `docs/setup-manuals/setup-new-machine.md`). Add when next touching env config (`src/core/config.py`, `.env.example`).

---

## Context Files

- `context/GLOSSARY.md` — canonical domain terms, lazy-populated mid-session when terms resolve
- `context/SERVICES.md` — external API calls map (Anthropic, Voyage, Strava, Google Calendar, Supabase); update when adding integrations

## Next Up

- **Deploy Execution Explorer V1**: apply migration 0024 on Supabase; restart API+worker to activate observability instrumentation and sweeper
- **Deploy** all pending changes (migrations 0016–0023 + Learning V2 + Commitments tab + plan import sets + Discord removal + Learning cron cross-day dedup + topic context on TodoResponse + **memory_expand endpoint + `claude-code-session` source in `AUTO_CAPTURE_SOURCES`** + **exercise library + per-day schedule + import wizard + plan CRUD** + **inline log form + last_logged on ExerciseResponse** + **Morning Pulse Briefing: 3 new detectors, build_briefing, migration 0022 drop notes, cron 04:00 UTC** + **Chat Tools Library: intent classifier, tool-use loop, 7 domain tools, ChatLog migration 0023, ToolsToggle UI** — `src/llm/intent_classifier.py`, `src/llm/tool_agent.py`, `src/api/services/chat_tools.py`, `src/api/services/memory_tools.py`, `src/api/services/todo_tools.py`, `src/api/routes/chat.py`, `web/components/chat/tools-toggle.tsx`, `web/hooks/use-chat.ts`, `alembic/versions/0023_chat_logs.py`) — `git pull` on GCP VM then `docker compose --profile migrate run --rm migrate` + restart services; remove `discord-bot` container if running (`docker rm -f openbrain-discord`)
- **Chat tools v2**: add memory-write tools (`defer_memory`, `adjust_importance`, `supersede_memory`) and pulse tools; add `GET /v1/chat/logs` route + frontend log page (`src/api/routes/chat.py`, `src/api/services/chat_tools.py`)
- **Verify chat tools UI**: at `0xpai.com/chat` — enable Tools toggle → send "show my todos" → tool-driven response; disable → RAG path; reload → toggle persists (`web/app/chat/page.tsx`, `web/hooks/use-chat.ts`)
- **Install memory flywheel locally (this machine)**: symlink both hooks into `~/.claude/hooks/`, add `OB_SESSION_END_BACKEND=cli` + `OPENBRAIN_*` to `~/.claude/openbrain.env`, add SessionStart + SessionEnd entries to `~/.claude/settings.json`, run `make memory-install-cron` (sudo), add `[boot] command = "service cron start"` to `/etc/wsl.conf` then `wsl --shutdown`. Verify via `make memory-state` + tail `/tmp/ob-session-*.log` on next CC session — see `docs/setup-manuals/setup-new-machine.md` (`scripts/claude-code/`, `scripts/memory/`)
- **First weekly curator run** to consolidate over-cap personal layer files (MF1) — `make memory-curate`, review diff before next run
- **Import first real plan** via the new 3-step wizard at `/commitments/import`; verify unknown exercises resolve correctly and entry_exercises rows are created
- **Visual verification of plan CRUD editor** at `/commitments/[id]/edit`: day-swap, exercise picker, week grouping — test on mobile viewport
- **Visual verification of Spec A inline log form** at `/` dashboard: tap Log on a routine exercise → expand form, fields match metric/progression_metric, prefilled from last_logged or target; after Confirm → check + summary shown (`web/components/dashboard/commitment-list.tsx`)
- **Day-swap UI from commitment detail page** (Spec A second half — not yet implemented; rest-day → workout-day swap on `/commitments/[id]` page)
- **Visual verification** of scroll-hide nav: scroll down on mobile viewport → top nav + bottom tabs should slide away; scroll up → both reappear with 300ms transition (`web/components/layout/top-nav.tsx`, `web/components/layout/bottom-tabs.tsx`)
- **Visual verification** of Commitments tab: active list cards + overlay links, collapsible form, history section with badges, sidebar + mobile bottom-tabs — desktop + iPhone 14 Pro DevTools (393×852)
- **Visual verification** of Learning redesign: stat cards, progress ring, filter pills, collapsible topic cards, Switch toggles, delete buttons
- **Write tests** for Learning components: `progress-ring.test.tsx`, `switch.test.tsx`, `learning-item-row.test.tsx`, `learning-topic-card.test.tsx`, `learning-page.test.tsx` (`web/__tests__/`)
- Seed first learning topics + sections + items via `/learning/import` using `docs/learning-import-template.md` + Claude.ai
- Verify pulse signal pipeline telemetry; address P1+P2 if always `open` (`src/pulse_signals/context.py`, `src/pulse_signals/prompts.py`, `src/pulse_signals/detectors/open.py`)
- Multi-metric aggregate form support in Commitments tab (`web/components/commitments/commitment-create-form.tsx`)
- Dashboard commitment cards currently have no detail link — consider adding "View" chevron to `MultiExerciseCommitmentCard` (`web/components/dashboard/commitment-list.tsx`)
