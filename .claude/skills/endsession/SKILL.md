---
name: endsession
description: Run at the end of every Open Brain work session to keep CLAUDE.md, PROGRESS.md, ARCHITECTURE.md, and HISTORY.md accurate and up to date. Trigger when the user says "end session", "wrap up", "endsession", "session done", or asks to update project docs before stopping work.
---

# End Session — Open Brain Doc Maintenance

Runs at the end of a work session. Updates the project memory files to reflect what was actually done. Goal: the next session starts with zero re-explanation needed.

## Step 1 — Scan the session

Before touching any file, answer these questions from the current conversation context:

- What was built, fixed, or changed?
- Were any new files created or deleted?
- Which specific files were touched this session? (collect actual paths)
- Did any architectural decisions get made or reversed?
- Were any new gotchas or non-obvious patterns discovered?
- Did the test count change? What is it now?
- Are there any new open items, deferred decisions, or next steps?

Do not write anything yet. Hold this summary internally.

## Step 1.5 — Advance backlog spec (optional)

If this session shipped or abandoned a feature tracked in `docs/backlog/`:

1. Check if any file in `docs/backlog/` matches what was built or dropped this session.
2. If yes:
   - Update its frontmatter: `status: shipped` (or `abandoned`) and add `shipped:` / `abandoned:` date.
   - Move it: `mv docs/backlog/<file> docs/archive/<file>`
3. If no backlog file matches, or the session was planning/doc-only: skip silently.

## Routing rule — what goes where

For each thing discovered this session, route it through this decision tree:

```
"Will the next agent write broken code if they don't know this?"
  YES → ## Footguns in CLAUDE.md (short imperative rule + file path)
  NO  → continue

"Is this a 'we chose X over Y' architectural decision?"
  YES → context/DECISIONS.md (one-liner, dated entry, append-only)
  NO  → continue

"Is this ops/deployment state (test count, migration, deploy status, cron)?"
  YES → PROGRESS.md
  NO  → continue

"Was an external API call added, removed, or its model/key/trigger changed?"
  YES → context/SERVICES.md (update the relevant row or add a new one)
  NO  → continue

"Was a domain term resolved — canonical name chosen, ambiguous concept clarified, wrong word corrected?"
  YES → verify context/GLOSSARY.md was already updated mid-session; if not, update it now
  NO  → continue

"Is this a record of what happened this session?"
  YES → HISTORY.md
  NO  → don't write it anywhere
```

**Anti-patterns — don't do these:**
- Do NOT add "why we built X" rationale to CLAUDE.md. That belongs in DECISIONS.md.
- Do NOT add behavioral rules or footguns to DECISIONS.md.
- Do NOT add session narrative to PROGRESS.md. That belongs in HISTORY.md.
- Do NOT write to CLAUDE.md just because something is interesting — only if an agent *will break prod* without it.

## Step 2 — Update CLAUDE.md

Read CLAUDE.md. Apply only changes where the routing rule says "Footguns":

- New footguns or gotchas discovered this session
- Patterns that changed (e.g. a new required step after migrations)
- Anything removed that is no longer true

**Size budget:** `## Footguns` target is ≤35 entries. If adding a new entry would push past that, cut the most stale existing entry first. If adding content would push the file past 130 lines, cut something stale first.

Do NOT add: completed work summaries, session notes, test counts, architectural rationale, or anything that belongs in PROGRESS.md or DECISIONS.md.

## Step 3 — Update PROGRESS.md

Read PROGRESS.md. Update:

- Status line and test count if changed
- Deployment info if anything was deployed or config changed
- Open Tech Debt — add new items, remove any that were resolved this session
- Next Up — replace with what actually comes next based on this session's outcome

**Path tagging rule:** Every entry that describes a change must include the affected file paths inline. This enables downstream tools (like prompt-h) to filter by relevance.
- Good: `Fixed todo sync race condition (api/routes/todos.py, services/todo_sync.py)`
- Bad: `Fixed todo sync race condition`

Do NOT add session narrative or detailed change logs — that goes in HISTORY.md.
Target: keep PROGRESS.md under 70 lines.

## Step 4 — Append to HISTORY.md

Append a new entry at the TOP of HISTORY.md (newest first). Format:

```
## Session — [DATE]

**What changed**: [2-4 bullet points, concrete: file names, feature names, test delta]
**Files touched**: [comma-separated list of files created, modified, or deleted]
**Decisions made**: [any architectural or design decisions, or "none"]
**Gotchas found**: [anything non-obvious discovered, or "none"]
**Test count**: [X total (Y backend + Z frontend) or just X if only one suite]
```

Keep each entry under 15 lines. Bullets only, no prose paragraphs.

## Step 5 — Update context/DECISIONS.md (only if needed)

Read context/DECISIONS.md. Append a new dated block at the TOP (below the header, above the previous entry) only if this session involved a "we chose X over Y" architectural decision — a design choice that isn't obvious from the code.

Format:
```
## YYYY-MM-DD — [Short title]

[One or two sentences: what was decided and why.]
```

**Hard cap: 5,000 characters.** If adding would overflow, summarise or trim the oldest entry before adding.

Do NOT add behavioral rules here — those go in CLAUDE.md Footguns.
If no architectural decision was made this session: skip this file entirely.

## Step 6 — Update ARCHITECTURE.md (only if needed)

Read the Maintenance Rule section in ARCHITECTURE.md. Only update if this session involved:

- A new table added (update schema section + table count)
- A stack decision changed (update Stack Decisions table)
- A new module or service added
- The importance formula or retrieval weights changed

If none of the above apply: skip this file entirely.
If an update is needed: make the minimal targeted change. Do not restructure.
Bump the version by 0.1 and update the date.

## Step 7 — Deploy prompt

If this session involved changes that could be deployed (new features, bug fixes, config changes), ask the user:

> "Changes are committed. Want me to run `/deploy`?"

- If yes: run the `/deploy` command
- If no: skip and proceed to the report
- If the session was planning-only, doc-only, or no deployable changes were made: skip this step entirely without asking

## Step 8 — Report

Print a short summary:

- CLAUDE.md: [changed / no changes]
- PROGRESS.md: [what was updated]
- HISTORY.md: [entry added]
- context/DECISIONS.md: [entry added / skipped]
- context/SERVICES.md: [updated / skipped]
- context/GLOSSARY.md: [updated / already current / skipped]
- ARCHITECTURE.md: [changed / skipped]

Done. No other files touched.
