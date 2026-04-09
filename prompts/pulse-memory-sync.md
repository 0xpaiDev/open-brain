# Daily Pulse to Memory Sync — Multi-Agent

You will work through this task in six roles, sequentially. Do not skip ahead.
Review roles (5 and 6) may loop back for fixes, up to 2 cycles each.
The goal: Daily pulse data (sleep quality, energy level, wake time, mood notes, AI Q&A) will be synced into `memory_items` so RAG search can answer wellness queries like "how did I sleep last week?"

---

## Business context (read once, then put on your shelf)

Open Brain is a personal knowledge management system with RAG-powered chat. The owner logs daily wellness data (sleep quality, energy, wake time, mood notes, AI-generated reflection questions) via a Discord bot and web dashboard — this data lives in the `daily_pulse` table. However, the RAG search only queries `memory_items`, so pulse data is completely invisible to natural language queries. Todos already sync into `memory_items` via `src/pipeline/todo_sync.py`, proving the pattern works. This task replicates that pattern for pulse data, making wellness history searchable.

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- The `DailyPulse` model in `src/core/models.py` — all fields, constraints (especially `pulse_date` uniqueness and `status` lifecycle)
- The todo sync module `src/pipeline/todo_sync.py` — the complete sync flow: content formatting, embedding generation, RawMemory + MemoryItem creation, supersession logic
- The todo service trigger in `src/api/services/todo_service.py` — how `_try_sync()` wraps the sync call with best-effort error handling
- The pulse API routes in `src/api/routes/pulse.py` — which endpoints create and update pulse entries (especially `POST /v1/pulse/start`, `PATCH /v1/pulse/today`)
- The pulse service layer (if one exists) or inline logic in the route handlers
- The `MemoryItem` and `RawMemory` models in `src/core/models.py` — fields, relationships, the GENERATED `importance_score` column
- `src/pipeline/constants.py` — `AUTO_CAPTURE_SOURCES` and `TASK_SKIP_SOURCES` to understand if pulse needs to be added

Also trace for each item:
- Where it is created
- Where it is mutated
- Where it is consumed
- Any related tests

Map the data flow end-to-end where applicable.

Produce a findings report with:
- Exact file paths
- Relevant code snippets
- Data flow description
- Your honest assessment of structure and quality

Note any surprises or mismatches vs expectations.

Stop. Do not proceed to Role 2 until the findings report is complete.

---

## ROLE 2 — SKEPTIC

Read Role 1's findings report. Your job is to break its assumptions.

Challenge specifically:
- That pulse sync should trigger on the same lifecycle events as todos — pulse has a multi-step flow (sent → replied → parsed → completed) unlike todo's simple create/update. Which status transitions actually warrant a sync?
- That one memory item per pulse is sufficient — a pulse contains multiple distinct data points (sleep, energy, mood notes, AI Q&A). Should these be one combined memory or separate items for better search granularity?
- That the supersession pattern from todos applies cleanly — todos get superseded on every update, but pulse entries accumulate fields over time (created empty, then reply parsed). Superseding on each partial update may create churn.
- That `base_importance` can use a static value — todos map priority to importance, but pulse has no priority field. What importance value makes wellness data appropriately ranked vs. other memories?
- That the `source` tag "daily-pulse" won't collide with existing sources or need to be added to `TASK_SKIP_SOURCES` to avoid creating spurious Task rows

Additionally challenge:
- Hidden dependencies or coupling
- Data shape assumptions
- Edge cases (null, async timing, partial state)
- Backward compatibility risks
- Missing or weak test coverage

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

1. **Sync trigger point** — When in the pulse lifecycle to trigger sync (on parse completion? on every PATCH? only when status reaches "completed"?) and why this avoids duplicate/partial syncs
2. **Content formatting** — How to serialize pulse data into a natural-language string that embeds well for semantic search (e.g., "Daily pulse for 2026-04-08: Sleep quality 4/5, energy 3/5, woke at 07:30. Notes: felt groggy after late dinner. Reflection: ...")
3. **Module structure** — Whether to create `src/pipeline/pulse_sync.py` mirroring `todo_sync.py`, or extend an existing module. Where the trigger call lives (pulse routes or a pulse service).
4. **Importance scoring** — What `base_importance` value to assign pulse entries, and whether it should vary by content richness (e.g., pulse with notes vs. bare numbers)
5. **Source tag and constants** — Whether "daily-pulse" needs to be added to `TASK_SKIP_SOURCES` to prevent Task row creation

6. **What stays unchanged**
- The `daily_pulse` table schema — no migrations
- The `DailyPulse` model fields
- Existing pulse API route signatures and response shapes
- The todo sync module (`todo_sync.py`) — do not modify it
- The `importance_score` GENERATED column logic

