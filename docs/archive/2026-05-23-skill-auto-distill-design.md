---
status: shipped
created: 2026-05-23
shipped: 2026-05-23
---

# Skill Auto-Distill (`/distill-skill`) — Design

**Status:** active
**Date:** 2026-05-23
**Source idea:** Hermes Agent's `skill_manage` tool (procedural memory).

## Context

Skills under `.claude/skills/` (project) and `~/.claude/skills/` (global) are hand-authored today. After a non-trivial debugging arc or a multi-step workflow that finally lands, the recipe lives only in the session transcript and is lost the moment the conversation ends. Useful procedures don't survive across sessions unless I manually stop to write them up — which I rarely do.

Hermes treats skills as **procedural memory**: the agent itself can author them via a `skill_manage` tool, triggered when a workflow proves non-trivial. We want the same effect without the cost of automatic detection (which is noisy and hard to tune for a single user).

The minimum-viable version is **explicit only**: a user-invoked skill that drafts a SKILL.md from the current session, runs a dedup check, classifies scope (project vs. global), and writes the file after user approval. Automatic detection is deferred to v2 — we don't know yet whether the drafts will be coherent enough to trust without review, and we shouldn't pay the cost of session-end hooks until we do.

## Goals

1. Turn a non-trivial session into a saved skill in under 60 seconds of user attention.
2. Never write a skill the user hasn't seen.
3. Catch obvious duplication before it lands on disk.
4. Make the right scope decision (project vs. global) by default, but let the user override.

## Non-goals (v1)

- Automatic detection at session end.
- Cross-session pattern mining (would need an FTS5 transcript index — separate idea, not blocking).
- In-place editing of existing skills (Hermes' `patch`/`edit` actions). v1 only creates new skills.
- Tagging taxonomy. Start untagged; revisit when we have ≥10 distilled skills.
- Sharing/publishing to a registry.

## Architecture

A single skill file at `~/.claude/skills/distill-skill/SKILL.md`. No backend code, no new tools, no MCP additions. The skill works by giving Claude a procedure to follow when the user invokes it; all the work happens inside the conversation Claude already has.

### Procedure (what the skill instructs Claude to do)

1. **Identify the recipe.**
   Scan the last N turns (default 30, or since the most recent `/clear` if shorter). Identify the user's stated objective and the sequence of tool calls + decisions that resolved it. If the recipe is unclear, ask the user to describe in one sentence what should become a skill.

2. **Draft the SKILL.md.**
   Follow the structure already used by existing project skills (e.g. `.claude/skills/ingest/SKILL.md`):
   - YAML frontmatter: `name` (kebab-case), `description` (the trigger sentence — what the user would say to invoke this skill).
   - Body sections: **When to Use**, **Procedure** (numbered steps), **Pitfalls** (gotchas encountered along the way), **Verification** (how to know the skill worked).
   - Keep description specific. "Use when the user wants to X" beats "useful for general tasks."

3. **Classify scope.**
   Decide whether the procedure is tied to this project's code/conventions (→ project scope, `.claude/skills/`) or generally useful across any repo (→ global scope, `~/.claude/skills/`). Show the classification and one-sentence reasoning. User can override.

4. **Dedup check.**
   Run `ls` on both `.claude/skills/` and `~/.claude/skills/`. Read the frontmatter `description` of any skills with overlapping keywords or kebab-case names. If a similar skill exists, surface it: "This looks similar to `<existing>` — extend that one instead?"

5. **Approval gate.**
   Show the full draft inline. User options:
   - Accept → write the file.
   - Edit → user provides changes, redraft, show again.
   - Change scope → re-classify and confirm the new path.
   - Reject → discard, no file written.

6. **Write.**
   - Project scope → `<cwd>/.claude/skills/<name>/SKILL.md`
   - Global scope → `~/.claude/skills/<name>/SKILL.md`
   - Create the parent directory if needed.
   - Do not commit. The user decides whether to stage the new file.

### Trigger phrasing

The skill `description` should match any of: `/distill-skill`, "save this as a skill", "distill this into a skill", "make a skill from this session". The using-superpowers flow will surface it on those phrasings.

## Critical files

- **New:** `~/.claude/skills/distill-skill/SKILL.md`
- **Reference for SKILL.md structure:** `.claude/skills/ingest/SKILL.md`, `.claude/skills/endsession/SKILL.md`
- **Reference for the Hermes shape we're approximating:** any superpowers skill under `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.1.0/skills/`

## Verification

1. End a non-trivial session, invoke `/distill-skill`. Claude proposes a coherent SKILL.md draft.
2. Invoke `/distill-skill` a second time on overlapping work — dedup warning fires, naming the similar existing skill.
3. Scope classification reads sensibly: a procedure about Open Brain SQL gets classified as project; a procedure about Git workflow gets classified as global.
4. Accept the draft. File lands at the expected path. Parent dir auto-created if absent.
5. Start a fresh Claude Code session. Invoke the new skill by trigger phrase. It loads via the Skill tool and runs.

## Risks / why this is small

It's a single markdown file. Failure modes are: drafts are too generic, dedup misses obvious duplicates, scope classification is wrong. All three are fixed by editing the SKILL.md text — no rollback, no migration. That's the correct level of investment for an idea we haven't validated.

## Open questions (deferred)

- `metadata.tags` taxonomy → defer until ≥10 distilled skills exist; the taxonomy is easier to design from real examples than from speculation.
- `/distill-skill <topic>` (partial-session scope) → defer; start with whole-session scope, add filter later if needed.
- `/distill-skill --extend <existing>` (treat as a patch to an existing skill) → defer to v2; same shape as the Hermes `patch` action but worth waiting until create-only proves valuable.
