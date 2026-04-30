# Web Chat Frontend (Session 2) — Multi-Agent

You will work through this task in five roles, sequentially. Do not skip ahead.
The goal: Replace the `/chat` stub page with a fully functional RAG chat UI — model selector, threaded messages with collapsible sources, external context injection, soft exchange limit, and a `useChat` hook wired to the existing `POST /v1/chat` backend endpoint.

---

## Business context (read once, then put on your shelf)

Open Brain is a single-user personal memory system with a PostgreSQL-backed RAG pipeline. It ingests text (via Discord bot, CLI, or web dashboard), extracts structured memories, and surfaces them through hybrid search. Session 1 already built the backend: `POST /v1/chat` accepts a message + conversation history + optional external context, formulates a search query via Haiku, retrieves relevant memories, and synthesizes a response via a user-selected Claude model (Haiku or Sonnet). The frontend is a Next.js 14 app using shadcn/ui components, Material Symbols icons, and a Material Design 3-inspired design token system (CSS variables like `text-on-surface`, `bg-surface-container`, `text-primary`, etc.). This session builds the chat UI that calls that endpoint.

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- The backend chat endpoint at `src/api/routes/chat.py` — note the exact request/response shapes (`ChatRequest`, `ChatResponse`, `ChatSourceItem`), field names, and defaults
- The existing API client at `web/lib/api.ts` — understand how `api<T>(method, path, body)` works, how auth is handled, and error shapes (`ApiError`)
- The existing types at `web/lib/types.ts` — note `SearchResultItem` (similar to `ChatSourceItem`) and all existing interfaces
- The current chat page stub at `web/app/chat/page.tsx`
- An existing hook like `web/hooks/use-memories.ts` — study the state management pattern, error handling, and how `api()` is called
- An existing component page like `web/app/memory/page.tsx` — study layout structure, `"use client"`, Suspense wrapping
- The shadcn/ui components available in `web/components/ui/` — especially `select.tsx`, `collapsible.tsx`, `textarea.tsx`, `button.tsx`
- The sidebar at `web/components/layout/sidebar.tsx` — note the nav structure, styling classes, and design tokens used
- The test setup at `web/__tests__/setup.ts` and an existing hook test like `web/__tests__/hooks/use-memories.test.ts` — note Vitest + Testing Library patterns, mock approach for `fetch`, `vi.mock("sonner")`
- The implementation plan at `docs/chat-implementation-plan.md` — Session 2 (steps 7-11) is the spec

Also trace for each item:
- Where it is created
- Where it is mutated
- Where it is consumed
- Any related tests

Map the data flow end-to-end: user types message → `useChat` hook → `api()` call → `POST /v1/chat` → response → message list → rendered in thread.

Produce a findings report with:
- Exact file paths
- Relevant code snippets (especially response shapes — the field is `response` not `reply` in the actual backend)
- Data flow description
- The design token system (CSS class naming convention from existing components)
- Your honest assessment of structure and quality

