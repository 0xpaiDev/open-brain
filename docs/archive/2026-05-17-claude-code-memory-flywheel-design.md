---
status: shipped
created: 2026-05-17
shipped: 2026-05-23
---

# Claude Code Memory Flywheel — Design

**Date:** 2026-05-17
**Status:** Approved for planning
**Author:** Shu (with Claude)

---

## Context

The trigger for this design was a third-party "Claude Code Memory Improvements" prompt that proposed installing `memsearch` (a Zilliz-built markdown-indexed memory system) alongside a parallel `context/MEMORY.md` + `context/USER.md` file tree, captured via a per-turn Stop hook.

Adopting that prompt naively was rejected for two reasons:

1. **Open-brain already exceeds memsearch's capabilities.** The project has Voyage-3 (1024-d) embeddings, pgvector hybrid search with GIN-FTS, importance/recency ranking, SHA-256 dedup, and supersede semantics. Memsearch's pitch (Milvus Lite + bge-m3 ONNX + RRF) is a less-featured subset of what's already in production.
2. **Two parallel memory systems is worse than one.** File-based session capture that doesn't land in the vector DB would create a second source of truth that's invisible to the iOS shortcut, the web dashboard, and the existing search/get_context MCP tools.

The **real gap** is the Hermes-style discipline that the prompt was pointing at without naming correctly: agent-curated markdown files with hard character caps, weekly pruning, frozen-snapshot loading at session start, and tier-0 (already-in-context) free recall before falling through to vector search. The existing `~/.claude/projects/.../memory/MEMORY.md` already does some of this — last consolidated 36 days ago, with no enforced caps and no auto-capture from sessions — but it has drifted because nothing maintains it.

This spec describes the system that closes that gap: **a Claude Code memory flywheel built on top of open-brain's existing vector DB, with two-layer markdown curation, SessionEnd auto-capture, deterministic repo→project tagging, and a new `memory_expand` MCP tool for progressive disclosure**.

The intended outcome: every Claude Code session ends with one structured Haiku summary landing in both the markdown layer and the vector DB; session-start context is a curated 3,000-token snapshot rather than a 14-day-stale index; and Claude has a tier-0 → tier-3 retrieval discipline rather than searching from cold every time.

---

## Architecture Overview

Five components, layered:

1. **Two-layer markdown memory** — personal (`~/.claude/`) and project-bound (`open-brain/context/`)
2. **SessionEnd auto-capture hook** — Haiku summary → file + vector DB
3. **Cron curators** — daily distillation + weekly pruning
4. **Tier-0/1/2/3 retrieval contract** — encoded in CLAUDE.md
5. **`memory_expand` MCP tool** — new endpoint for progressive disclosure

```
┌─────────────────────────────────────────────────────────────────┐
│ Tier 0 — already in context (free, zero-latency)                │
│   ~/.claude/projects/.../memory/MEMORY.md + supporting files    │
│   open-brain/context/STATE.md + DECISIONS.md                    │
│   Total ≈ 3,000 tokens, loaded at SessionStart                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ↓ (escalate if T0 doesn't answer)
┌─────────────────────────────────────────────────────────────────┐
│ Tier 1 — search_memory("query")                                 │
│   Existing MCP tool, hybrid search, returns top-K with IDs      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ↓ (when a T1 hit needs full context)
┌─────────────────────────────────────────────────────────────────┐
│ Tier 2 — memory_expand(memory_id)  ← NEW                        │
│   Returns full content + parent RawMemory + neighbors           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ↓ (broad fallback)
┌─────────────────────────────────────────────────────────────────┐
│ Tier 3 — get_context("query", limit=20)                         │
│   Existing MCP tool, token-budgeted dump                        │
└─────────────────────────────────────────────────────────────────┘

Write path (SessionEnd):
  $CLAUDE_PROJECT_DIR → repo→project mapping → Haiku summary →
    1. append to open-brain/context/sessions/{date}.md (gitignored)
    2. POST /v1/memory with source="claude-code-session", project=<resolved>
```

---

## Component 1 — Two-Layer Markdown Memory

### Personal layer (`~/.claude/projects/-home-shu-projects-open-brain/memory/`)

Already loaded at session start by the system prompt's auto-memory mechanism. We **keep this location**, harden it with caps, and let the curator maintain it.

