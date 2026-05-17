---
name: Weekly Memory Curator
time: '09:00'
days: sun
active: 'true'
model: sonnet
notify: on_finish
description: "Prune and consolidate ~/.claude/.../memory/ markdown files"
timeout: 10m
retry: '0'
---

# Weekly Memory Curator

Runs Sunday 09:00 local time. Owns the **personal layer** at
`~/.claude/projects/-home-shu-projects-open-brain/memory/`. Keeps each file
under its cap, drops stale facts, merges duplicates, and keeps the `MEMORY.md`
index in sync with the supporting files.

## Inputs

- `~/.claude/projects/-home-shu-projects-open-brain/memory/*.md` — all
  personal-layer markdown files (read + write)
- `open-brain/context/STATE.md` and `DECISIONS.md` — read-only reference for
  what is currently active in the project layer (so personal memories that
  duplicate project-layer entries can be trimmed)

## Per-file caps (enforced at write time)

| File | Cap |
|---|---|
| `MEMORY.md` (index) | 200 lines |
| `user_profile.md` | 1,500 chars |
| `ops_deployment.md` | 2,500 chars |
| `feedback_*.md` (each) | 1,500 chars |
| `project_*.md` (each) | 2,500 chars |
| `learning.md` | 2,500 chars |
| `config_auto_capture.md` | 1,500 chars |

## Steps

1. List every file in the personal layer. Note size vs. cap.

2. For each non-index file: read it, identify entries that are
   - duplicated across files (consolidate to the most appropriate file)
   - stale (referencing decisions that have since been superseded — check
     against `context/DECISIONS.md` and recent memory_items)
   - still active and unique (leave alone)

3. Apply edits. Enforce caps — if a file is still over-cap after dedup, drop
   the lowest-importance entry. Never silently truncate prose mid-sentence.

4. Rebuild `MEMORY.md` so each supporting file gets exactly one line entry
   under the right section. Update the "Last consolidated: YYYY-MM-DD" date.

5. Report per file:
   `{filename}: {N}/{cap} chars ({percent}%) — {delta vs last week}`

## Constraints

- Never touch `context/STATE.md` or `context/sessions/` (project layer)
- Never touch `context/DECISIONS.md` (manual + agent-on-request only)
- Never re-embed memories — this curator is markdown-only
- `MEMORY.md` is an index, not a memory. Never write content directly into it
- Fail closed: if any file write fails, surface via `notify: on_finish`
