# Voice Command Endpoint — Multi-Agent

You will work through this task in six roles, sequentially. Do not skip ahead.
Review roles (5 and 6) may loop back for fixes, up to 2 cycles each.
The goal: a single `POST /v1/voice/command` endpoint that routes dictated iOS-Shortcut text into one of three explicit intents — create todo, complete todo, or save memory — and returns a structured response describing exactly what happened so the Shortcut can surface it as a notification.

---

## Business context (read once, then put on your shelf)

Open-brain is Shu's personal second-brain: a FastAPI backend with a web dashboard, Discord bot, and iOS Shortcut capture, all feeding a shared Postgres memory store. Today the iOS Back-Tap Shortcut is the fastest input channel, but it only knows how to hit `POST /v1/memory`, so every dictated note lands as a casual memory — you cannot create a todo or close a todo from the phone without opening the dashboard or typing a Discord command. This task adds a second endpoint that lets one gesture reach all three capture modes, routed by explicit spoken keywords (no heuristic guessing) so mutations are predictable and mistakes are recoverable. Latency must stay under Siri's attention span (< 2s), and the LLM layer must stay on Haiku to keep per-call cost negligible.

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- `POST /v1/memory` route in [src/api/routes/memory.py](src/api/routes/memory.py): `MemoryCreate`/`MemoryResponse` schemas, content-hash dedup, `RawMemory` + `RefinementQueue` insert path, and its `@limiter.limit(memory_limit)` decorator.
- `POST /v1/todos` and `PATCH /v1/todos/{id}` in [src/api/routes/todos.py](src/api/routes/todos.py) and the underlying [src/api/services/todo_service.py](src/api/services/todo_service.py) — especially `create_todo`, `update_todo`, the `_snapshot` helper, and how `TodoHistory` rows are written atomically with event_type determination (`completed` vs `updated`).
- [src/pipeline/todo_sync.py](src/pipeline/todo_sync.py) `sync_todo_to_memory` and the `_try_sync` best-effort wrapper in todo_service — so the new endpoint reuses the same service functions and inherits memory sync for free.
- [src/llm/client.py](src/llm/client.py) `AnthropicClient.complete(system_prompt, user_content, max_tokens)` and the module-level `anthropic_client` singleton; confirm Haiku is the default via `settings.anthropic_model`. Read [src/llm/prompts.py](src/llm/prompts.py) to see the `<user_input>…</user_input>` wrapping convention.
- [src/api/middleware/rate_limit.py](src/api/middleware/rate_limit.py) `memory_limit` / `todos_limit` callables and settings in [src/core/config.py](src/core/config.py) (`rate_limit_memory_per_minute`, etc.).
- [src/api/middleware/auth.py](src/api/middleware/auth.py) `APIKeyMiddleware` so you know the new endpoint will already be authenticated.
- [src/core/models.py](src/core/models.py) `TodoItem` (lines ~389–418), `TodoHistory` (lines ~421–442), and `RawMemory` — no schema changes are allowed, so you need these shapes exactly.
- Existing shortcut docs at [docs/voice-ios-shortcut.md](docs/voice-ios-shortcut.md) and any test patterns in `tests/api/` for memory + todo routes.

Also trace for each item:
- Where it is created
- Where it is mutated
- Where it is consumed
- Any related tests

Map the data flow end-to-end: Shortcut → `/v1/voice/command` → intent classifier → (create todo | match+complete todo | ingest memory) → response → iOS notification.

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
- **Keyword routing is sufficient.** Does "remind me to close the fridge" actually start with a create trigger, or does the word "close" pull it into completion? Are the trigger word lists mutually exclusive, or can a single dictation legitimately match two intents? Is whitespace/punctuation/casing normalized before matching?
- **Fuzzy matching on open todos is safe.** What's the distribution of open-todo counts and description lengths in practice — can a single low-quality match beat the confidence floor? Is there a canonical fuzzy-match helper already, or are we about to invent one? Does `rapidfuzz`/`difflib` match the latency budget when open todos are in the hundreds?
- **Haiku can extract description + optional due date within budget.** Real round-trip latency of `AnthropicClient.complete` on Haiku — is `< 2s total` realistic once you add DB queries, fuzzy match, and TodoHistory write? What happens on Haiku timeout — do we fall back to memory, or fail loudly?
- **Reusing `create_todo` / `update_todo` services is free.** Do those functions require a caller that already holds a session and commits? Do they fire `_try_sync` synchronously on the request path, and does that blow the latency budget?
- **`RawMemory.source` of "voice_command" is harmless.** Does `AUTO_CAPTURE_SOURCES` / `TASK_SKIP_SOURCES` in [src/pipeline/constants.py](src/pipeline/constants.py) need updating so the memory-intent path behaves identically to today's `source="voice"` path? Does any dashboard filter key off the source string?
- **Rate limiter reuse.** Is `@limiter.limit(memory_limit)` the right choice when this endpoint can also mutate todos? Should there be a distinct `voice_limit` setting, and what happens to existing config if we add one?
- **Completion history fidelity.** Does the existing `update_todo` path already write a `TodoHistory` row with enough context to audit a wrong voice completion, or do we need to stash the original dictation + confidence score in `reason` / `new_value` metadata?