Note any surprises or mismatches vs the plan document (the plan says `reply` but the backend returns `response`; the plan says `history_length` but the backend doesn't return it).

Stop. Do not proceed to Role 2 until the findings report is complete.

---

## ROLE 2 — SKEPTIC

Read Role 1's findings report. Your job is to break its assumptions.

Challenge specifically:
- **Response shape mismatch**: The plan doc (Section 2c) defines `ChatResponse.reply` and `history_length`, but the actual backend at `src/api/routes/chat.py` returns `response` (not `reply`) and has no `history_length` field. The frontend types MUST match the actual backend, not the plan.
- **Model default assumption**: The plan hardcodes `"claude-haiku-4-5-20251001"` in `ChatRequest.model`, but the backend accepts `model: str | None = None` and resolves to `settings.rag_default_model` server-side. The frontend should send the model string or `null`/omit it for default.
- **History truncation boundary**: The plan says `.slice(-20)` keeping "last 10 pairs" — but 20 messages != 10 pairs if the conversation has errors or resets. Verify the backend validates `len(body.history) > 20` at `chat.py:118`.
- **Component isolation**: Are the five proposed components (`ModelSelector`, `ChatSources`, `ChatThread`, `ExternalContextPanel`, `ChatInput`) the right decomposition, or would fewer/more components better match the existing component patterns in this codebase?

Additionally challenge:
- Hidden dependencies or coupling (does `useChat` need `sonner` toast for errors? Does it need `next/navigation`?)
- Data shape assumptions (backend `ChatSourceItem.importance_score` is `float` — can it be null? Check `SearchResult` in `src/retrieval/search.py`)
- Edge cases (empty history on first message, external context cleared mid-conversation, network failure mid-chat, empty sources list)
- Backward compatibility risks (does replacing the stub break any existing links or imports?)
- Missing or weak test coverage (what should the Vitest tests cover — hook logic, component rendering, or both?)

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

1. **Types** (`web/lib/types.ts`) — exact interfaces to add, matching the *actual* backend response (field `response` not `reply`, no `history_length`). Reuse `SearchResultItem` fields where they overlap with `ChatSourceItem`.

2. **Hook** (`web/hooks/use-chat.ts`) — state shape (`messages`, `externalContext`, `model`, `loading`, `error`), `sendMessage(text)` flow, history truncation to 20 messages before API call, `resetChat()`, `exchangeCount` derivation, localStorage key for model persistence (`ob_chat_model`), error handling (set error state, don't throw).

3. **Components** (`web/components/chat/`) — each component's props interface, what shadcn/ui primitives it uses, and how it follows the existing design token system:
   - `ModelSelector` — shadcn `Select`, two options, `localStorage` persistence
   - `ChatSources` — shadcn `Collapsible`, renders source cards with type badge, content snippet (use `summary` if available, else truncate `content` to 200 chars), project label, score
   - `ChatThread` — scrollable container, auto-scroll on new message, user/assistant bubble styling, "Searched for: ..." label, `ChatSources` per assistant message, loading skeleton
   - `ExternalContextPanel` — shadcn `Collapsible` + `Textarea`, character count, clear button
   - `ChatInput` — `Textarea` with Enter-to-send / Shift+Enter-for-newline, send button, exchange counter badge, yellow warning at 10+ exchanges

4. **Page** (`web/app/chat/page.tsx`) — `"use client"`, layout: sticky header (title + ModelSelector + Reset button) → flex-grow ChatThread → ExternalContextPanel → ChatInput. No Suspense needed (no server data fetching).

5. **What stays unchanged**
   - `web/lib/api.ts` — used as-is
   - `web/lib/types.ts` — only append new interfaces, don't modify existing ones
   - `web/components/layout/sidebar.tsx` — already links to `/chat`
   - Backend files — Session 1 is complete
   - All other pages and components

6. **Constraints & Safety**
   - Design tokens: use existing CSS class patterns (`text-on-surface`, `bg-surface-container`, `border-outline-variant/15`, `font-headline`, etc.) — do NOT introduce Tailwind color literals
   - Icons: use Material Symbols Outlined via `<span className="material-symbols-outlined">icon_name</span>` — match existing pattern
   - No external dependencies beyond what's already in `package.json`
   - Tests go in `web/__tests__/` following the existing directory structure (`hooks/use-chat.test.ts`, `components/chat-thread.test.tsx`)
   - `npm run build` must pass with zero errors
   - `npm test` must pass

For each decision:
- Provide reasoning
- If multiple approaches exist, list them and justify the chosen one

Stop. Present the plan. Do not implement until Role 4 begins.

---

## ROLE 4 — IMPLEMENTER

Read the architect's plan. Implement it exactly as specified.

Work in this order:
1. **Add chat types to `web/lib/types.ts`** — append `ChatMessage`, `ChatSourceItem`, `ChatDisplayMessage`, `ChatRequest`, `ChatResponse` interfaces. Run `npm run build` (gate: no TS errors).
2. **Create `web/hooks/use-chat.ts`** — implement the hook with all state, `sendMessage`, `resetChat`, model persistence. Run `npm run build`.
3. **Create chat components** in `web/components/chat/`:
   - `model-selector.tsx`
   - `chat-sources.tsx`
   - `chat-thread.tsx`
   - `external-context-panel.tsx`
   - `chat-input.tsx`
   Run `npm run build` after all five.
4. **Replace `web/app/chat/page.tsx`** — wire hook + components into the page layout. Run `npm run build`.
5. **Write tests** in `web/__tests__/`:
   - `hooks/use-chat.test.ts` — test `sendMessage`, `resetChat`, error handling, model persistence, history truncation
   - `components/chat-thread.test.tsx` — test message rendering, sources display, loading state
   Run `npm test`.

After each step:
- Run the existing test suite (`cd web && npm test`)
- Fix any failures before continuing

After implementation:
- Run `npm run build` one final time to confirm clean build
- Verify no lint errors (`cd web && npx next lint` if configured)
- Identify any remaining risks or edge cases

Final check:
- Re-read the business context
- Verify the implementation matches the original intent
- Especially validate: **frontend types match the actual backend `ChatResponse` shape** (`response` field, not `reply`; no `history_length`), and all user input goes through the `<user_input>` wrapping on the backend side (frontend just sends raw text).

Stop. Do not consider the task complete until reviewed.

---

## ROLE 5 — REVIEWER

Review the implementation as if this were a production PR. Be critical and precise.

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
   - Consistency with existing patterns (hooks, components, design tokens, test structure)

4. **Safety**
   - Edge cases (null, async, race conditions — especially rapid send clicks causing out-of-order responses)
   - Backward compatibility (stub replacement doesn't break routes or sidebar)
   - Failure handling (network errors display gracefully, no partial state corruption)

5. **System impact**
   - Hidden coupling or side effects
   - Performance implications (auto-scroll, re-renders on message list growth)

6. **Tests & validation**
   - Are tests sufficient and meaningful?
   - What critical paths are untested?

Output:
- List of issues grouped by severity:
  - CRITICAL (must fix before merge)
  - MAJOR (should fix)
  - MINOR (nice to improve)

- Concrete suggested fixes for each CRITICAL and MAJOR issue

If CRITICAL issues exist:
- The task is NOT complete
- Return to ROLE 4 with explicit fixes required

If no CRITICAL issues:
- Provide final approval summary
- Highlight any residual risks or follow-up improvements
