# State

Project-bound active context. Maintained by `cron/jobs/daily-memory-distill.md`
(daily Haiku distillation of the previous day's session log). Hard cap: 2,500
characters. The curator consolidates entries when adding would overflow.

Read at session start as part of the tier-0 frozen snapshot. Mid-session edits
persist to disk but only take effect next session.

## Active Threads

- **Commitments Feature (3 specs):** Spec 0 (chart fix, standalone), Spec B (exercise library + per-day schedule + import wizard + plan editor), Spec A (inline log form + day-swap, depends on B). Per-day schedule requires new junction table `commitment_entry_exercises` for workout day granularity (current schema discards it, all exercises show every day). Import wizard: blocking three-step (validate → resolve unknowns → confirm). Detail page must query by ID directly (not list endpoint).
- **Docs restructuring:** Four-step plan (README with status gates, skills hygiene in CLAUDE.md, selective skill shadowing, migrate folders). Deprioritized vs. Commitments; next after shipped.

## In-flight Decisions

- Schema: New `exercises` table (name normalized unique), `commitment_entry_exercises` junction (entry→exercise), `commitment_exercises.exercise_id` FK (nullable SET NULL)
- Import wizard adds step 2 (resolve unknown exercises: create new or match existing)
- Plan CRUD editor: calendar day layout with inline exercise picker
- Execution: Superpowers subagent workflow (subagent-driven-development, executing-plans) for parallel work, not prompt-h multi-agent harness

## Current Sprint

- 2026-05-17 → ongoing — Commitments system (specs 0/B/A with dependency chain)
- SessionEnd hook fixed 2026-05-19 (detach worker via nohup/disown, no longer blocks on Haiku)
- 2026-05-23: Distill-skill shipped and live; chat tools (Plan 2) deferred pending tool-use loop in backend
