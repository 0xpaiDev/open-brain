# State

Project-bound active context. Maintained by `cron/jobs/daily-memory-distill.md`
(daily Haiku distillation of the previous day's session log). Hard cap: 2,500
characters. The curator consolidates entries when adding would overflow.

Read at session start as part of the tier-0 frozen snapshot. Mid-session edits
persist to disk but only take effect next session.

## Active Threads

- **Commitments Feature (3 specs):** Spec 0 (chart fix, standalone), Spec B (exercise library + per-day schedule + import wizard + plan editor), Spec A (inline log form + day-swap, depends on B). Per-day schedule requires new junction table `commitment_entry_exercises` for workout day granularity. Import wizard: three-step (validate → resolve → confirm). Detail page must query by ID directly (not list).
- **Docs restructuring:** CLAUDE.md doc placement hardened as HARD RULE (all backlog items in single file per item). `context/GLOSSARY.md` + `context/SERVICES.md` created. Skills and superpowers artifact split completed.

## In-flight Decisions

- Schema: New `exercises` table (name normalized unique), `commitment_entry_exercises` junction (entry→exercise), `commitment_exercises.exercise_id` FK (nullable SET NULL)
- Import wizard adds step 2 (resolve unknown exercises: create new or match existing)
- Plan CRUD editor: calendar day layout with inline exercise picker
- Execution: Superpowers subagent workflow (subagent-driven-development, executing-plans) for parallel work

## Current Sprint

- 2026-05-17 → ongoing — Commitments system (specs 0/B/A with dependency chain)
- 2026-05-24: **Chat tools library shipped** — 7 tools (5 todo + 2 memory), Sonnet-based tool loop, hybrid intent classifier (regex + Haiku), ChatLog table (0023 migration), localStorage UI toggle. All 3 PRs merged, deployed to prod, 955 backend tests + 315 frontend tests passing.
- Next: Commitments Spec 0 (chart fix, standalone); Spec B + A follow