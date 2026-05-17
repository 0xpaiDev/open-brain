# Decisions

Append-only architectural decision log. Dated entries, newest at the top.
Hard cap: 5,000 characters. Trim or summarise the oldest entries when adding
would overflow. Manual + agent-on-request only — the daily / weekly curators
do not touch this file.

Read at session start as part of the tier-0 frozen snapshot.

## 2026-05-17 — Claude Code Memory Flywheel

Adopted the two-layer markdown + SessionEnd auto-capture + memory_expand design
in `docs/superpowers/specs/2026-05-17-claude-code-memory-flywheel-design.md`.
Personal layer (`~/.claude/.../memory/`) keeps Hermes-style curation; project
layer (`context/STATE.md`, `context/DECISIONS.md`) ships with the repo.
Auto-capture is unattended at SessionEnd via `scripts/claude-code/session-end-ingest.sh`
+ deterministic repo→project mapping. Tier-0/1/2/3 retrieval contract codified
in CLAUDE.md.
