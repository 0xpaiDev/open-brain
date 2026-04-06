# Claude Code Capture: Duplicate Ingestion Analysis

## Current Behavior

### How the Stop Hook Works

The Stop hook (`scripts/capture_claude_code.py`) is configured in `~/.claude/settings.json` and fires **every time Claude finishes a response** — not once per session.

In a 20-turn conversation, the hook fires ~20 times. Each time, it:

1. Reads the **full JSONL transcript** from disk (`_read_transcript`)
2. POSTs the **entire conversation text** to `POST /v1/memory`
3. The pipeline processes it as a new raw memory

### What the Stop Hook Fires On

| Scenario | Fires? |
|----------|--------|
| Claude finishes a response | Yes |
| Claude finishes tool calls | Yes |
| Subagent completes | Yes |
| Context compaction | Yes |
| User presses Ctrl+C | Yes |
| User runs `/clear` | No |
| Terminal/window closes | No |
| API errors | No (fires `StopFailure` instead) |

### Current Dedup: Content-Hash (SHA-256)

`src/api/routes/memory.py` lines 38–41:

```python
def _content_hash(text: str) -> str:
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()
```

Before creating a `raw_memory` row, the route checks for an existing row with the same hash within a 24-hour window. If found, it returns `status="duplicate"` and skips ingestion.

### Why Dedup Doesn't Catch Growing Transcripts

Each time the hook fires, the transcript has grown (new messages appended). The text is different, so the SHA-256 hash is different. The dedup sees each submission as unique content.

**Example — a 5-turn conversation produces 5 pipeline runs:**

| Turn | Transcript Content | Hash | Pipeline Run? |
|------|--------------------|------|---------------|
| 1 | `USER: hello \n ASSISTANT: hi` | `a1b2...` | Yes |
| 2 | Above + `USER: do X \n ASSISTANT: done` | `c3d4...` | Yes |
| 3 | Above + `USER: thanks \n ASSISTANT: np` | `e5f6...` | Yes |
| 4 | Above + ... | `g7h8...` | Yes |
| 5 | Above + ... | `i9j0...` | Yes |

Each run processes an increasingly large superset of the previous one. The LLM extraction runs on nearly identical content 5 times. Only the final run contains the complete conversation.

### Impact

- **Wasted LLM calls**: N extractions for an N-turn conversation, each on overlapping content
- **Wasted pipeline compute**: embedding generation, entity extraction, importance scoring — all repeated
- **Redundant memory items**: the pipeline may extract the same facts multiple times from overlapping transcripts, creating near-duplicate `memory_item` rows that aren't caught by content-hash dedup (different wording from different extraction runs)

## Possible Solutions

### Option A: Client-Side Offset Tracking (Recommended)

Track the last-sent JSONL line number in a temp file per session. Only send new lines since the last capture.

**File**: `scripts/capture_claude_code.py`

```
/tmp/ob-capture-{session_id}.offset  →  stores last line number sent
```

**Pros**: Zero API/pipeline changes. Eliminates redundant POSTs entirely.
**Cons**: Only captures incremental fragments — the pipeline sees individual turns, not full context. May affect extraction quality since the LLM doesn't see the full conversation.

### Option B: Client-Side "Send Only on Final" with Debounce

Instead of sending immediately, write a marker file. Use a short delay or a SessionEnd hook to send only once.

**Problem**: There's no reliable way to know which response is "final" from the Stop hook alone. A timer-based debounce (e.g., skip if another Stop fires within 60s) would delay all captures and still miss edge cases.

**Verdict**: Fragile. Not recommended.

### Option C: API-Side Session Upsert

Modify `POST /v1/memory` to recognize `source=claude-code` + `metadata.session_id` and **replace** (not duplicate) the previous raw_memory for that session.

**Pros**: Pipeline always processes the latest full transcript. No client changes needed.
**Cons**: Violates the `raw_memory` append-only architecture. Previous transcripts would need to be superseded or deleted. Adds complexity to the ingestion route.

### Option D: Worker-Side Session Dedup

Let all N submissions arrive and queue. In the worker, before processing a `refinement_queue` entry, check if a newer entry exists for the same `session_id`. If so, skip the older one.

**Pros**: No API changes. Preserves append-only raw_memory. Only the latest (most complete) transcript gets processed.
**Cons**: N raw_memory rows still created. Requires the worker to query by session_id. Queue entries sit idle until the session ends (or a timeout).

### Option E: Hybrid — Offset Tracking + Final Full Send

Combine Option A with a final full-transcript send. During the session, send nothing (or only incremental deltas). On session end (or after a quiet period), send the complete transcript.

**Pros**: Best of both worlds — minimal waste during session, complete context for extraction.
**Cons**: Most complex. Requires both client and potentially API changes.

## Recommendation

**Option A (offset tracking)** is the simplest fix with the highest impact. It eliminates all redundant POSTs with a ~15-line change to `capture_claude_code.py` and zero backend changes.

If extraction quality suffers from seeing fragments instead of full conversations, upgrade to **Option D (worker-side session dedup)** which lets all submissions arrive but only processes the most complete one.