| File | Purpose | Cap | Maintained by |
|---|---|---|---|
| `MEMORY.md` | Index pointing to supporting files | 200 lines (existing) | Weekly curator |
| `user_profile.md` | Hermes-style `user.md` — preferences, role, working style | 1,500 chars | Agent on the fly + weekly curator |
| `ops_deployment.md` | Deployment procedures, SSH alias, prod URL | 2,500 chars | Weekly curator |
| `feedback_*.md` | One file per feedback rule | 1,500 chars each | Agent on the fly |
| `project_*.md` | One file per project area | 2,500 chars each | Weekly curator |
| `learning.md` | Study syllabus | 2,500 chars | Agent + manual |
| `config_auto_capture.md` | Auto-capture conventions | 1,500 chars | Manual |

### Project-bound layer (`open-brain/context/`)

New. Git-tracked except `sessions/` which is gitignored.

| File | Purpose | Cap | Maintained by |
|---|---|---|---|
| `STATE.md` | Hermes-style `memory.md` — active threads, in-flight decisions, current sprint | 2,500 chars | Daily curator |
| `DECISIONS.md` | Architectural decisions, append-only with dated entries | 5,000 chars | Manual + agent on user request |
| `sessions/{YYYY-MM-DD}.md` | Daily append-only session log | unbounded (rotated nightly) | SessionEnd hook |

### Loading at session start

The existing system-prompt auto-memory loads `~/.claude/projects/.../memory/MEMORY.md` automatically. We extend this by adding two CLAUDE.md sections:

```markdown
## Session Context

At session start, also read these project-bound state files:
- `context/STATE.md` — active threads, current sprint, in-flight decisions
- `context/DECISIONS.md` — architectural decisions (dated, append-only)

These plus the auto-loaded `~/.claude/projects/.../memory/MEMORY.md` form your
"frozen snapshot" (~3,000 tokens). Mid-session writes to any of these files
persist to disk but take effect next session.
```

### Cap enforcement

Caps are enforced **at write time** by whichever process writes (agent, daily curator, weekly curator). Each writer must:

1. Read the file
2. Compute `wc -c` (or equivalent)
3. If adding would exceed cap → consolidate existing entries first
4. Write
5. Confirm "Saved — will be active from next session" (when agent-initiated)

No lint, no test, no CI check. The caps are operational, not structural.

---

## Component 2 — SessionEnd Auto-Capture Hook

### Hook location and trigger

- **Location:** `~/.claude/hooks/session-end-ingest.sh` (user-level, fires for every Claude Code session)
- **Trigger:** SessionEnd hook in `~/.claude/settings.json`
- **Implementation script:** lives in this repo at `scripts/claude-code/session-end-ingest.sh`, symlinked into `~/.claude/hooks/` on each machine (see Portability section)

### Repo → project mapping

Deterministic, based on `$CLAUDE_PROJECT_DIR`. Hardcoded `case` statement in the script:

```bash
case "$(basename "$CLAUDE_PROJECT_DIR")" in
  open-brain)    PROJECT="open-brain" ;;
  egle-climbing) PROJECT="Egle-climbing" ;;
  # Add new repos here
  *)             PROJECT="" ;;  # falls back to "Personal" via NULL
esac
```

Adding a new project = one line in the script + `git commit`. No JSON file, no dynamic discovery, no Haiku inference.

### Idempotent project-label creation

Before posting the memory, the hook ensures the `project_labels` row exists:

```bash
if [ -n "$PROJECT" ]; then
  curl -fsS -X POST "$OPENBRAIN_API_URL/v1/project-labels" \
    -H "X-API-Key: $OPENBRAIN_API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"$PROJECT\"}" \
    >/dev/null 2>&1 || true   # 409 on existing is fine
fi
```

### Capture flow

1. **Read transcript.** Locate the session's JSONL transcript file (Claude Code writes these per-session). Path provided by hook env or constructed from `$CLAUDE_PROJECT_DIR`.
2. **Haiku summarization.** Pipe the transcript through a Haiku call with the existing `/ingest` skill's prompt (Decisions / Discoveries / Outcomes / Key Details, 500–2000 words). Use Anthropic API directly — no need to round-trip through the open-brain backend.
3. **Skip-if-trivial.** Same escape hatch as the existing `/ingest` skill: if Haiku returns "This session doesn't contain decisions worth capturing," exit 0 silently.
4. **Write markdown.** Append to `$CLAUDE_PROJECT_DIR/context/sessions/{YYYY-MM-DD}.md`:
   ```
   ## {HH:MM} — Session {N}
   <Haiku summary>
   ```
   The hook creates `context/sessions/` only if the repo already has a `context/` directory (i.e. opted into this system). Repos without `context/` get vector-DB ingestion only, no markdown file. This prevents polluting unrelated repos with `context/` directories.
