# UI Polish Sprint — Multi-Agent

You will work through this task in seven roles, sequentially. Do not skip ahead.
Review roles (6 and 7) may loop back for fixes, up to 2 cycles each.
The goal: Five UI/UX improvements ship across the Memory and Dashboard pages — memory type icons for Todo/Pulse, consistent tab bar & form styling, tomorrow as default due date, a collapsible History parent group for past tasks, and a wider max-width layout across all pages.

---

## Business context (read once, then put on your shelf)

Open Brain is a personal knowledge management system with a Next.js frontend (under `web/`). It has a Memory page for browsing ingested memories and a Dashboard for managing daily tasks and morning pulse check-ins. The app follows a Material Design 3 dark theme with design tokens in `web/app/globals.css`, uses Google Material Symbols Outlined for icons, and `@base-ui/react` primitives for UI components. The user is a solo developer who uses this daily — these five changes address visual inconsistencies and ergonomic friction that have accumulated over several feature sprints.

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- The `TYPE_CONFIG` object in `web/components/memory/memory-card.tsx` — how existing memory types (memory, decision, task, context) get icons, badges, and className
- The `SmartComposer` component in `web/components/memory/smart-composer.tsx` — the tab bar implementation, how tabs are styled, and how Voice tab behaves on mobile
- The `AddTaskForm` in `web/components/dashboard/task-list.tsx` — the default `dueDate` state initialization, the "Add task" Button, and the priority Select styling
- The `groupDoneTodos` function in `web/hooks/use-todos.ts` and how done groups are rendered with Collapsible in `task-list.tsx`
- The `<main>` wrapper in `web/app/layout.tsx` — current `max-w-7xl` class and padding values
- The shared UI components: `web/components/ui/tabs.tsx`, `web/components/ui/button.tsx`, `web/components/ui/select.tsx`, `web/components/ui/collapsible.tsx`

Also trace for each item:
- Where it is created
- Where it is mutated
- Where it is consumed
- Any related tests

Map the data flow end-to-end where applicable.

Produce a findings report with:
- Exact file paths and line numbers
- Relevant code snippets
- Data flow description
- Your honest assessment of structure and quality

Note any surprises or mismatches vs expectations.

Stop. Do not proceed to Role 2 until the findings report is complete.

---

## ROLE 2 — SKEPTIC

Read Role 1's findings report. Your job is to break its assumptions.

Challenge specifically:
- That adding new entries to `TYPE_CONFIG` is sufficient — are there other places that filter or switch on memory type strings (e.g. API responses, search filters, type definitions in `lib/types.ts`)?
- That changing `max-w-7xl` to a wider value won't break the sidebar offset (`md:ml-64`) or cause horizontal overflow on medium-width screens (768–1024px)
- That wrapping all done groups in a single parent Collapsible won't break the existing per-group collapse state or cause nested-collapsible rendering issues with `@base-ui/react/collapsible`
- That the tab bar overflow on mobile is purely a CSS issue — check whether the Voice tab's wider content (icon + "Voice" label + possible recording indicator) is the actual cause, or if the tabs container has a hard width constraint
- That changing the default due date from today to tomorrow won't break the `AddTaskForm` reset logic or the date picker validation

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

