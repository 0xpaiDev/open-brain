---
status: shipped
created: 2026-05-23
shipped: 2026-05-23
---

# Docs Cleanup — Todo Plan

**Status:** ready
**Date:** 2026-05-23
**Owner:** Shu (solo)

## Goal

Stop superpowers' brainstorm → spec → plan → executing four-artifact dance from littering `docs/superpowers/specs/` with overlapping documents. Establish: **one file per backlog item, status gates in frontmatter, file moves from `backlog/` to `archive/` exactly once at ship.** All workflow stages converge into the same document as it matures.

## Workflow stages condensed into one file

Superpowers' stages become `status` values on the same file:

| Superpowers stage | Status | What the file contains |
|---|---|---|
| brainstorming output | `idea` or `refined` | Loose notes, design axes |
| design doc | `ready` | Locked design, decisions made |
| writing-plans output | `ready` (still) | A "Plan" section appended |
| executing | `in-progress` | Plus a progress log |
| done | `shipped` | Final state, file moves to `archive/` |
| won't ship | `abandoned` | Move to `archive/` with reason |

## Todo plan (4 items, do in order)

### 1. Write the convention README

Replace `docs/superpowers/specs/README.md` with a 2-page convention doc covering:

- The two folders (`backlog/`, `archive/`) and what lives in each.
- The status frontmatter schema (status, created, shipped/abandoned, gates list).
- The valid `status` values and what each means.
- **Override clause:** explicitly state that this convention supersedes the superpowers `brainstorming` → `writing-plans` → `executing-plans` artifact split. Brainstorming/writing-plans skills still run their *process*, but their *output* lands in one file in `backlog/`, not separate documents.
- A short example file (frontmatter + 3-line body) to anchor the convention.

Also: add a one-line pointer in `CLAUDE.md` so Claude reads it every session.

**Why first:** load-bearing. Steps 2–4 depend on this being settled.

### 2. Skills hygiene — instruction-level only, no file copying

Add a "skills loaded vs. skipped" note to either project `CLAUDE.md` or global `~/.claude/CLAUDE.md`. No copying, no shadowing yet — just instruction-level scoping that tells Claude which superpowers skills are noise for solo Open Brain work.

**Revised split (now that prompt-h is abandoned and superpowers is the active workflow):**

- **Keep, active workflow** — `subagent-driven-development`, `executing-plans`, `dispatching-parallel-agents`, `writing-plans`. These are the new replacement for prompt-h.
- **Keep, well-tuned** — `systematic-debugging`, `verification-before-completion`, `test-driven-development`, `requesting-code-review`, `receiving-code-review`.
- **Keep, occasional** — `writing-skills` (for when authoring skills like distill-skill).
- **Skip / silent-disable** — `using-git-worktrees` (solo, single-branch most of the time), `finishing-a-development-branch` (you ship to master directly, no PR-driven flow).
- **Customize candidates (for step 3)** — `brainstorming` (too heavy for "give me 5 ideas" tasks — we hit this earlier this session), `using-superpowers` (forces a skill check before every response, overkill for trivial messages).

**Why second:** trying shadow-only (step 3) before knowing which skills genuinely chafe is premature. Use the instruction-level scoping for 1–2 weeks, see which skills *actually* bother you in practice, then shadow only those.

### 3. Selective shadow — only the 2 that genuinely chafe (after a 1–2 week trial period)

After running with step 2 for a while, copy ≤3 skills into `~/.claude/skills/` (or `.claude/skills/` if project-scoped) with the same name as their superpowers counterpart. Project skills override plugin skills automatically — no plugin uninstall needed.

Likely candidates based on this session:

- **`brainstorming`** — needs a "lightweight" path that distinguishes ideation (5 bullets, no spec) from real design work (spec doc + writing-plans handoff). The current skill forces every brainstorm through the heavy path.
- **`using-superpowers`** — relax the "invoke a skill before every response" rule for trivially simple messages.

Leave everything else under the plugin so it keeps getting free upstream improvements.

**Why third:** the value of customizing is real but the maintenance burden is real too. Customize the minimum.

### 4. Mechanical migration of existing docs

Once the convention is settled (step 1), retrofit the existing docs:

1. Rename `docs/superpowers/specs/active/` → `backlog/`.
2. Rename `docs/superpowers/specs/done/` → `archive/`.
3. Add the frontmatter status header to all 8 existing files:
   - 6 files currently in `done/` → `status: shipped`, move to `archive/`.
   - `2026-05-23-skill-auto-distill-design.md` → `status: shipped`, move to `archive/` (the skill itself ships today's session).
   - `2026-05-23-chat-tools-brief.md` → `status: refined` (not `ready` yet — still needs brainstorm session), stays in `backlog/`.
   - This file → `status: shipped` once items 1–4 done, move to `archive/`.
4. Update `INDEX.md` if it lists paths — point to the new folder names.

**Why last:** boring mechanical work. Don't do it before the convention is locked or we'll redo it.

## Deferred (not in this todo)

- **Full detach from superpowers plugin.** Defer indefinitely. The maintenance burden outweighs the customization value as long as we're under ~3 shadowed skills.
- **Routine superpowers update check.** Defer until step 3 reveals ≥3 shadowed skills (= a real "drift surface" worth monitoring). At that point, a monthly scheduled agent that diffs upstream releases makes sense.
- **`prompts/new/` migration.** That folder is for multi-agent prompt harness output (the old prompt-h flow). Now that prompt-h is abandoned in favor of the superpowers workflow, the folder can be archived — but that's a separate cleanup, not part of this todo.

## Definition of done for this todo

- `docs/superpowers/specs/README.md` reflects the new convention and is referenced from `CLAUDE.md`.
- All existing specs have status frontmatter and live in either `backlog/` or `archive/`.
- Skills hygiene note exists in `CLAUDE.md` (or `~/.claude/CLAUDE.md`) listing which superpowers skills are skip-candidates.
- ≤3 shadowed skills exist under `~/.claude/skills/` or `.claude/skills/` (likely 0 at first — wait for the 1–2 week trial).
- This file moves to `archive/` with `status: shipped`.
