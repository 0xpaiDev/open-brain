# Web Voice Unification + Link Tab Removal — Multi-Agent

You will work through this task in six roles, sequentially. Do not skip ahead.
Review roles (5 and 6) may loop back for fixes, up to 2 cycles each.
The goal: the web dashboard's voice capture posts to the same `POST /v1/voice/command` endpoint the iOS Siri shortcut uses, surfaces the endpoint's outcome message, and the SmartComposer tab strip no longer renders a "Link" input tab.

---

## Business context (read once, then put on your shelf)

Open Brain is Shu's personal memory system: a FastAPI + Next.js app where dictated thoughts, todos, and notes are ingested, extracted, and later surfaced via search and a daily pulse. There are two capture surfaces — a web dashboard and an iOS Siri shortcut. The shortcut was recently repointed at a new deterministic voice-command endpoint (`POST /v1/voice/command`) that classifies intent (create todo / complete todo / save memory) via regex before invoking Haiku for field extraction. The web dashboard's mic button still posts dictated transcripts to the older generic `/v1/memory` path, so the two surfaces now behave differently for the same spoken input. This task unifies them so one voice path serves both surfaces. Alongside, the SmartComposer's "Link" input tab is being removed as low-value tab-strip clutter.

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- The SmartComposer component at `web/components/memory/smart-composer.tsx` — understand all four tabs (Text, Link, Media, Voice), the voice submit handler `handleVoiceSubmit`, and how it calls `onIngest`.
- The `useMemories` hook at `web/hooks/use-memories.ts` — specifically `ingestMemory` and how it posts to `/v1/memory` and surfaces toasts.
- The unified voice endpoint at `src/api/routes/voice.py` and its service `src/api/services/voice_intent.py` — capture the request schema, response schema (`VoiceCommandResponse`: action, entity_id, title, confidence, message), status codes (200 vs 202), and the ambiguous/low-confidence behavior.
- The API client at `web/lib/api.ts` and existing type definitions at `web/lib/types.ts` — understand how to add a new typed call.
- The voice tests at `web/__tests__/components/smart-composer-voice.test.tsx`, `web/__tests__/hooks/use-speech-recognition.test.ts`, and `web/__tests__/hooks/use-memories.test.ts`.
- Any Playwright e2e spec touching voice or SmartComposer under `web/e2e/`.

Also trace:
- Where `handleVoiceSubmit` hands off to (`onIngest` prop) and what happens to its return value.
- How duplicate vs success toasts are chosen today and what fields the new endpoint provides instead.
- Whether the Link tab (`value={1}`) is referenced from any test, snapshot, or external component.

Produce a findings report with exact file paths, line numbers, code snippets, and the end-to-end data flow for both (a) the current web voice path and (b) the phone voice path via `/v1/voice/command`. Note any surprises — especially whether the voice transcript today carries `metadata.transcription_method` that the new endpoint may not expect.

Stop. Do not proceed to Role 2 until the findings report is complete.

---

## ROLE 2 — SKEPTIC

Read Role 1's findings report. Your job is to break its assumptions.

Challenge specifically:
- **Response shape mismatch**: does the new endpoint return the same `{raw_id, status}` fields `ingestMemory` currently reads? If not, the toast/refresh logic will break unless handled.
- **Status code handling**: the endpoint returns 202 for the memory action and 200 for create/complete/ambiguous. Does `web/lib/api.ts`'s `api()` helper treat non-200 as an error? Will 202 throw?
- **Ambiguous action**: when `action === "ambiguous"`, the endpoint returns 200 but performs *no mutation*. The web must not show a green success toast in that case — confirm the user's phone UX here and mirror it.
- **List refresh**: `ingestMemory` calls `refresh()` to reload the memory list. Does `/v1/voice/command` with action=`created` or `completed` actually produce a new `memory_items` row immediately, or does it only touch todos/tasks? The memory grid may not update for create/complete actions — verify whether that's a UX regression or acceptable.
- **Request shape**: the existing `ingestMemory` sends `{text, source, metadata}`. The new endpoint may expect `{transcript}` or similar. Confirm the exact field name and strip the stale `source="voice"` / `transcription_method` fields if they are not accepted.
- **Link tab removal coupling**: Tabs use numeric `value={0..3}`. Removing `value={1}` may leave gaps or break `defaultValue={0}` semantics if the Tabs component re-numbers internally — check the `@/components/ui/tabs` contract.
- **Orphan check**: the user asserted "items previously filed under Link must remain reachable." Confirm the Link tab is an *input* affordance only, not a *filter* — and that removing it hides no data.
- **Tests**: which existing Vitest tests mock `/v1/memory` for the voice flow and will fail once the endpoint changes? Which Playwright specs click the Link tab?