5. **Ingest to vector DB.** `POST /v1/memory`:
   ```json
   {
     "text": "<full summary>",
     "source": "claude-code-session",
     "project": "<resolved project or omitted>"
   }
   ```
6. **Log silently.** Echo result to `/tmp/ob-session-end.log`. Never block, never error to stderr — SessionEnd hooks must be fire-and-forget.

### Source-label constants

Add `"claude-code-session"` to `AUTO_CAPTURE_SOURCES` in [src/pipeline/constants.py](src/pipeline/constants.py). This caps importance and skips Task row creation, consistent with the existing pattern for `claude-code-manual`.

### Relationship to existing `/ingest` skill

- **`/ingest` skill stays unchanged** — remains the manual mid-session override for "save this insight now"
- **The hook is additive** — uses the same prompt structure but runs unattended at SessionEnd

---

## Component 3 — Cron Curators

Two new jobs in [cron/jobs/](cron/jobs/).

### Daily memory distillation (`daily-memory-distill.md`)

```yaml
name: Daily Memory Distillation
time: '23:00'
days: daily
active: 'true'
model: haiku
notify: on_failure
description: 'Extract durable facts from today's session log into STATE.md'
timeout: 5m
retry: '0'
```

**Behavior:**
1. Read `open-brain/context/sessions/{today}.md`
2. Read current `open-brain/context/STATE.md` and all `~/.claude/projects/.../memory/*.md`
3. Identify durable facts in today's sessions NOT already represented
4. Propose edits (append/replace) to `STATE.md` only — never touches personal layer (that's the weekly curator's job)
5. Enforce 2,500-char cap; consolidate if needed
6. Reports diff: "Added 2 threads, removed 1 resolved, STATE.md now 1,847/2,500 chars (74%)"

### Weekly memory curator (`weekly-memory-curator.md`)

```yaml
name: Weekly Memory Curator
time: '09:00'
days: sun
active: 'true'
model: sonnet
notify: on_finish
description: 'Prune and consolidate ~/.claude/.../memory/ markdown files'
timeout: 10m
retry: '0'
```

**Behavior:**
1. Read all `~/.claude/projects/-home-shu-projects-open-brain/memory/*.md`
2. For each file: check still-relevant entries, merge duplicates, drop stale facts
3. Enforce per-file caps
4. Update `MEMORY.md` index if files were added/removed
5. Report per-file: `{filename}: {N}/{cap} chars ({percent}%) — {delta}`

### What about `nightly-memsearch-index`?

**Skipped.** Open-brain already re-embeds on ingestion; there's no index to rebuild. The original prompt's nightly index step assumed memsearch was installed.

---

## Component 4 — Tier-0/1/2/3 Retrieval Contract

Add this section to project [CLAUDE.md](CLAUDE.md):

```markdown
### Memory Retrieval

When the user asks about past context, conversations, or decisions, escalate
tiers in order. Only escalate if the previous tier didn't answer.

**Tier 0** — already in context (free, instant):
  - `~/.claude/projects/.../memory/MEMORY.md` + supporting files (loaded at start)
  - `context/STATE.md`, `context/DECISIONS.md`

**Tier 1** — `mcp__open-brain__search_memory("query", limit=5)`:
  - Hybrid vector + keyword search across all memory_items
  - Returns top chunks with memory_ids

**Tier 2** — `mcp__open-brain__memory_expand(memory_id)`:
  - Full content of one item + parent RawMemory + 2–3 neighbors
  - Use when a T1 hit looks relevant but the snippet is truncated

**Tier 3** — `mcp__open-brain__get_context("query", limit=20)`:
  - Token-budgeted broad dump (~8,000 tokens max)
  - Last resort, expensive

**Fallback:** "I don't have a record of that. Want me to search the web?"
```

---

## Component 5 — `memory_expand` MCP Tool

### Endpoint

```
GET /v1/memory/{id}/expand
Returns:
  {
    "memory_id": "...",
    "content": "<full MemoryItem.content, untruncated>",
    "raw_text": "<parent RawMemory.raw_text, or null if missing>",
    "neighbors": [
      {"memory_id": "...", "content": "<snippet>", "created_at": "...", "source": "..."},
      ...up to 3 by recency from same source...
    ],
    "metadata": {
      "source": "...",
      "project": "...",
      "tags": [...],
      "importance_score": ...,
      "created_at": "..."
    }
  }
```

### Implementation

