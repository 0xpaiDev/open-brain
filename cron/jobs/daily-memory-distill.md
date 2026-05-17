---
name: Daily Memory Distillation
time: '23:00'
days: daily
active: 'true'
model: haiku
notify: on_failure
description: "Extract durable facts from today's session log into STATE.md"
timeout: 5m
retry: '0'
---

# Daily Memory Distillation

Runs at 23:00 local time **and is catch-up-safe** — if the laptop was off for
N days, the next run processes every missed session log oldest → newest.
Reads `context/sessions/{date}.md` files and folds durable facts into
`context/STATE.md`. **Scope is limited to the project-bound layer** —
`~/.claude/projects/.../memory/` is the weekly curator's job.

## Inputs

- `open-brain/context/.last-distill` — sentinel file containing the ISO date
  of the most recent successful distillation (e.g. `2026-05-16`). Missing on
  first run.
- `open-brain/context/sessions/*.md` — per-day session logs from the
  SessionEnd hook. Files may be missing on days with no sessions.
- `open-brain/context/STATE.md` — current project state (cap: 2,500 chars)
- `~/.claude/projects/-home-shu-projects-open-brain/memory/*.md` — read-only
  reference; do not modify here

## Steps

1. **Determine the catch-up window.**
   - Read `context/.last-distill`. If missing, treat the last-distill date as
     `today − 1 day` (process today only on first run, do not back-fill weeks
     of history).
   - Enumerate every `context/sessions/{date}.md` where
     `last_distill_date < date <= today`.
   - If the list is empty: exit 0 with message
     `no sessions to distill (last_distill={date}, today={date})`. Do not
     touch STATE.md or the sentinel file.

2. **Read context.** Read current `STATE.md` and all personal-layer memory
   files. Identify what is **already represented** so the distillation does
   not duplicate facts that already live elsewhere.

3. **Distill one day at a time, oldest → newest.** For each session file in
   the window:
   - Scan for durable facts: active threads, in-flight decisions, sprint
     state, blockers. Skip ephemeral details (test output, one-off file
     reads, transient errors).
   - Update an in-memory copy of `STATE.md`:
     * Append new active threads under "Active Threads"
     * Remove resolved threads (anything explicitly closed)
     * Update "Current Sprint" if direction has changed
     * Do **not** rewrite history — STATE.md is a snapshot, not a log
   - Enforce the 2,500-character cap. If applying the update would overflow,
     consolidate older entries first (merge or drop the least-relevant), then
     apply the new content.

4. **Write `STATE.md` once** with the final consolidated content (single write
   per run, not per session-day).

5. **Update the sentinel.** Write today's local ISO date to
   `context/.last-distill`. This is the catch-up anchor for the next run.

6. **Report a diff line** like:
   `STATE.md: 1,847/2,500 chars (74%) — distilled 3 days, +2 threads, -1 resolved`

## Constraints

- Never touch `context/DECISIONS.md` (manual + agent-on-request only)
- Never touch `~/.claude/projects/.../memory/` (weekly curator owns it)
- Never call `search_memory` / `get_context` — STATE.md is for already-in-context
  facts, not retrieval candidates
- Only write `context/.last-distill` **after** `STATE.md` is safely on disk —
  if STATE.md write fails, leave the sentinel alone so the next run retries
  the same window
- Fail closed: if any write fails, exit non-zero so the runner / cron
  scheduler notifies the user