For each challenge, label: CONFIRMED | REVISED | UNKNOWN.
For anything REVISED or UNKNOWN: revisit the codebase and update findings.

Stop. Present the reconciled findings before Role 3 begins.

---

## ROLE 3 — SENIOR ARCHITECT

Read the reconciled findings. Design the implementation. Do not write code yet.

Produce a concrete implementation plan covering:

1. **New typed client call** — add a `postVoiceCommand(transcript)` helper (or an inline `api()` call) in `web/lib/api.ts` or `web/hooks/use-memories.ts`. Define `VoiceCommandResponse` in `web/lib/types.ts` mirroring the backend `{action, entity_id, title, confidence, message}`. Decide whether to extend `ingestMemory` with a new branch or add a sibling function `submitVoiceCommand` — prefer a sibling to keep the legacy text/link ingest path untouched.

2. **Web voice submit handler rewrite** — `handleVoiceSubmit` in `smart-composer.tsx` calls the new sibling instead of `onIngest("voice", ...)`. Map the response to toasts:
   - `action === "created"` → success toast with `message` (e.g., `Added todo: "buy milk"`)
   - `action === "completed"` → success toast with `message`
   - `action === "memory"` (202) → success toast with `message`
   - `action === "ambiguous"` → **info or warning** toast using `message`, do not clear the transcript, do not call `refresh()` — mirror phone behavior.
   - Non-2xx → error toast, keep transcript.
   Decide: should the SmartComposer still expose `onIngest` for voice, or bypass it? Recommendation: bypass — wire a new prop `onVoiceCommand` from the parent that returns the response, so the hook owns the fetch and the component owns the UX.

3. **useMemories hook extension** — add `submitVoiceCommand(transcript)` that posts to `/v1/voice/command`, returns the typed response, refreshes the memory list only when `action === "memory"` (since the memory grid is the only surface that reflects a new row), and never throws to the component. Expose it alongside `ingestMemory`.

4. **Link input tab removal** — delete the `TabsTrigger value={1}` and the matching `TabsContent value={1}` (Link form) in `smart-composer.tsx`. Renumber Media (2→1) and Voice (3→2) consistently so `defaultValue` and all `value` props remain a contiguous 0..2 range. Remove the now-unused `url` state, `handleLinkSubmit`, and the `<Input>` import *only if no other tab uses it*.

5. **What stays unchanged**
- `src/api/routes/voice.py`, `src/api/services/voice_intent.py`, or any backend code — zero backend changes.
- The iOS Siri shortcut.
- The Text and Media input tabs and their handlers.
- The `/memory` page sidebar filter list in `web/components/layout/sidebar.tsx`.
- The `ingestMemory` legacy `/v1/memory` path — still used by Text and Media tabs.

6. **Constraints & Safety**
- **Latency**: single fetch, no extra round-trip — confirm no new client-side transformations block the UI thread.
- **Ambiguous / low-confidence behavior**: must match phone — no silent mutations, clear user-visible message, transcript preserved so user can retry.
- **Refresh strategy**: only re-fetch memory list on `action === "memory"`. For todo create/complete, optionally bump a separate todos query if one exists on the same page; otherwise accept that the memory grid won't reflect the todo (it will next hard refresh).
- **Tab renumbering**: verify `@/components/ui/tabs` accepts renumbered values without snapshot drift. If the Tabs primitive keys content by `value`, renumbering is safe; if it keys by index, it is also safe — but audit once.
- **Rollback**: single feature, contained in one component + one hook + one type — revert is a clean `git revert`.

Stop. Present the plan. Do not implement until Role 4 begins.

If recalled by Role 5 for an architectural revision: update only the affected sections of the plan, note what changed and why, and return to Role 4.

---

## ROLE 4 — IMPLEMENTER

Read the architect's plan. Implement it exactly as specified.

Work in this order:
1. Add `VoiceCommandResponse` type to `web/lib/types.ts`.
2. Add `submitVoiceCommand` in `web/hooks/use-memories.ts` and export it alongside `ingestMemory`. Handle the `ambiguous` branch explicitly.
3. Wire `onVoiceCommand` prop through the parent memory page into `SmartComposer`, and update `handleVoiceSubmit` to call it, mapping the typed response to the toast UX. Preserve the existing speech-recognition loop and the transcript-reset-on-success semantics.
4. Delete the Link `TabsTrigger` + `TabsContent`, renumber remaining tabs 0..2, remove now-dead `url` state and `handleLinkSubmit`, and the matching import(s) if fully unused.
5. Update tests:
   - Extend `smart-composer-voice.test.tsx` to mock `onVoiceCommand` and assert the four outcome branches (created / completed / memory / ambiguous) render the endpoint-supplied message.
   - Extend `use-memories.test.ts` with `submitVoiceCommand` happy-path + ambiguous + error cases.
   - Remove any Link-tab assertions from component tests if present; remove Link e2e steps if any.