1. **Memory type icons & tags** — which icon and badge text to use for `todo` and `daily-pulse` types in `TYPE_CONFIG`, what badge colors to assign (following the existing `bg-secondary/20 text-secondary` pattern or picking distinct colors from the MD3 palette), and whether the API returns these as distinct `memory_type` values
2. **Tab bar & form control restyling** — whether to modify the shared `tabs.tsx` component or apply overrides in `smart-composer.tsx`, how to achieve responsive tab layout on mobile (horizontal scroll with `overflow-x-auto` vs. icon-only on small screens vs. wrapping), and how to restyle the "Add task" button and priority dropdown to match the rounded design language
3. **Default due date change** — the exact line to change in `AddTaskForm`, whether the reset-after-submit should also use tomorrow, and date calculation approach (simple `Date` arithmetic vs. a utility)
4. **History parent group** — how to nest a parent Collapsible around the existing done groups map, state management for the parent open/closed state, and whether to persist collapse state (localStorage vs. ephemeral)
5. **Layout max-width scaling** — the target value (custom `max-w-[1400px]` or Tailwind's `max-w-screen-xl`), which pages/components need updating, and whether the sidebar offset math still works at wider breakpoints

6. **What stays unchanged**
- The `@base-ui/react` primitive components themselves — no modifications to the headless library
- The API response shapes and `memory_type` values returned by the backend
- The `groupDoneTodos` logic in `use-todos.ts` — only the rendering wrapper changes
- The design tokens in `globals.css` (colors, fonts, radii) — reuse existing values
- Mobile safe-area and bottom nav behavior

7. **Constraints & Safety**
- All `<input>`, `<textarea>`, `<select>` must keep `text-base md:text-sm` pattern (no bare `text-sm`) to prevent Safari auto-zoom
- Changes must pass existing Vitest and Playwright tests without modification
- No new dependencies — use existing Material Symbols icons and Tailwind utilities
- Each of the 5 changes should be independently committable
- Rollback: each change is a pure frontend CSS/JSX change with no backend coupling

For each decision:
- Provide reasoning
- If multiple approaches exist, list them and justify the chosen one

Stop. Present the plan. Do not implement until Role 4 begins.

If recalled by Role 6 for an architectural revision:
- Read the specific concern raised
- Update only the affected sections of the plan
- Note what changed and why
- Return to Role 4 to re-implement the affected parts

---

## ROLE 3B — SENIOR UI/UX REVIEWER

Read the Architect's plan. Evaluate it through the lens of visual consistency, interaction design, and user experience.

For each of the 5 changes, evaluate:

1. **Visual consistency**
   - Do the proposed icon and color choices for Todo/Pulse badges fit the existing visual hierarchy? Will they be instantly distinguishable from existing types at a glance?
   - Does the proposed tab bar restyle maintain visual weight balance across all 4 tabs?
   - Does the History parent group add useful hierarchy or just extra clicks?

2. **Interaction design**
   - For the responsive tab bar: will the chosen approach (scroll/wrap/icon-only) be discoverable on mobile? Can users tell there are more tabs?
   - For the History parent: should it default to open or closed? What's the most common use pattern?
   - For default due date: will "Tomorrow" as default confuse users who are adding same-day tasks?

3. **Information hierarchy**
   - Does the wider max-width (1400px) maintain comfortable reading line lengths for task descriptions and memory card text?
   - Is the memory card bento grid going to look right at wider widths, or will cards stretch too much?

4. **Accessibility**
   - Color contrast: do proposed badge colors meet WCAG AA on dark backgrounds?
   - Touch targets: are mobile tab targets at least 44px?
   - Focus states: will the nested collapsible maintain keyboard navigation?

5. **Polish details**
   - Transitions and animations: should the History parent collapsible animate?
   - Empty states: what does "History" look like when there are no past tasks?
   - Loading states: any impact on skeleton/loading UI?

Output:
- **APPROVE** items that are well-designed
- **REFINE** items with specific UX improvement suggestions (the Architect should incorporate these)
- **REJECT** items that would degrade UX (with alternative approach)

If any items are REFINE or REJECT, return to ROLE 3 to update the plan before proceeding to ROLE 4.

---

## ROLE 4 — IMPLEMENTER

Read the architect's plan (incorporating any UI/UX refinements from Role 3B). Implement it exactly as specified.

Work in this order:
1. **Memory type icons & tags** — add `todo` and `daily-pulse` entries to `TYPE_CONFIG` in `memory-card.tsx` with chosen icons and badge styling
2. **Default due date** — change the `dueDate` state initializer in `AddTaskForm` to tomorrow's date, update the reset-after-submit logic
3. **Layout max-width** — update `max-w-7xl` to the chosen wider value in `layout.tsx`, verify sidebar offset still works
4. **Tab bar & form controls** — restyle the `SmartComposer` tab bar for rounded consistency and mobile responsiveness, restyle the "Add task" button and priority dropdown in `task-list.tsx`
5. **History parent group** — wrap the done groups rendering in `task-list.tsx` with a parent Collapsible

After each step:
- Run the existing test suite (`cd web && npm test`)
- Fix any failures before continuing

After implementation:
- Run Playwright E2E tests (`cd web && npx playwright test`)
- Manually verify on mobile viewport (Chrome DevTools responsive mode)
- Check that all 5 changes render correctly together

Final check:
- Re-read the business context
- Verify the implementation matches the original intent
- Especially validate: all inputs maintain `text-base md:text-sm` font sizing (no Safari auto-zoom regression)

Stop. Do not consider the task complete until reviewed.

If recalled by Role 6 or Role 7 for fixes:
- Read the specific issues listed
- Apply fixes to the affected code only
- Do not refactor or change unrelated code
- Summarize what changed and why
- Return to Role 6 for re-review

---

## ROLE 5 — REVIEWER

Review the implementation as if this were a production PR. Be critical and precise.

**Review cycle: 1 of 2 maximum.**

Inputs:
- Architect's plan
- UI/UX reviewer's refinements
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
- Any new user-supplied text being rendered without sanitization (XSS via memory content, task descriptions, badge labels)
- Whether the tab bar restyle or form control changes introduce clickjacking or input confusion vectors
- Whether the wider layout exposes any content that was previously clipped or hidden on narrower viewports

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