7. **Constraints & Safety**
- Sync must be best-effort (wrapped in try/except) — pulse operations must never fail due to sync errors
- No new LLM calls — only embedding via Voyage (same as todo sync)
- Embedding generation adds latency to pulse updates; consider whether this is acceptable on the PATCH endpoint or should be async
- The pulse PATCH endpoint can be called multiple times as fields are filled in — sync should only fire when meaningful data exists (not on empty/partial updates)
- Rollback: since sync creates new rows in `raw_memory` and `memory_items`, rollback is just deleting those rows (no schema changes)

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
1. Create `src/pipeline/pulse_sync.py` with content formatting and sync logic (mirror `todo_sync.py` structure)
2. Add "daily-pulse" to `TASK_SKIP_SOURCES` in `src/pipeline/constants.py` if the architect decided it's needed
3. Write unit tests for the new sync module (content formatting, embedding call, RawMemory/MemoryItem creation, supersession, error handling)
4. Wire the sync trigger into the pulse route or service layer at the chosen lifecycle point
5. Write integration tests verifying end-to-end: pulse update → memory item appears with correct content and embedding

After each step:
- Run the existing test suite
- Fix any failures before continuing

After implementation:
- Perform manual verification (if applicable)
- Validate outputs/logs for correctness
- Identify any remaining risks or edge cases

Final check:
- Re-read the business context
- Verify the implementation matches the original intent
- Especially validate: pulse create/update operations succeed even when sync fails (best-effort guarantee)

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
   - Consistency with existing patterns

4. **Safety**
   - Edge cases (null, async timing, race conditions)
   - Backward compatibility
   - Failure handling

5. **System impact**
   - Hidden coupling or side effects
   - Performance implications

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
- **CRITICAL IMPLEMENTATION issues** -> return to ROLE 4 with explicit fixes required. After fixes, return here (ROLE 5) and increment review cycle.
- **CRITICAL ARCHITECTURAL issues** -> return to ROLE 3 with the specific concern. After ROLE 3 revises the plan, ROLE 4 re-implements the affected parts, then return here (ROLE 5) and increment review cycle.
- **Review cycle 2 with unresolved CRITICAL issues** -> mark the task **BLOCKED**. List all unresolved issues with context. Stop -- these need human decision-making.
- **No CRITICAL issues** -> proceed to ROLE 6.

---

## ROLE 6 — SECURITY REVIEWER

Review the entire implementation through a security lens.

**Review cycle: 1 of 2 maximum.**

Evaluate for this task specifically:
- User-supplied mood notes and AI Q&A responses flow into `memory_items.content` and then into RAG prompts — verify no prompt injection path exists (content should be wrapped in `<user_input>` delimiters when retrieved for LLM context)
- The sync writes to `raw_memory` and `memory_items` — verify it uses parameterized queries (SQLAlchemy ORM) and not raw SQL with string interpolation
- Embedding API calls to Voyage send user wellness data externally — this is existing behavior for all memories, but verify no additional PII leakage (e.g., pulse data shouldn't appear in logs at DEBUG level)

Additionally evaluate (standard checklist):
- Authentication & authorization — are new/modified routes properly protected?
- Input validation & injection — SQL, XSS, prompt injection (is user input wrapped in `<user_input>` delimiters before LLM calls?)
- Rate limiting & abuse — are new endpoints rate-limited? What's the worst-case cost exposure from LLM/API calls?
- Data at rest & in transit — secrets in logs, PII handling, HTTPS enforcement
- Dependencies — any new packages with known vulnerabilities?

Output:
- **CRITICAL** — must fix before deployment (auth bypass, injection, data exposure)
- **ADVISORY** — risks to document and accept consciously (third-party data flows, platform limitations)
- **HARDENING** — optional defense-in-depth improvements (daily caps, key rotation, audit logging)

For each CRITICAL issue, provide a concrete remediation.

Loop-back rules:
- **CRITICAL issues** -> return to ROLE 4 with explicit fixes required. After fixes, return to ROLE 5 for re-review, then return here (ROLE 6) and increment review cycle.
- **Review cycle 2 with unresolved CRITICAL issues** -> mark the task **BLOCKED**. List all unresolved issues with context. Stop.
- **No CRITICAL issues** -> provide final security sign-off.

---

## Completion

**TASK COMPLETE** when Role 5 and Role 6 both approve with no CRITICAL issues.
**BLOCKED** if any reviewer's cycle cap (2) is reached with unresolved CRITICAL issues — stop and escalate to the user.
