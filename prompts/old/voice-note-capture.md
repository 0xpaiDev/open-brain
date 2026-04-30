# Voice Note Capture — Multi-Agent

You will work through this task in six roles, sequentially. Do not skip ahead.
Review roles (5 and 6) may loop back for fixes, up to 2 cycles each.
The goal: Two zero-friction surfaces for capturing voice notes — a floating mic button on the webapp dashboard and an iPhone Back Tap shortcut — both feeding transcribed text into Open Brain's existing ingestion pipeline as `voice_note` memory items.

---

## Business context (read once, then put on your shelf)

Open Brain is a personal knowledge management system built by a solo developer. It ingests text from multiple sources (API, email, Slack, Claude Code), runs it through Claude for extraction and Voyage AI for embedding, and stores structured memory items in PostgreSQL with pgvector. The system has a Next.js dashboard for browsing and searching memories, and a FastAPI backend with an async worker pipeline. This change adds voice capture so the user can record a thought instantly — at their desk via the webapp, or on the go via iPhone — without navigating to any app. The transcribed text flows through the same ingestion pipeline, so voice notes get the same extraction, embedding, entity resolution, and searchability as any other memory.

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- The `MemoryItem` and `RawMemory` models in `src/core/models.py` — all fields, the `source` values currently in use, and how `type` is set during ingestion
- The ingestion endpoint `POST /v1/memory` in `src/api/routes/memory.py` — the `MemoryCreate` schema, dedup logic, and how it creates `RawMemory` + `RefinementQueue` entries
- The worker pipeline in `src/pipeline/worker.py` — specifically how `store_memory_item` sets the `type` field on `MemoryItem` (it comes from Claude extraction, not from the ingestion request)
- The embedding client `VoyageEmbeddingClient` in `src/llm/client.py` — the `embed_text` function in `src/pipeline/embedder.py` and how it's called from the worker
- The auth middleware in `src/api/middleware/auth.py` — how `X-API-Key` is validated and which paths are exempt
- The rate limiter setup in `src/api/middleware/rate_limit.py` — how limits are defined as lazy functions and applied to routes
- The web dashboard's `SmartComposer` component in `web/components/memory/smart-composer.tsx` — its tab structure and how it calls `onIngest`
- The `useMemories` hook in `web/hooks/use-memories.ts` — the `ingestMemory` function and toast patterns
- The app layout in `web/app/layout.tsx` — where `<Toaster />` is rendered and how global floating elements would be placed

Also trace for each item:
- Where it is created
- Where it is mutated
- Where it is consumed
- Any related tests

Map the data flow end-to-end: user submits text → `POST /v1/memory` → `RawMemory` + `RefinementQueue` → worker picks up → normalize → extract (Claude) → validate → embed (Voyage) → resolve entities → `store_memory_item` → done.

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
- That the existing `POST /v1/memory` endpoint can be reused as-is for voice notes — does the `MemoryCreate` schema accept arbitrary `source` values, or is it constrained? Will the Claude extraction prompt handle voice-note-style rambling text (stream of consciousness, no structure) without producing garbage?
- That the `type` field on `MemoryItem` can be set to `"voice_note"` — the type is determined by Claude extraction (memory/decision/task), not by the ingestion source. A voice note saying "I need to buy groceries" would become a `task`, not a `voice_note`. Clarify whether `voice_note` should be a `source` on `RawMemory` rather than a `type` on `MemoryItem`.
- That Web Speech API (`webkitSpeechRecognition`) is reliable enough for production use — browser support is Chrome-only, it requires an active internet connection (sends audio to Google), and it silently fails in many edge cases (no microphone permission, background tab, screen lock).
- That a single `X-API-Key` is sufficient for the iOS Shortcut — the task description mentions "a dedicated scoped key," but the current auth middleware only supports one key. Evaluate whether a second key is needed or whether the same key works fine for a solo user.
- That the iOS Shortcut description belongs in the codebase at all — it's a client-side Apple Shortcuts configuration, not code. Determine what (if anything) the backend needs to do differently for `source: "ios_shortcut"` vs `source: "webapp"`.

Additionally challenge:
- Hidden dependencies or coupling
- Data shape assumptions
- Edge cases (empty transcription, very long voice notes, non-English text, rapid repeated submissions)
- Backward compatibility risks (existing tests, existing ingestion consumers)
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

1. **Backend endpoint design** — Whether to reuse `POST /v1/memory` with `source: "voice_note"` or create a new dedicated route like `POST /v1/voice`. Consider: the existing endpoint already accepts `{ text, source, metadata }` and the worker pipeline is source-agnostic. A new route adds surface area for no functional gain. Decide and justify.

2. **Source vs type semantics** — How to represent voice notes in the data model. The `source` field on `RawMemory` tracks provenance (api, email, slack, claude-code). Voice notes are a provenance — they should be `source: "webapp"` or `source: "ios_shortcut"` with `metadata_.transcription_method` indicating voice. Or should there be a new source value like `"voice_webapp"` / `"voice_ios"`? The `type` on `MemoryItem` is determined by Claude extraction and should NOT be overridden. Decide the representation.