Additionally challenge:
- Hidden dependencies or coupling
- Data shape assumptions
- Edge cases: empty dictation, dictation that's only a trigger word, multiple open todos with identical titles, todos whose descriptions are long sentences, non-English dictation
- Backward compatibility with the current `/v1/memory` iOS shortcut (it must keep working unchanged)
- Missing or weak test coverage for intent routing and ambiguous-match no-op

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

1. **Intent classifier — keyword-first, LLM-second** — Define the exact regex / token rules for the three intents. Create triggers: dictation starts with `todo`, `task`, `remind me to`, or `create a todo`. Complete triggers: contains a completion verb (`close`, `complete`, `done`, `finish`, `mark done`) **and** a noun phrase referring to a todo (the spec requires a confirmation verb, so bare references never complete). Everything else → memory. Decide whether keyword detection runs in Python only, or whether Haiku is only invoked *after* an intent is already locked in, to extract structured fields (description + due date for create, target phrase for complete). This matters because it keeps the non-LLM path fast and deterministic and confines Haiku to field extraction, not routing.
2. **Fuzzy matching strategy for completion** — Pick the library (`rapidfuzz` is already likely available; fall back to stdlib `difflib.SequenceMatcher` only if not), the comparison field (`description` normalized to lowercase, whitespace-collapsed), the score threshold for "confident match" (propose a number and justify it), and the tie-break rule. Decide how to fetch the candidate set (open todos only, bounded `LIMIT`) and the response when no candidate clears the threshold (`action="ambiguous"`, no mutation). Justify the choice against the < 2s latency budget for the realistic case of dozens of open todos.
3. **Endpoint shape and response contract** — New route `POST /v1/voice/command` with inline Pydantic `VoiceCommandRequest` (text, source default `"voice"`, optional metadata) and `VoiceCommandResponse` with fields the Shortcut can render directly: `action` (`"created" | "completed" | "memory" | "ambiguous"`), `entity_id` (todo id or raw_memory id), `title` (matched or created todo description, or `null` for memory), `confidence` (float, 0–1), `message` (human-readable notification string pre-baked server-side so the Shortcut just displays it verbatim). Decide status codes (202 for memory to match current behavior, 200 for todo actions, 200 with `action="ambiguous"` and no mutation).
4. **Reuse vs duplication** — Call the existing service functions: `todo_service.create_todo`, `todo_service.update_todo`, and the memory-ingest helper currently inside the `/v1/memory` route (extract it into a reusable helper in `src/api/services/memory_service.py` only if it isn't already one — prefer reuse over copy-paste). Confirm `_try_sync` runs in the right place and latency budget. Make sure `TodoHistory` capture for voice completions stashes the original dictation and confidence in `reason` so a wrong close is auditable.
5. **Rate limiting, auth, config** — Reuse `@limiter.limit(memory_limit)` unless Role 2 surfaced a reason not to. Confirm `APIKeyMiddleware` already covers `/v1/*`. Decide whether to add a `voice_command_llm_timeout_seconds` setting (Haiku field-extraction budget, e.g. 1.5s) with a sane default.
6. **What stays unchanged**
   - `POST /v1/memory` — existing iOS Shortcut keeps working byte-identical.
   - `todo_items`, `raw_memory`, `todo_history` schemas — zero migrations.
   - `todo_service.create_todo` / `update_todo` signatures — the new endpoint calls them, does not modify them.
   - `anthropic_client` singleton and the Haiku model selection.
   - `<user_input>…</user_input>` prompt-injection wrapping convention.

7. **Constraints & Safety**
   - End-to-end latency comfortably < 2s, dominated by Haiku field extraction; keyword routing + fuzzy match stays in the low milliseconds.
   - Per-call cost pinned to Haiku; do not fall back to Opus/Sonnet on any path.
   - Ambiguous completion must be a true no-op: no TodoHistory row, no memory side-effects, no partial writes.
   - Silent mis-classification is the worst failure mode — every mutating path must return a `message` that names the exact todo title so the user catches errors in the notification.
   - Rollback: endpoint is additive and purely routes to existing services; rollback = delete the route file + router include.
   - Failure handling: Haiku timeout on the create path → fall back to raw dictation as the description; Haiku timeout on the complete path → treat as low confidence → `ambiguous`. Never fall through silently to memory.

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
1. **Intent classifier module** — Pure Python, no I/O. `src/api/services/voice_intent.py` (or similar) with `classify_intent(text) -> Literal["create", "complete", "memory"]` and trigger constants. Unit test it against a matrix of spoken phrases including edge cases from Role 2 (e.g. "remind me to close the fridge" → create, "close the fridge todo" → complete).
2. **Fuzzy matcher** — Add `match_open_todo(session, target_phrase) -> (todo | None, score)` using the chosen library. Unit test with synthetic open-todo fixtures covering: confident single match, tie between two similar todos → returns ambiguous, empty open-todo set.
3. **Haiku field extractor** — Thin wrapper calling `anthropic_client.complete` with a tight system prompt that returns JSON `{description, due_date}` for create intent and `{target_phrase}` for complete intent. Wrap dictation in `<user_input>…</user_input>`. Enforce `max_tokens` small (e.g. 256) and a timeout ≤ 1.5s via `asyncio.wait_for`. Unit test with mocked Anthropic responses including malformed JSON → fall back gracefully.
4. **Memory-service extraction (only if needed)** — If the `/v1/memory` route still inlines its ingest logic, extract the dedup + RawMemory + RefinementQueue insert into `memory_service.ingest_memory(...)` and have both routes call it. Do not change behavior.
5. **New route `POST /v1/voice/command`** — Wire classifier → extractor → action dispatch → response builder. Reuse `todo_service.create_todo` and `todo_service.update_todo(status="done", reason=<dictation + confidence>)`. Build the human-readable `message` server-side. Apply `@limiter.limit(memory_limit)` and include the router in the app.
6. **Tests** — Route-level tests for all four actions (`created`, `completed`, `memory`, `ambiguous`), rate-limiter test (inherit existing pattern), auth test, and an end-to-end test asserting that a completion writes a `TodoHistory` row whose `reason` contains the dictation text.

After each step:
- Run the existing test suite
- Fix any failures before continuing

After implementation:
- Perform manual verification against a local API (curl examples for all four intents)
- Validate logs show Haiku latency under budget
- Identify any remaining risks or edge cases

Final check:
- Re-read the business context
- Verify the implementation matches the original intent
- Especially validate: **every mutating path returns a `message` string that names the exact todo title affected, and every ambiguous or unparseable completion returns `action="ambiguous"` with zero side effects.**

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
- **Prompt injection via dictation** — Dictated text flows straight into a Haiku prompt. Confirm every call wraps the text in `<user_input>…</user_input>` delimiters and that the system prompt explicitly instructs Haiku to treat anything inside as data, not instructions. A malicious-looking dictation must not be able to exfiltrate other memories or reroute the intent.
- **Unauthorized mutation surface** — The new endpoint can `create` and `complete` todos, which is a stronger capability than the existing `/v1/memory` POST. Confirm `APIKeyMiddleware` covers it, confirm the rate limit is at least as strict as `memory_limit`, and confirm there's no bypass path (e.g. missing router include on the auth middleware's allowlist).
- **Ambiguous-match guarantees** — A low-confidence fuzzy match must be a hard no-op. Verify there is no code path where partial todo state is written before the confidence check fails, and no LLM retry loop that could eventually coerce a match.
- **Audit trail integrity** — Voice completions must leave a `TodoHistory` row that names the original dictation + confidence. Verify `reason` is populated and append-only, so wrong completions are always recoverable from the dashboard.
- **LLM cost exposure** — Confirm Haiku is hard-coded (not taken from a user-controlled request field) and that `max_tokens` is bounded. An attacker who gets hold of the API key should not be able to escalate cost per call.

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
