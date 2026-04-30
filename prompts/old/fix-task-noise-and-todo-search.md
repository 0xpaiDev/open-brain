# Fix Task Extraction Noise & Todo Search Visibility — Multi-Agent

You will work through this task in six roles, sequentially. Do not skip ahead.
Review roles (5 and 6) may loop back for fixes, up to 2 cycles each.
The goal: Auto-captured Claude Code sessions no longer create Task rows, and TodoItem data is surfaced in hybrid search and RAG chat responses.

---

## Business context (read once, then put on your shelf)

Open Brain is a personal memory system that ingests text from multiple sources (webapp, voice, MCP, Discord, and auto-captured Claude Code sessions). An async worker pipeline extracts structured data — including Task items — from every ingested memory. The problem: Claude Code session transcripts are noisy development logs, and the Task items extracted from them pollute the task list with irrelevant items like "refactor component" or "fix test." Only memories from intentional sources (webapp, voice, MCP, Discord) should produce tasks. Separately, the system has a first-class TodoItem table for explicit task management, but hybrid search and RAG chat are completely blind to it — asking "what are my todos?" returns nothing because search only queries the memory_items table.

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- The worker pipeline's task extraction and storage logic in `src/pipeline/worker.py` — specifically where `Task` rows are created from extraction results and the existing `source == "claude-code"` importance-capping logic
- The `RawMemory` model in `src/core/models.py` — how the `source` field flows from ingestion to worker processing, and which source values exist (claude-code, api, mcp, discord, voice)
- The `TodoItem` and `TodoHistory` models in `src/core/models.py` — schema, fields, relationships, and notably the absence of an `embedding` column
- The hybrid search implementation in `src/retrieval/search.py` — the `_execute_hybrid_sql()` function and `hybrid_search()` entry point, including how they query only `memory_items`
- The RAG chat endpoint in `src/api/routes/chat.py` — the full pipeline from query formulation through context building to synthesis
- The context builder in `src/retrieval/context_builder.py` — how search results are formatted into token-budgeted context blocks

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
- That simply skipping task extraction for `source == "claude-code"` is safe — are there legitimate tasks in Claude Code sessions that should be captured? Could the source field be unreliable or missing?
- That TodoItem data can be meaningfully embedded and searched — todo descriptions are typically short (5-15 words). Will vector similarity and FTS actually produce useful results, or will they drown in noise?
- That injecting todo results into the existing hybrid search won't degrade memory search quality — mixing two different data types (memories vs todos) in the same ranking pipeline could confuse the scoring
- That the existing `combined_score` formula (0.5 vector + 0.2 keyword + 0.2 importance + 0.1 recency) works for TodoItems which have no `importance_score` or `dynamic_importance`
- That adding todos to search doesn't require a migration — TodoItem has no `embedding` column, no `content` text field for FTS, and no tsvector index

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

1. **Task extraction gating by source** — Where in the worker pipeline to skip task creation for auto-captured sources, how to implement it (config-driven allowlist vs hardcoded check), and whether to use the existing importance-capping pattern as a model
2. **Todo search strategy** — Whether to (a) add an embedding column to TodoItem and include it in hybrid search via UNION, (b) run a separate simple SQL query for todos and merge results in Python, or (c) use a tool/function-call approach where the chat LLM can query todos directly. Consider that todos are short text, frequently changing, and have structured metadata (status, priority, due_date, label) that matters more than semantic similarity
3. **Context builder integration** — How to format todo results alongside memory results in the token-budgeted context block, including how to distinguish them visually for the LLM (e.g., a "TODOS" section vs inline with memories)
4. **Chat system prompt update** — Whether and how to update the RAG system prompt in `src/llm/rag_prompts.py` to teach the LLM about todo data availability and how to present it
5. **Migration requirements** — Whether schema changes are needed (new columns, indexes) or if the approach avoids migrations entirely

5. **What stays unchanged**
- The `RawMemory` → `MemoryItem` pipeline (normalization, extraction, embedding, entity resolution) — no changes to the core ingestion flow
- The `TodoItem` CRUD endpoints and Discord integration — no changes to todo management
- The existing hybrid search ranking formula for memory_items — no regression in memory search quality
- The `memory_items` table schema — no new columns or indexes

6. **Constraints & Safety**
- Performance: todo queries must not add meaningful latency to search/chat (currently ~200ms). A simple SQL query is preferable to embedding + vector search for 10-100 todo rows
- Backward compatibility: existing search API consumers should see no change in response shape for memory results. Todo results should be additive
- Migration plan: if schema changes are needed, they must go through Alembic (never `create_all()`), and the migration must be reversible
- Failure modes: if todo query fails, search/chat should still return memory results (graceful degradation)
- Rollback strategy: task gating can be toggled via config; todo search can be disabled by removing the query without data loss

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
1. Gate task extraction in `src/pipeline/worker.py` — add source check to skip Task row creation for `source == "claude-code"`, following the existing importance-capping pattern nearby
2. Add todo query logic to search — implement the architect's chosen approach (likely a simple SQL query in search.py or a helper function)
3. Integrate todo results into context builder — update `src/retrieval/context_builder.py` to format todo data in the context block
4. Update chat endpoint if needed — modify `src/api/routes/chat.py` to fetch and include todo data in the RAG context
5. Update RAG system prompt if needed — modify `src/llm/rag_prompts.py` to inform the LLM about todo data
6. Write tests — add tests for task gating (verify no Task rows for claude-code source) and todo search visibility (verify todos appear in search/chat context)

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
- Especially validate: auto-captured sessions must NOT create Task rows, and asking "what are my todos?" in chat must return actual TodoItem data

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
   - Edge cases (null, async, race conditions)
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
- **CRITICAL IMPLEMENTATION issues** → return to ROLE 4 with explicit fixes required. After fixes, return here (ROLE 5) and increment review cycle.
- **CRITICAL ARCHITECTURAL issues** → return to ROLE 3 with the specific concern. After ROLE 3 revises the plan, ROLE 4 re-implements the affected parts, then return here (ROLE 5) and increment review cycle.
- **Review cycle 2 with unresolved CRITICAL issues** → mark the task **BLOCKED**. List all unresolved issues with context. Stop — these need human decision-making.
- **No CRITICAL issues** → proceed to ROLE 6.

---

## ROLE 6 — SECURITY REVIEWER

Review the entire implementation through a security lens.

**Review cycle: 1 of 2 maximum.**

Evaluate for this task specifically:
- Todo data injected into RAG context could contain user-controlled text — verify it is properly sanitized or wrapped in delimiters before reaching the LLM (prompt injection via todo descriptions)
- New SQL queries for todo search — verify they use parameterized queries via SQLAlchemy ORM, not raw `text()` with string interpolation
- The task gating logic must not be bypassable — verify the source field cannot be spoofed or omitted by API callers to force task extraction

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
- **CRITICAL issues** → return to ROLE 4 with explicit fixes required. After fixes, return to ROLE 5 for re-review, then return here (ROLE 6) and increment review cycle.
- **Review cycle 2 with unresolved CRITICAL issues** → mark the task **BLOCKED**. List all unresolved issues with context. Stop.
- **No CRITICAL issues** → provide final security sign-off.

---

## Completion

**TASK COMPLETE** when Role 5 and Role 6 both approve with no CRITICAL issues.
**BLOCKED** if any reviewer's cycle cap (2) is reached with unresolved CRITICAL issues — stop and escalate to the user.