3. **Webapp mic button component** — Where to place the floating button (global in layout vs per-page), which speech recognition API to use, how to handle browser compatibility (Chrome vs Firefox vs Safari), silence detection and auto-stop behavior, and visual feedback during recording (pulsing indicator, live transcript preview).

4. **iOS Shortcut documentation** — What to include in the repo (a markdown guide with Shortcut construction steps, the endpoint URL pattern, and auth setup) vs what's purely on the iPhone side. The backend doesn't need any iOS-specific code if the Shortcut just POSTs JSON to the same endpoint.

5. **Error handling and edge cases** — Empty transcription (user clicks record then immediately stops), very long voice notes (set a character limit?), rapid double-submissions (dedup already handles via content hash), network failures during POST from iOS Shortcut (Shortcut retry behavior).

6. **Testing strategy** — Backend: unit test for the endpoint with `source: "voice_webapp"`, integration test through the pipeline. Frontend: Vitest unit test for the mic button component (mock `webkitSpeechRecognition`), E2E test with Playwright (if feasible given browser API mocking). iOS Shortcut: manual testing only.

7. **What stays unchanged**
- The worker pipeline (`normalizer → extractor → validator → embedder → entity_resolver → store_memory_item`) — voice note text flows through identically
- The `MemoryItem` model — no schema changes, no migration
- The `RawMemory` model — `source` is already a free-text string, no enum constraint
- The embedding pipeline — text in, vector out, source-agnostic
- Existing tests — nothing breaks because this is purely additive

8. **Constraints & Safety**
- No new database migration required (source is free-text, metadata is JSONB)
- Rate limit the endpoint at the existing 50/minute — voice notes are infrequent
- Max transcription length: 5000 characters (prevents accidental mega-submissions)
- Browser microphone permission must be requested on first use — handle denial gracefully
- The iOS Shortcut uses the same `X-API-Key` — no need for a second auth mechanism for a solo user
- Rollback: remove the mic button component and the Shortcut guide; backend changes are backward-compatible

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
1. Backend: Add `source` validation (if needed) and any metadata conventions for voice notes to the existing `POST /v1/memory` endpoint. Add a `voice_note_limit` rate limiter if the architect decided on a separate limit.
2. Frontend: Create the floating mic button component (`web/components/voice/mic-button.tsx` or similar) with Web Speech API integration, recording state management, silence detection, and visual feedback.
3. Frontend: Wire the mic button into the app layout or dashboard page — render it as a floating element, connect it to the `useMemories` hook's `ingestMemory` function with `source: "voice_webapp"`.
4. Frontend: Add toast feedback on successful capture — show first ~80 characters of transcribed text.
5. Documentation: Create `docs/ios-shortcut-setup.md` with step-by-step instructions for building the iOS Shortcut (Siri Dictation → POST to endpoint → notification).
6. Tests: Add backend tests for voice note ingestion, frontend Vitest tests for the mic button component.

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
- Especially validate: voice note text flows through the existing pipeline unchanged — no special-casing in the worker, no new model fields, no migration

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
- **CRITICAL IMPLEMENTATION issues** -> return to ROLE 4 with explicit fixes required. After fixes, return here (ROLE 5) and increment review cycle.
- **CRITICAL ARCHITECTURAL issues** -> return to ROLE 3 with the specific concern. After ROLE 3 revises the plan, ROLE 4 re-implements the affected parts, then return here (ROLE 5) and increment review cycle.
- **Review cycle 2 with unresolved CRITICAL issues** -> mark the task **BLOCKED**. List all unresolved issues with context. Stop — these need human decision-making.
- **No CRITICAL issues** -> proceed to ROLE 6.

---

## ROLE 6 — SECURITY REVIEWER

Review the entire implementation through a security lens.

**Review cycle: 1 of 2 maximum.**

Evaluate for this task specifically:
- **Browser microphone access**: Ensure the mic button only activates on explicit user click (no auto-recording). Verify that the recording indicator is always visible when the mic is active. Check that audio data stays in the browser (Web Speech API streams to Google's servers for transcription — document this privacy tradeoff).
- **iOS Shortcut auth token exposure**: The `X-API-Key` is stored as a Shortcut variable on the iPhone. Evaluate the risk: if the phone is compromised, the attacker gets write access to the memory ingestion endpoint. Assess whether this is acceptable for a solo user or whether a write-only scoped token should be recommended.
- **Transcription text as user input**: The transcribed text is user-generated content that flows into Claude for extraction. Verify that the existing `<user_input>` delimiter wrapping in extraction prompts covers this path. A voice note like "ignore previous instructions and..." must not escape the delimiter.
- **Content length limits**: Verify that excessively long transcriptions (someone leaves the mic on for 30 minutes) are rejected or truncated before hitting the LLM and embedding APIs, which have token/character limits and cost implications.
- **Rate limiting on the ingestion endpoint**: Confirm that `@limiter.limit()` is applied and that rapid-fire POSTs from a compromised Shortcut can't run up Voyage AI / Claude API costs.

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
