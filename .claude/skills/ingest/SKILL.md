---
name: ingest
description: Ingest the current Claude Code session into Open Brain memory. Use when the user says "/ingest", "save this session", "remember this", or wants to capture decisions and discoveries from the current conversation into their memory system.
---

# Ingest Session — Open Brain Memory Capture

Captures the meaningful parts of the current conversation into Open Brain for RAG retrieval in future sessions. Only invoke when the user explicitly asks — this replaces the old automatic stop hook with intentional, high-quality capture.

## Step 1 — Assess the session

Review the full conversation context. Identify:

- **Decisions made**: architectural choices, technology picks, trade-offs evaluated
- **Discoveries**: bugs found, root causes identified, non-obvious behaviors learned
- **Outcomes**: what was built, fixed, refactored, or deployed
- **Knowledge gained**: patterns learned, gotchas encountered, configuration details

If the conversation contains nothing meaningful (only file reads, trivial fixes, test runs with no surprises), tell the user:

> This session doesn't contain decisions or discoveries worth capturing. Nothing ingested.

Stop here. Do not ingest.

## Step 2 — Compose the memory text

Write a concise, structured summary. Target 500-2000 words. Do NOT include raw tool output, file contents, or verbose code blocks — summarize what matters.

Format:

```
Session: [DATE] — [1-line description of what the session was about]

## Decisions
- [Decision]: [Why this choice was made, what alternatives were considered]

## Discoveries
- [What was learned]: [Context and implications]

## Outcomes
- [What changed]: [Files/systems affected, before/after]

## Key Details
- [Any specific configuration, commands, patterns, or numbers worth remembering]
```

Omit any section that has no entries. Keep the total text under 10,000 characters.

**If the user provided arguments** (e.g., `/ingest decided to use pgvector for embeddings`), use their text as focus guidance — emphasize those topics in the summary, but still review the full conversation for additional context worth capturing.

## Step 3 — Ingest via MCP

Call the `ingest_memory` MCP tool with:
- **text**: the composed summary from Step 2
- **source**: `"claude-code-manual"`

## Step 4 — Report

Tell the user the result:
- **Queued**: "Session ingested (raw_id: {id}). It will be processed by the pipeline shortly."
- **Duplicate**: "This content was already ingested within the last 24 hours."
- **Error**: Surface the error message so the user can decide what to do.

Done. No other actions needed.
