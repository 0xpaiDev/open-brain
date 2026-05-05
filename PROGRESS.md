# Open Brain — Progress

**Status**: All phases + dashboard + training/commitments + Strava live + Learning Library V1 + commitment completion bugfix + bulk todo defer + signal-driven pulse Phase 1 + scheduler boot sweep + todo redesign (focus card + project groups) + UI polish sprint + Learning V2 fully shipped (backend + frontend) + Learning UI redesign (2026-05-02) + **multi-exercise commitments (routine + plan kinds, 2026-05-04)** — ~1347 tests (1069 backend + 278 Vitest)
**Project**: 2026-03-13 → 2026-04-30 | See [HISTORY.md](HISTORY.md) for completed phases and session notes

---

## Deployment (LIVE since 2026-03-16)

**Server**: GCP e2-medium, Ubuntu 24.04, `34.118.15.81` (static IP: `open-brain-ip`)
**Domain**: `0xpai.com` (DNS at Spaceship, A record → `34.118.15.81`)
**MCP**: `.mcp.json` → `https://0xpai.com` (routes through Caddy; port 8000 is localhost-only)
**Database**: Supabase (session-mode pooler, port 5432) — migrations at head (0015 — todo project field + project_labels Personal seed, deployed 2026-04-30); 0016 (learning_materials) + **0017 (multi-exercise commitments)** pending deploy
**Services**: API + Worker + Discord bot + Web + Caddy (Docker Compose)

**Strava**: Webhook subscription active (ID: 340388), callback `https://0xpai.com/v1/strava/webhook`, auto-refresh tokens in `strava_tokens` table, FTP=190w, MAX_HR=195, RESTING_HR=57 (HR-based TSS fallback enabled)

**Cron jobs**:
- `importance` — 01:00 UTC daily
- `synthesis` — 00:00 UTC Sunday
- `backup` — 03:30 AM daily
- `pulse` — 05:00 UTC daily (signal-driven Phase 1 active; first signal-pipeline run = 2026-04-26 05:00 UTC)
- `commitment_miss` — 00:30 UTC daily + once on scheduler container boot (`docker-compose.yml` command wrapper)
- `training_weekly` — 01:00 UTC Monday
- `learning_daily` — 04:30 UTC daily (runs before pulse)

---

## Open Tech Debt

- **L3**: Hardcoded LIMIT 100 in search CTEs (`src/retrieval/search.py`). Revisit at 10k+ memories.
- **L4**: `merge_entities()` is 162 lines (`src/api/routes/entities.py`). Revisit if >200 lines.
- **S1**: Narrow `--forwarded-allow-ips=172.0.0.0/8` to exact Docker subnet after verifying Caddy setup.
- **V1**: Voice-command classifier regex is hand-tuned to real Siri phrasings seen in prod.
- **M1**: `sync_todo_to_memory()` flips `is_superseded=True` but does NOT set `supersedes_memory_id` pointer.
- **T3**: `hybrid_search()` tag filtering (tags @> query) not yet wired — column and GIN index exist but no API surface.
- **T4**: Settings form only supports single-metric aggregate commitments; backend supports multi-metric via JSONB `targets`.
- **T5**: `/v1/commitments` list default filter is `status=active`; completed-but-not-reached aggregates only visible on settings (`status=all`). If dashboard should surface "not reached" tombstones, add a separate "recent" section rather than widening the active filter (`web/app/dashboard/page.tsx`, `web/components/dashboard/commitment-list.tsx`).
- **C1**: Multi-exercise commitment detail page (`web/app/commitments/[id]/page.tsx`) requires navigating to `/commitments/{id}` — there is no link from the dashboard card yet. Add a card header link or "View progression" button in `MultiExerciseCommitmentCard`.
- **C2**: Exercise logging from dashboard is a simple "Done" tap (empty body `{}`). No UI for logging sets/reps/weight — only available via API directly. Add a log modal if per-session detail is needed.
- **C3**: `import_hash` has an index but no `UNIQUE` constraint — concurrent identical imports could create duplicates in theory. Acceptable for single-user; add constraint if multi-user.
- **L5**: Learning cron uses two-commit pattern in `_create_learning_todo` (`src/jobs/learning_daily.py`) — todo created then FK set. Non-atomic but low-probability; worst case one extra todo on next run. Consolidate into one transaction if this ever manifests.
- **L6**: Web sidebar `/learning` link is hardcoded, not gated by `/v1/modules`. When `module_learning_enabled=False` clicking shows 404 gracefully. Acceptable for single-user; fix if multi-user.
- **L7**: `/v1/learning/*` routes return `dict[str, Any]` rather than Pydantic response models. Matches modules endpoint style; tighten to models if stricter OpenAPI spec is needed.
- **P1**: Pulse `_fetch_yesterday_pulse` only looks back exactly 1 day (`src/pulse_signals/context.py`). If yesterday was silent or missing (cron skip, infra hiccup), today's `open` signal loses its alternation hint. Widen to "most recent non-silent pulse within last 7 days".
- **P2**: `open` catch-all signal fires whenever there is ≥1 todo or ≥1 calendar event (urgency 5.0 = silence threshold) (`src/pulse_signals/detectors/open.py`). When `focus` keyword and `opportunity` weather pattern don't trigger, `open` wins every day, and its prompt's "prefer alternation" rule is a soft hint with no flavor label, so Haiku may produce near-identical wording on consecutive days. Decide post-Phase-1 telemetry whether to raise threshold, lower `open` urgency, or add a hard A/B rule when consecutive `open` days occur (`src/pulse_signals/prompts.py`).

---

## Next Up

- **Deploy** migration 0016 (`learning_materials`) + all Learning V2 + redesign commits — `git pull` on GCP VM then `docker compose --profile migrate run --rm migrate` + restart `web` container
- **Visual verification** of redesign: stat cards, progress ring, filter pills, collapsible topic cards, Switch toggles, delete buttons — desktop + iPhone 14 Pro DevTools (393×852)
- **Write tests** for new components per spec: `progress-ring.test.tsx`, `switch.test.tsx`, `learning-item-row.test.tsx`, `learning-topic-card.test.tsx`, `learning-page.test.tsx` (`web/__tests__/`)
- Seed first learning topics + sections + items via `/learning/import` using `docs/learning-import-template.md` + Claude.ai
- Verify 2026-04-26 05:00 UTC pulse signal pipeline: `signal_type` populated, `parsed_data->'signal_trace'` is a JSON array. If always `open` with similar wording, address P1+P2 (`src/pulse_signals/context.py`, `src/pulse_signals/prompts.py`, `src/pulse_signals/detectors/open.py`).
- Add tag filtering to `hybrid_search()` for training memory queries (`src/retrieval/search.py`)
- Multi-metric aggregate form support in Settings page (`web/app/settings/page.tsx`)