- **Route:** new function in [src/api/routes/memory.py](src/api/routes/memory.py)
- **Service:** new function `expand_memory(memory_id)` in [src/api/services/memory_service.py](src/api/services/memory_service.py)
- **Auth:** standard `X-API-Key` middleware (same as `/v1/search`)
- **Rate limit:** `@limiter.limit()` decorator (project convention)
- **Neighbor query:** order by absolute time-delta from the target's `created_at`, filtered to same `source`, excluding the target ID and superseded rows, `LIMIT 3`. Implement via SQLAlchemy expressions (`func.abs(MemoryItem.created_at - target_ts)`) so it works on both Postgres prod and SQLite tests — avoid raw `EXTRACT(EPOCH FROM ...)` which is Postgres-only.
- **404** if `memory_id` not found or `is_superseded = True`

### MCP wrapper

Add tool to [src/mcp_server.py](src/mcp_server.py):

```python
@mcp.tool()
def memory_expand(memory_id: str) -> str:
    """Expand a memory_item: return full content + parent + neighbors."""
    response = httpx.get(
        f"{OPENBRAIN_API_URL}/v1/memory/{memory_id}/expand",
        headers={"X-API-Key": OPENBRAIN_API_KEY},
    )
    response.raise_for_status()
    return format_expand_result(response.json())
```

### Tests

- Unit: `expand_memory()` returns full content + neighbors
- Integration: `GET /v1/memory/{id}/expand` returns 404 for missing/superseded
- MCP: tool returns formatted markdown

---

## Portability

The project is **mostly cloud already**. Backend (FastAPI + worker + Postgres + web) runs on the GCP VM at `0xpai.com` — both machines hit the same backend, no porting needed.

**Per-machine setup is minimized:** new PC requires only 5 steps, documented at `docs/setup-new-machine.md`:

1. `git clone github.com/shu/open-brain ~/projects/open-brain`
2. `ln -s ~/projects/open-brain/scripts/claude-code/session-end-ingest.sh ~/.claude/hooks/session-end-ingest.sh`
3. Create `~/.claude/openbrain.env`:
   ```
   OPENBRAIN_API_URL=https://0xpai.com
   OPENBRAIN_API_KEY=<from 1Password>
   ```
4. Add MCP server entry to `~/.claude/settings.json` (or `claude mcp add open-brain ...`)
5. Add SessionEnd hook entry to `~/.claude/settings.json`:
   ```json
   {"hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": "bash ~/.claude/hooks/session-end-ingest.sh"}]}]}}
   ```

**What's version-controlled vs. per-machine:**

| Thing | Version-controlled? | Why |
|---|---|---|
| SessionEnd hook script | ✅ Yes (in repo) | Fixes propagate via `git pull`; identical on all machines |
| Repo→project mapping | ✅ Yes (in script) | Add a project once, available on all machines |
| `context/STATE.md`, `DECISIONS.md` | ✅ Yes (in repo) | Travels with the codebase |
| `context/sessions/{date}.md` | ❌ No (gitignored) | High churn, low durable value |
| `~/.claude/openbrain.env` | ❌ No (per-machine) | Contains API key |
| `~/.claude/projects/.../memory/*.md` | ❌ No (per-machine) | Accept divergence — vector DB is the cross-machine source of truth |

**Why we don't sync the personal markdown layer across machines:** the vector DB already syncs (it's cloud). Letting the personal markdown layer diverge per machine is a feature, not a bug — it creates a natural privacy boundary (work PC ≠ home PC), avoids merge conflicts, and the cross-machine memory you actually need is already in `memory_items` accessible via `search_memory`.

---

## Out of Scope (v1)

The following were considered and explicitly excluded:

- **Per-turn Stop hook with transcript capture.** Original prompt's design; rejected as noisy and orthogonal to the SessionEnd capture path. Raw transcripts have low signal-to-noise; structured summaries don't.
- **Haiku-inferred project labels for free-text ingestions.** Discussed at length. Deferred — deterministic mapping covers the SessionEnd case; web UI has a dropdown; iOS voice command is a separate conversation. Risk of confident wrong answers polluting work-vs-personal split.
- **`context/USER.md` separate from `~/.claude/.../user_profile.md`.** The personal layer already covers this. Keeping one file per role rather than splitting personal vs. project-bound user profile.
- **Memsearch installation.** Open-brain's hybrid search + Voyage embeddings + pgvector already exceed memsearch's capabilities.
- **Per-machine git-synced markdown layer.** Considered for portability; rejected (see Portability section).
- **`memory_remove` / `memory_replace` MCP tools.** Existing supersede semantics + manual file edits cover this. Adding API-level mutation tools is a separate decision.
- **Auto-updating `MEMORY.md` index from supporting files.** Weekly curator handles this.

