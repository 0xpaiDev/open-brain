# RAG Chat UX/UI Cleanup — Multi-Agent

You will work through this task in six roles, sequentially. Do not skip ahead.
The goal: The RAG Chat page has a clean, minimal header (title only), a sticky bottom input bar that never scrolls off-screen on mobile, model/session config lives on the Settings page, and the external context control is an unobtrusive icon button inside the input bar.

---

## Business context (read once, then put on your shelf)

Open Brain is a personal knowledge management system with a RAG-powered chat interface. The chat page lets a user query their stored memories using an LLM. Right now the chat header is cluttered with a model selector dropdown and a reset button, the external context panel adds visual noise above the input, and on mobile the input field can scroll below the viewport. This cleanup strips the chrome to essentials, relocates configuration to Settings, and ensures the input is always reachable — making the chat feel like a focused conversation tool, not a control panel.

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- The chat page layout (`web/app/chat/page.tsx`) — full component tree, flex structure, height calc
- The model selector component (`web/components/chat/model-selector.tsx`) — props, state source, localStorage key
- The external context panel (`web/components/chat/external-context-panel.tsx`) — collapsible structure, how context flows to the chat hook
- The chat input component (`web/components/chat/chat-input.tsx`) — positioning, textarea behavior, send/keyboard handling
- The Settings page (`web/app/settings/page.tsx`) — current sections, layout pattern, how to add a new section
- The `useChat` hook (`web/hooks/use-chat.ts`) — model state, external context state, reset logic, available models list
- The sidebar/navigation (`web/components/layout/sidebar.tsx` or similar) — how routes are listed, icons used

Also trace for each item:
- Where it is created
- Where it is mutated
- Where it is consumed
- Any related tests

Map the data flow end-to-end: user selects model -> stored in localStorage -> read by useChat -> sent to API.

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
- That removing the model selector from the header and reading it from Settings won't break the useChat hook's model state (localStorage key must stay consistent)
- That `h-[calc(100vh-4rem)]` is correct on all mobile viewports — mobile browsers have dynamic toolbar height that changes `100vh`; `dvh` may be needed
- That moving the external context into an icon-button popover inside the input bar won't break the textarea auto-resize or the send flow (context must still reach useChat)
- That the reset button can be removed from the header without losing discoverability — where will users find it?

Additionally challenge:
- Hidden dependencies or coupling
- Data shape assumptions
- Edge cases (empty context, very long context, mid-stream reset, mobile keyboard open)
- Backward compatibility risks (users who have localStorage model set)
- Missing or weak test coverage for chat components

For each challenge, label:
CONFIRMED | REVISED | UNKNOWN

For anything REVISED or UNKNOWN:
- Revisit the codebase
- Update findings with corrected understanding

Stop. Present the reconciled findings before Role 3 begins.

---

## ROLE 3a — SENIOR UI/UX DESIGNER

Read the reconciled findings. Before any architecture decisions, evaluate the UX holistically.

Assess and recommend on:

1. **Header simplification** — With model selector and reset removed, is "RAG Chat" alone sufficient? Should there be a subtle subtitle or status indicator (e.g., connected model name as muted text)? Or is bare minimal best?

2. **Input bar composition** — The input bar will now house: textarea, send button, external-context icon trigger, and possibly a kebab menu (for reset + future actions). Sketch the layout:
   - Where does each element sit? (left gutter icons vs right action cluster)
   - How does the external context popover/sheet behave on mobile vs desktop?
   - Should the exchange counter stay inline or move?

3. **Settings page "RAG Chat" section** — What controls belong here? Model selector, temperature slider, anything else? How should it be grouped relative to the existing Projects section?

4. **Reset discoverability** — Evaluate: kebab menu in input bar vs. long-press on header title vs. swipe gesture vs. explicit "New chat" button. Recommend the pattern that balances discoverability with minimal chrome.

5. **Mobile-specific concerns** — Virtual keyboard pushing layout, safe-area insets, thumb-reach zones for bottom input bar. Any patterns from common chat apps (WhatsApp, iMessage) worth adopting?

Produce a UX recommendation document with concrete layout sketches (ASCII or description) for each viewport breakpoint.

Stop. Present recommendations before Role 3b begins.

---

## ROLE 3b — SENIOR ARCHITECT

Read the reconciled findings AND the UX recommendations. Design the implementation. Do not write code yet.

