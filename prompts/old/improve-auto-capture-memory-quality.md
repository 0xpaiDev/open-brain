# Replace Auto-Capture Stop Hook with Intentional /ingest Skill — Multi-Agent

You will work through this task in six roles, sequentially. Do not skip ahead.
Review roles (5 and 6) may loop back for fixes, up to 2 cycles each.
The goal: Remove the automatic stop hook that captures every Claude Code session, and replace it with an `/ingest` skill that the user explicitly invokes when a session is worth remembering — producing dramatically higher-quality memories with zero noise.

---

## Business context (read once, then put on your shelf)

Open Brain is a personal knowledge management system with RAG-based retrieval. Currently, a Claude Code stop hook (`scripts/capture_claude_code.py`) automatically captures every session transcript and ingests it into the memory pipeline. The problem: most sessions are routine (file reads, test runs, quick fixes) and produce low-quality, noisy memory items that dilute search results. The extraction LLM wastes tokens processing tool output, and the importance ceiling (0.4) means auto-captured memories rarely surface anyway. The user wants to replace this fire-and-forget approach with intentional capture: a `/ingest` skill they invoke only when a session contains decisions, discoveries, or outcomes worth remembering. This gives the user control over what enters their memory system and eliminates noise at the source.

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- The stop hook configuration in `~/.claude/settings.json` — the hooks.Stop entry that invokes `capture_claude_code.py`
- The capture script at `scripts/capture_claude_code.py` — understand `_extract_content()`, `_read_transcript()`, `_post_transcript()`, and the stdin JSON payload format (session_id, transcript_path, stop_hook_active)
- The existing skill definitions in `.claude/skills/` — understand the pattern: how skills are defined (frontmatter, description, trigger conditions), how they access conversation context, and how they invoke tools. Pay special attention to `/endsession` as the closest analog.
- The MCP server at `src/mcp_server.py` — the `ingest_memory` tool implementation and how it POSTs to `/v1/memory`
- The `/v1/memory` POST endpoint in `src/api/routes/memory.py` — the `MemoryCreate` schema (text, source, metadata, supersedes_id), the SHA-256 dedup logic, and the 50,000 char limit
- The pipeline constants at `src/pipeline/constants.py` — `AUTO_CAPTURE_SOURCES` and how they affect importance capping and task extraction gating in `src/pipeline/worker.py`
- The extraction prompts at `src/llm/prompts.py` — understand the current generic extraction prompt
- The existing tests at `tests/test_capture_claude_code.py`

Also trace:
- How Claude Code makes the transcript path available to hooks (stdin JSON payload)
- Whether a skill can access the same transcript_path or session context
- How the `/endsession` skill currently works — does it read files, call MCP tools, or use bash?

Produce a findings report with:
- Exact file paths and relevant code snippets
- The skill definition format and conventions
- How a skill can access the current session's transcript
- Your honest assessment of what can be reused vs. what needs to be built fresh

Note any surprises. Especially: can a skill running mid-session access the JSONL transcript, or is it only finalized at session end?

Stop. Do not proceed to Role 2 until the findings report is complete.

---

## ROLE 2 — SKEPTIC

Read Role 1's findings report. Your job is to break its assumptions.

Challenge specifically:
- Can a skill actually access the session transcript? Skills run as expanded prompts within the conversation — they may not have access to the raw JSONL transcript path. If not, the skill would need to summarize from conversation context rather than reading the transcript file. This fundamentally changes the approach.
- If the skill runs mid-conversation (not at session end), is the JSONL transcript complete up to that point, or only finalized when the session closes? The skill might be reading a partial/stale transcript.
- The user might want to call `/ingest` multiple times in a long session (after different significant events). Does the SHA-256 dedup cause problems if the transcript grows between calls? Each call would have different content, so probably fine — but verify.
- Removing the stop hook means zero automatic capture. If the user forgets to `/ingest` for weeks, they lose all that context. Is there a middle ground (e.g., keep the hook but have it only log metadata, not full transcripts)?
- Even with summarized content, the extraction LLM might create `open` Task rows for work that was already completed in the session. Verify that the `TASK_SKIP_SOURCES` constant properly gates task creation for `claude-code-manual` source while allowing full importance scoring.
- The `/endsession` skill already updates CLAUDE.md/PROGRESS.md/etc. Should `/ingest` be integrated into `/endsession` as an optional step, or kept separate? What's the user's workflow?
- If the skill uses a Haiku call to summarize, that's an LLM call within the skill execution. Does this conflict with any constraints? (Skills run within Claude Code, so this would be an inner API call.)

Additionally challenge:
- Hidden dependencies or coupling (other tools/scripts that depend on the stop hook existing)
- Edge cases (empty conversation, conversation with only tool output, very short sessions)
- What happens to the `AUTO_CAPTURE_SOURCES` config and importance capping logic — dead code?
- Test coverage for the new skill

For each challenge, label:
CONFIRMED | REVISED | UNKNOWN