---

## Verification Plan

End-to-end test once implemented:

1. **SessionEnd hook fires.** In a Claude Code session in `~/projects/open-brain`, exit normally. Within 30 seconds:
   - `tail /tmp/ob-session-end.log` shows success
   - `context/sessions/{today}.md` has a new entry
   - `GET /v1/memory?source=claude-code-session&limit=1` returns the new row with `project="open-brain"`
2. **Repo→project mapping works.** Repeat from a different repo (e.g. `~/projects/egle-climbing` if it exists, or a test repo with `case` entry). Verify the `project` field on the new memory_item.
3. **Trivial session is skipped.** Start a Claude Code session, do one trivial action (`ls`), exit. Verify no new memory_item, no session file entry.
4. **`memory_expand` returns full content + neighbors.**
   - `mcp__open-brain__search_memory("query")` → grab a `memory_id`
   - `mcp__open-brain__memory_expand(memory_id)` → returns full content + neighbors
   - Confirm 404 for invalid ID
5. **Daily curator runs and updates STATE.md.** Trigger manually via the `/schedule` skill (list, then run the job by name). Verify `STATE.md` updated, cap respected.
6. **Weekly curator runs and reports per-file usage.** Trigger manually via `/schedule` the same way; verify the per-file `{N}/{cap} chars ({percent}%) — {delta}` report.
7. **Tier-0 free recall works.** New session, ask "what's our prod domain?" — answer comes from in-context `ops_deployment.md`, no MCP call made.
8. **Tier-1 search works.** Ask about a session from a week ago — `search_memory` returns it.
9. **Cap enforcement.** Manually fill `STATE.md` to 2,400 chars, run daily curator with a long session — verify it consolidates rather than overflows.
10. **Multi-machine setup.** Follow `docs/setup-new-machine.md` on the work PC. Verify SessionEnd captures land in the same backend.

---

## Critical Files

**To create:**
- `scripts/claude-code/session-end-ingest.sh` — the hook
- `docs/setup-new-machine.md` — multi-machine setup memo
- `context/STATE.md` — initial empty template with section headers
- `context/DECISIONS.md` — initial empty template with section headers
- `cron/jobs/daily-memory-distill.md`
- `cron/jobs/weekly-memory-curator.md`

**To modify:**
- [src/pipeline/constants.py](src/pipeline/constants.py) — add `"claude-code-session"` to `AUTO_CAPTURE_SOURCES`
- [src/api/routes/memory.py](src/api/routes/memory.py) — add `GET /v1/memory/{id}/expand`
- [src/api/services/memory_service.py](src/api/services/memory_service.py) — add `expand_memory()`
- [src/mcp_server.py](src/mcp_server.py) — register `memory_expand` MCP tool
- [CLAUDE.md](CLAUDE.md) — add Session Context, Memory Retrieval sections
- [.gitignore](.gitignore) — add `context/sessions/`

**To NOT modify:**
- `~/.claude/projects/-home-shu-projects-open-brain/memory/*.md` — weekly curator owns these
- Existing `/ingest` skill — stays as manual override

---

## Open Implementation Questions

These are flagged for the implementation plan, not blockers for the spec:

1. **Where is the Claude Code session JSONL transcript located on disk?** The hook needs to read it. Likely `$CLAUDE_PROJECT_DIR/.claude/sessions/<session_id>.jsonl` or a system path. Confirm during planning.
2. **How does the hook receive the session_id?** Via env var or hook payload. Confirm.
3. **What's the per-call Haiku token budget for summarization?** A long session transcript could exceed Haiku's input context. Plan needs a truncation strategy (last N turns? assistant-only? sampling?).
4. **Should the daily curator also update the personal layer when a session reveals a long-term user preference?** Currently scoped to STATE.md only. Could be a follow-up.

---

## Success Criteria

- One Haiku summary per session lands in both `context/sessions/` and `memory_items` within 30s of session end
- New machine setup completes in under 10 minutes following `docs/setup-new-machine.md`
- `STATE.md` stays under 2,500 chars indefinitely (curator enforces)
- `MEMORY.md` index stays under 200 lines and is consolidated weekly
- `memory_expand` reduces token spend on "tell me more about X" follow-ups vs. re-searching
- After one month: querying "what did I work on around <date>" via tier 0/1/2/3 returns useful results without manual `/ingest` invocations