Produce a concrete implementation plan covering:

1. **Mobile-safe sticky input** — Replace `h-[calc(100vh-4rem)]` with `h-[calc(100dvh-4rem)]` or use a CSS `position: sticky; bottom: 0` approach. Decide which method is more robust given the existing flex layout. Consider the `dvh` unit browser support vs. a JS-based fallback.

2. **Model config migration to Settings** — Add a "RAG Chat" section to `web/app/settings/page.tsx`. The model selector component can be reused as-is. State stays in localStorage (`ob_chat_model`). The useChat hook reads it on mount — no change needed there. Decide whether to also expose temperature or keep it server-side only for now.

3. **External context as input-bar icon** — Replace the `ExternalContextPanel` above the input with an icon button (paperclip/attach icon) inside `ChatInput`. On click, open a popover (desktop) or bottom sheet (mobile) containing the textarea. The context value still flows through the same prop/state path to useChat. Decide on popover component (shadcn Popover vs Drawer).

4. **Reset button relocation** — Move reset into a kebab/overflow menu (three-dot icon) in the input bar area, or place it as an icon-only button near the conversation. Implement using shadcn DropdownMenu. Include the exchange counter context if appropriate.

5. **Header cleanup** — Strip header to just the page title. Remove the `flex items-center gap-3` row that currently holds model selector + reset. Consider if the header div is even needed or if the title can be part of the chat thread scroll area.

6. **What stays unchanged**
   - `useChat` hook API and state shape (model, externalContext, messages, loading)
   - localStorage key `ob_chat_model` and available models list
   - Chat API endpoint and request/response format
   - ChatThread component (message rendering, auto-scroll)
   - All backend code

7. **Constraints & Safety**
   - No new dependencies — use existing shadcn components (Popover, DropdownMenu, Drawer)
   - Mobile viewport: test with Chrome DevTools device mode (iPhone SE, iPhone 14, Pixel 7)
   - Preserve keyboard shortcuts (Enter to send, Shift+Enter for newline)
   - External context character limit (20,000) must remain enforced
   - Exchange count warning banner must remain visible
   - Existing Vitest and Playwright tests must pass; update component tests that reference moved elements

For each decision:
- Provide reasoning
- If multiple approaches exist, list them and justify the chosen one

Stop. Present the plan. Do not implement until Role 4 begins.

---

## ROLE 4 — IMPLEMENTER

Read the architect's plan and the UX designer's recommendations. Implement exactly as specified.

Work in this order:
1. **Settings page — add RAG Chat section** with model selector (reuse existing component). This is isolated and low-risk.
2. **Chat input bar — integrate external context icon + popover/sheet**. Refactor `ChatInput` to include the attach icon and context popover. Verify context still flows to useChat.
3. **Chat input bar — add overflow/kebab menu** with reset action. Wire up the existing `resetChat` callback.
4. **Chat page header — strip to title only**. Remove model selector and reset button from header. Clean up unused imports.
5. **Fix mobile viewport height** — switch to `dvh` or equivalent. Test that input is always visible.
6. **Update tests** — fix any broken component tests referencing moved elements. Add a test for the new Settings section.

After each step:
- Run `cd web && npm test` (Vitest)
- Fix any failures before continuing

After implementation:
- Run `cd web && npx playwright test` for E2E
- Manually verify on mobile viewport sizes in DevTools
- Check that localStorage model preference persists across page navigation

Final check:
- Re-read the business context
- Verify the implementation matches the original intent
- Especially validate: the input bar is always visible at the bottom on mobile without scrolling, and no functionality was lost — just relocated

Stop. Do not consider the task complete until reviewed.

---

## ROLE 5 — REVIEWER

Review the implementation as if this were a production PR. Be critical and precise.

Inputs:
- Architect's plan
- UX designer's recommendations
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
   - Consistency with existing patterns (MD3 theme, shadcn components, Material Symbols icons)

4. **Safety**
   - Edge cases (empty context, very long context, mid-stream reset, mobile keyboard open)
   - Backward compatibility (existing localStorage values)
   - Failure handling

5. **UX fidelity**
   - Does the result match the UX recommendations?
   - Is the mobile experience genuinely improved?
   - Are interactive elements in thumb-reach zones?

6. **System impact**
   - Hidden coupling or side effects
   - Performance implications (unnecessary re-renders from lifted state)

7. **Tests & validation**
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