6. Run `cd web && npm test` and `cd web && npx playwright test` — fix failures.

After each step: run the existing test suite and fix failures before continuing.

Final check:
- Re-read the business context.
- Especially validate: **voice path on web must honor the same low-confidence / ambiguous behavior as the phone path — no silent mutations when intent is unclear**. Manually test by dictating an ambiguous phrase and confirming no todo/memory is created.

Stop. Do not consider the task complete until reviewed.

If recalled by Role 5 or Role 6 for fixes: apply only to the affected code, summarize what changed, and return to Role 5.

---

## ROLE 5 — REVIEWER

Review the implementation as if this were a production PR. Be critical and precise.

**Review cycle: 1 of 2 maximum.**

Inputs:
- Architect's plan
- Full diff of changes
- Implementer's summary

Evaluate across:

1. **Correctness** — implementation fully satisfies the plan; no logical errors; all four `action` values handled.
2. **Scope adherence** — no unrelated refactors; no backend changes; sidebar filters untouched.
3. **Code quality** — readability, naming, consistency with `ingestMemory` patterns.
4. **Safety** — ambiguous path does not clear transcript, does not refresh, does not mutate; 202 status is treated as success, not error.
5. **System impact** — memory-list refresh only fires on `action === "memory"`; no unnecessary renders or fetches.
6. **Tests & validation** — at least one test per `action` branch; error path covered; Link-tab test remnants removed.
7. **Skeptic's concerns (cross-reference Role 2)** — confirm each REVISED / UNKNOWN item is addressed, especially 202 handling and response-shape mapping.
8. **Plan fidelity (cross-reference Role 3)** — flag any silent deviation from the architect's plan.

Output: issues grouped CRITICAL / MAJOR / MINOR with concrete fixes; classify each CRITICAL as IMPLEMENTATION or ARCHITECTURAL.

Loop-back rules:
- **CRITICAL IMPLEMENTATION** → return to ROLE 4.
- **CRITICAL ARCHITECTURAL** → return to ROLE 3, then ROLE 4, then here.
- **Cycle 2 with unresolved CRITICAL** → mark **BLOCKED**.
- **No CRITICAL** → proceed to ROLE 6.

---

## ROLE 6 — SECURITY REVIEWER

Review the entire implementation through a security lens.

**Review cycle: 1 of 2 maximum.**

Evaluate for this task specifically:
- **Transcript as user input to LLM**: the web transcript is forwarded verbatim to the backend, which in turn passes it to Haiku for field extraction. Confirm no new client-side path bypasses the backend's existing `<user_input>` prompt-injection wrapping. (No change expected — but confirm no transcript is ever injected into a URL path or dangerouslySetInnerHTML in the toast.)
- **Toast content rendering**: the `message` string (e.g., `Added todo: "buy milk"`) comes from the backend but ultimately reflects user-supplied transcript text. Ensure the toast renders it as text, not HTML, to avoid XSS via a dictated `<script>` tag.
- **Rate limiting / abuse**: the endpoint is already `@limiter.limit()`-decorated on the backend (per CLAUDE.md). Confirm the web does not bypass by calling it in a loop on speech-recognition interim events — only `handleVoiceSubmit` should fire the request.

Additionally evaluate (standard checklist):
- Auth & authz — new route already protected on backend; no client-side auth change.
- Input validation & injection — XSS in toast; no SQL path on the client.
- Rate limiting & abuse — LLM cost exposure is backend-bounded.
- Secrets — no new env vars, no secrets in client.
- Dependencies — no new packages.

Output:
- **CRITICAL** — auth bypass, XSS, data exposure.
- **ADVISORY** — document and accept.
- **HARDENING** — optional defense-in-depth.

For each CRITICAL, provide concrete remediation.

Loop-back rules:
- **CRITICAL** → return to ROLE 4, then ROLE 5, then here.
- **Cycle 2 with unresolved CRITICAL** → mark **BLOCKED**.
- **No CRITICAL** → final security sign-off.

---

## Completion

**TASK COMPLETE** when Role 5 and Role 6 both approve with no CRITICAL issues.
**BLOCKED** if any reviewer's cycle cap (2) is reached with unresolved CRITICAL issues — stop and escalate to the user.