For anything REVISED or UNKNOWN:
- Revisit the codebase
- Update findings with corrected understanding

Stop. Present the reconciled findings before Role 3 begins.

---

## ROLE 3 — SENIOR ARCHITECT

Read the reconciled findings. Design the implementation. Do not write code yet.

Produce a concrete implementation plan covering:

1. **Skill definition** — Design the `/ingest` skill file (`.claude/skills/ingest.md` or similar). Define: trigger phrases, description, what the skill prompt instructs Claude to do. Decide whether the skill reads the JSONL transcript directly (if accessible) or summarizes from conversation context (if transcript isn't available mid-session). Define the argument format: `/ingest` (no args = auto-summarize), `/ingest decided to use pgvector for embeddings` (args = user-provided summary used as-is or as guidance for summarization).

2. **Ingestion mechanism** — How the skill sends content to Open Brain. Options: (a) call the `ingest_memory` MCP tool directly, (b) use bash to POST to the API, (c) invoke `capture_claude_code.py` with modified args. Decide which is simplest and most reliable. Define the `source` value (e.g., `"claude-code-manual"` to distinguish from auto-capture) and what metadata to include.

3. **Source treatment and task gating** — `claude-code-manual` must NOT be in `AUTO_CAPTURE_SOURCES` (no importance ceiling). However, task extraction should still be skipped to avoid creating stale `open` Task rows for work already completed in the session. Create a new `TASK_SKIP_SOURCES` constant in `src/pipeline/constants.py` that is `AUTO_CAPTURE_SOURCES | {"claude-code-manual"}`. Change `worker.py` line 396 to use `TASK_SKIP_SOURCES` instead of `AUTO_CAPTURE_SOURCES` for the task gating check. The importance capping check (line 201) stays on `AUTO_CAPTURE_SOURCES`. This gives: full importance + full entity/decision extraction + no stale tasks.

4. **Stop hook removal** — How to cleanly remove the auto-capture: remove the hooks.Stop entry from `~/.claude/settings.json` guidance, decide whether to delete `scripts/capture_claude_code.py` or keep it as a manual tool, update the memory file (`config_auto_capture.md`).

5. **Content quality** — If the skill summarizes from conversation context: design the summarization approach. The skill prompt should instruct Claude to extract key decisions, discoveries, architectural choices, bugs found/fixed, and outcomes — then format this as a concise memory-ready text block before ingesting. If the user provides args, use those as the core content (perhaps enriched with conversation context). Define a maximum content length to stay within the 50,000 char API limit.

6. **What stays unchanged**
- The `/v1/memory` POST endpoint and `MemoryCreate` schema
- The worker pipeline (normalize → extract → validate → embed → store)
- The `ingest_memory` MCP tool
- The SHA-256 content-hash dedup
- The `AUTO_CAPTURE_SOURCES` frozenset (just won't match the new source)
- The `/endsession` skill (kept separate — different purpose)

7. **Constraints & Safety**
- The skill must work within Claude Code's skill execution model (expanded prompt, not a subprocess)
- No new Python dependencies
- The ingested content must still be wrapped in `<user_input>` delimiters by the extraction prompt (existing behavior, just verify)
- If using MCP tool: verify the MCP server is typically available during Claude Code sessions
- Rollback: re-adding the stop hook is trivial if the user wants auto-capture back

For each decision:
- Provide reasoning
- If multiple approaches exist, list them and justify the chosen one

Stop. Present the plan. Do not implement until Role 4 begins.

If recalled by Role 5 for an architectural revision:
- Read the specific concern raised
- Update only the affected sections of the plan
- Note what changed and why
- Return to Role 4 to re-implement the affected parts

---

## ROLE 4 — IMPLEMENTER

Read the architect's plan. Implement it exactly as specified.

Work in this order:
1. **Create the `/ingest` skill definition** — Write the skill file following existing skill conventions discovered in Role 1. Include trigger phrases, description, and the full skill prompt that instructs Claude to summarize the session and ingest it.
2. **Test the skill manually** — Verify the skill can be invoked and produces reasonable output. If it uses the MCP `ingest_memory` tool, verify connectivity.
3. **Remove the stop hook** — Remove the hooks.Stop entry from settings.json documentation/guidance. Decide on `capture_claude_code.py` disposition (keep as utility or remove). Update the auto-capture memory file.
4. **Update tests** — If `capture_claude_code.py` is kept, tests stay. If removed, clean up `tests/test_capture_claude_code.py`. Add any tests for new functionality if applicable.
5. **Documentation** — Update CLAUDE.md if the auto-capture architecture decision needs revision. Update the memory index if `config_auto_capture.md` changes.

After each step:
- Run the existing test suite
- Fix any failures before continuing

After implementation:
- Perform manual verification: invoke `/ingest` in a test conversation
- Verify the memory appears in the pipeline (check `/v1/queue/status` or search for it)
- Verify that stopping a session no longer triggers auto-capture

Final check:
- Re-read the business context
- Verify the implementation matches the original intent
- Especially validate: the user has full control over what gets ingested; no automatic noise enters the memory system; the skill is easy and natural to invoke

Stop. Do not consider the task complete until reviewed.

If recalled by Role 5 or Role 6 for fixes:
- Read the specific issues listed
- Apply fixes to the affected code only
- Do not refactor or change unrelated code
- Summarize what changed and why
- Return to Role 5 for re-review

---

## ROLE 5 — REVIEWER

Review the implementation as if this were a production PR. Be critical and precise.

**Review cycle: 1 of 2 maximum.**

Inputs:
- Architect's plan
- Full diff of changes
- Implementer's summary

Evaluate across:

1. **Correctness**
   - Does the implementation fully satisfy the plan?
   - Any logical errors or missing cases?

2. **Scope adherence**
   - Any unnecessary changes?
   - Anything missing that was explicitly required?

3. **Code quality**
   - Readability, structure, naming
   - Consistency with existing skill patterns

4. **Safety**
   - Edge cases (invoking `/ingest` in an empty conversation, invoking it twice)
   - Backward compatibility (does removing the hook break anything?)
   - Failure handling (what if MCP server is down when skill runs?)

5. **System impact**
   - Is `AUTO_CAPTURE_SOURCES` now partially dead code? Should "claude-code" be removed from it?
   - Are there other references to the stop hook that need updating?

6. **Tests & validation**
   - Are tests sufficient and meaningful?
   - What critical paths are untested?

7. **Skeptic's concerns (cross-reference Role 2)**
   - Review each REVISED and UNKNOWN finding from Role 2
   - Is each concern addressed in the implementation, or consciously accepted with documented rationale?
   - Flag any REVISED/UNKNOWN item that was silently ignored

8. **Plan fidelity (cross-reference Role 3)**
   - Does the implementation match the Architect's plan?
   - Were any deviations from the plan justified and documented by the Implementer?
   - Flag any undocumented deviation as a scope issue

Output:
- List of issues grouped by severity:
  - CRITICAL (must fix before merge)
  - MAJOR (should fix)
  - MINOR (nice to improve)
- Concrete suggested fixes for each CRITICAL and MAJOR issue
- For each CRITICAL, classify as: **IMPLEMENTATION** (code bug) or **ARCHITECTURAL** (design flaw)

Loop-back rules:
- **CRITICAL IMPLEMENTATION issues** → return to ROLE 4 with explicit fixes required. After fixes, return here (ROLE 5) and increment review cycle.
- **CRITICAL ARCHITECTURAL issues** → return to ROLE 3 with the specific concern. After ROLE 3 revises the plan, ROLE 4 re-implements the affected parts, then return here (ROLE 5) and increment review cycle.
- **Review cycle 2 with unresolved CRITICAL issues** → mark the task **BLOCKED**. List all unresolved issues with context. Stop — these need human decision-making.
- **No CRITICAL issues** → proceed to ROLE 6.

---

## ROLE 6 — SECURITY REVIEWER

Review the entire implementation through a security lens.

**Review cycle: 1 of 2 maximum.**

Evaluate for this task specifically:
- The `/ingest` skill sends conversation content to the Open Brain API — does the content pass through `<user_input>` delimiters in the extraction prompt? (It should, via the existing pipeline.)
- If the skill accepts user arguments (`/ingest some text`), could those arguments be used for prompt injection when they reach the extraction LLM? (They're wrapped in `<user_input>` tags by existing code, but verify.)
- Does the new `source` value (`claude-code-manual`) bypass any security checks that `claude-code` had? (It shouldn't — the only difference is importance ceiling and task gating.)

Additionally evaluate (standard checklist):
- Authentication & authorization — does the skill's API call include proper auth (API key)?
- Input validation & injection — SQL, XSS, prompt injection
- Rate limiting & abuse — can `/ingest` be spammed? (Existing endpoint rate limits apply.)
- Data at rest & in transit — secrets in logs, PII handling
- Dependencies — any new packages with known vulnerabilities?

Output:
- **CRITICAL** — must fix before deployment (auth bypass, injection, data exposure)
- **ADVISORY** — risks to document and accept consciously
- **HARDENING** — optional defense-in-depth improvements

For each CRITICAL issue, provide a concrete remediation.

Loop-back rules:
- **CRITICAL issues** → return to ROLE 4 with explicit fixes required. After fixes, return to ROLE 5 for re-review, then return here (ROLE 6) and increment review cycle.
- **Review cycle 2 with unresolved CRITICAL issues** → mark the task **BLOCKED**. List all unresolved issues with context. Stop.
- **No CRITICAL issues** → provide final security sign-off.

---

## Completion

**TASK COMPLETE** when Role 5 and Role 6 both approve with no CRITICAL issues.
**BLOCKED** if any reviewer's cycle cap (2) is reached with unresolved CRITICAL issues — stop and escalate to the user.
