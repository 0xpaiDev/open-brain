# State

Project-bound active context. Maintained by `cron/jobs/daily-memory-distill.md`
(daily Haiku distillation of the previous day's session log). Hard cap: 2,500
characters. The curator consolidates entries when adding would overflow.

Read at session start as part of the tier-0 frozen snapshot. Mid-session edits
persist to disk but only take effect next session.

## Active Threads

- (none yet — first session after the memory flywheel landed)

## In-flight Decisions

- (none yet)

## Current Sprint

- 2026-05-17 — Claude Code Memory Flywheel implementation
