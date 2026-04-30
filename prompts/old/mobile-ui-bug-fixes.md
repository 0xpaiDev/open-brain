# Mobile UI Bug Fixes (4 bugs) — Multi-Agent

You will work through this task in seven roles, sequentially. Do not skip ahead.
Review roles (6 and 7) may loop back for fixes, up to 2 cycles each.
The goal: Fix four mobile-only UI bugs — date input padding, tab bar overflow, oversized button, and clunky task row layout — so the mobile experience feels polished and consistent.

---

## Business context (read once, then put on your shelf)

Open Brain is a personal knowledge management and task tracking app with a Next.js frontend (in `web/`). The owner uses it daily on mobile (iPhone Safari via 0xpai.com). The mobile viewport has several visual bugs that make the UI feel unfinished: an input missing padding, a tab bar that clips its last tab off-screen, an oversized date button, and task rows that feel heavy when due dates are shown. These are all CSS/layout issues — no backend changes needed. The codebase uses Tailwind CSS, shadcn/ui components, and follows a "no duplicate DOM for responsive layouts" rule (use responsive classes, not separate mobile/desktop elements).

The four bugs:
- **BUG-1**: Due Date modal — date input has no right-side padding, text flush against edge
- **BUG-2**: Memory Bank page — "Voice" tab clipped off-screen, only 3 of 4 tabs visible
- **BUG-3**: Today page task input — "Tomorrow" button oversized, flush against container edge
- **BUG-4**: Today page task list — task rows with due dates feel clunky; calendar icon + date badge inline makes multi-line titles heavy

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- The Due Date modal/dialog component (renders the date picker with "10 Apr 2026" input, "Date range" checkbox, Cancel/Apply buttons)
- The Memory Bank page and its tab bar component (Text / Link / Media / Voice tabs)
- The task input panel on the Today page (the "Add a task..." pill bar with priority toggle and date/tomorrow button)
- The task list item/row component (renders checkbox, priority bar, title, calendar icon, date badge)
- The base UI primitives: `input.tsx`, `dialog.tsx`, `tabs.tsx`, `button.tsx` in `web/src/components/ui/`
- Any shared layout or spacing constants/utilities used across these components

Also trace for each item:
- The full class list on the container and inner elements (look for padding, flex, overflow, width classes)
- Any responsive breakpoint classes (`sm:`, `md:`, `lg:`) already in use
- Whether the component uses shadcn/ui primitives or custom markup
- Any related tests (Vitest or Playwright)

Map the layout/styling end-to-end for each bug location.

Produce a findings report with:
- Exact file paths and line numbers
- Current Tailwind classes on the relevant elements
- Root cause hypothesis for each bug
- Your honest assessment of the current mobile styling approach

Note any surprises or mismatches vs expectations.

Stop. Do not proceed to Role 2 until the findings report is complete.

---

## ROLE 2 — SKEPTIC

Read Role 1's findings report. Your job is to break its assumptions.

Challenge specifically:
- That BUG-1 is a simple padding issue — could it be the date picker library (`react-day-picker` or similar) injecting inline styles or its own CSS that overrides Tailwind padding?
- That BUG-2 is a flex/width issue — could the tab bar be inside a container with `overflow-hidden` that clips it? Or could individual tabs have `min-width` or `whitespace-nowrap` preventing shrink?
- That BUG-3's "Tomorrow" button grows because of `flex-1` — could it be that the priority toggle group takes fixed width and the date button fills remaining space? Check the actual flex layout math.
- That BUG-4 can be fixed with `flex-col` on mobile without breaking desktop layout or violating the "no duplicate DOM" rule — verify the current DOM structure supports a single responsive approach
- That fixing these bugs won't break the `text-base md:text-sm` font-size rule (inputs must be >= 16px on mobile to prevent Safari auto-zoom)
- That existing Vitest tests won't break if layout classes change (JSDOM ignores CSS, but class-based test selectors could exist)

Additionally challenge:
- Hidden dependencies or coupling between these components
- Whether the dialog padding fix (recent commit `6746f40`) already partially addresses BUG-1
- Edge cases: very long task titles, no due date, date range mode, RTL text

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

1. **BUG-1: Date input padding** — exact classes to add/change on the date input element inside the Due Date dialog. Identify whether the fix belongs on the input primitive, the dialog-specific wrapper, or an inline override.

2. **BUG-2: Tab bar overflow** — decide between two approaches: (a) `flex-1` on all tabs so they share width equally, or (b) `overflow-x-auto` with horizontal scroll. Justify the choice based on the number of tabs and typical label lengths.

3. **BUG-3: Tomorrow button sizing** — determine how to constrain the button without breaking the layout. Options: remove `flex-1`/`flex-grow`, add `max-w-*`, or restructure the flex container. Consider the relationship between the priority toggle group and the date button.

4. **BUG-4: Task row stacked layout** — design the responsive layout change. On mobile (`< md`): title on line 1, small muted date text on line 2, no calendar icon. On desktop (`>= md`): keep current inline layout. Must use a single DOM structure with responsive Tailwind classes (no duplicate elements).

5. **What stays unchanged**
   - Desktop layout for all four areas must remain identical
   - `text-base md:text-sm` pattern on inputs (Safari zoom prevention)
   - No changes to component props or data flow
   - No changes to test files unless a test explicitly asserts a removed class

6. **Constraints & Safety**
   - All fixes are CSS/Tailwind-only — no JS logic changes
   - Each bug fix should be independently testable (can be applied one at a time)
   - Verify no regression on the recent dialog padding fix (commit `6746f40`)
   - Font sizes on mobile inputs must stay >= 16px

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

## ROLE 3B — SENIOR UX/UI EXPERT

Read the Architect's plan before implementation begins. Evaluate every proposed change through a UX lens.

For each bug fix, evaluate:

1. **Visual consistency**
   - Does the fix maintain consistent spacing rhythm across the app? (e.g., if BUG-1 adds `px-3`, do other inputs in the same dialog/page use the same value?)
   - Are touch targets still >= 44px on mobile (Apple HIG minimum)?
   - Does the fix respect the existing visual hierarchy (muted colors for secondary info, proper contrast)?

2. **Interaction quality**
   - BUG-2 tab bar: if using `flex-1` equal-width tabs, will short labels ("Text") and long labels ("Media") look balanced? Would truncation or icon-only on mobile be better?
   - BUG-3 button: after constraining width, is the tap target still comfortable? Does the button label remain fully readable?
   - BUG-4 stacked layout: does the date badge on line 2 create enough visual separation from the task title? Should it have a left indent to align with the title text (not the checkbox)?

3. **Mobile-specific UX patterns**
   - Verify adequate spacing between interactive elements (no accidental taps)
   - Check that the proposed changes follow platform conventions (iOS Safari is the primary mobile browser)
   - Ensure swipe/scroll gestures aren't blocked by layout changes

4. **Holistic coherence**
   - Do all four fixes together create a consistent mobile experience?
   - Are there any adjacent elements (not in the bug list) that will look inconsistent after these fixes?
   - Flag any "while we're here" improvements that would take < 5 minutes and significantly improve the overall feel

Output:
- **APPROVED** items — fixes that are UX-sound as designed
- **ADJUST** items — fixes that need specific tweaks (provide exact recommendations: spacing values, color tokens, alignment)
- **RETHINK** items — fixes where the architectural approach is correct but the UX outcome needs a different treatment

For each ADJUST or RETHINK item, provide:
- The specific concern
- A concrete alternative with exact Tailwind classes or spacing values where possible
- Visual reasoning (why the alternative feels better on mobile)

The Architect should incorporate ADJUST items directly. RETHINK items should be discussed before proceeding to implementation.

Stop. Present your UX review before Role 4 begins.

---

## ROLE 4 — IMPLEMENTER

Read the Architect's plan and UX Expert's recommendations. Implement incorporating both.

Work in this order:
1. BUG-1: Date input padding fix (smallest, most isolated change)
2. BUG-2: Memory Bank tab bar overflow fix (isolated to one page)
3. BUG-3: Tomorrow button sizing fix (task input area)
4. BUG-4: Task row stacked layout (most complex, touches list rendering)

After each step:
- Run `cd web && npm test` to verify no test regressions
- Fix any failures before continuing

After all four fixes:
- Manually verify each fix addresses the original bug description
- Confirm desktop layout is unchanged (check for unintended responsive class side effects)
- Verify no Safari auto-zoom regression (all mobile input font sizes >= 16px)

Final check:
- Re-read the business context and all four bug descriptions
- Verify each fix matches the original intent
- Especially validate: no duplicate DOM elements were introduced (the "no duplicate DOM for responsive layouts" rule from CLAUDE.md)

Stop. Do not consider the task complete until reviewed.

If recalled by Role 6 or Role 7 for fixes:
- Read the specific issues listed
- Apply fixes to the affected code only
- Do not refactor or change unrelated code
- Summarize what changed and why
- Return to Role 6 for re-review

---

## ROLE 5 — REVIEWER (CODE)

Review the implementation as if this were a production PR. Be critical and precise.

**Review cycle: 1 of 2 maximum.**

Inputs:
- Architect's plan + UX Expert's recommendations
- Full diff of changes
- Implementer's summary

Evaluate across:

1. **Correctness**
   - Does each fix address exactly what the bug describes?
   - Any logical errors or missing responsive breakpoints?

2. **Scope adherence**
   - Any unnecessary changes beyond the four bugs?
   - Were all four bugs addressed?

3. **Code quality**
   - Consistent Tailwind class ordering (layout → spacing → sizing → colors)
   - Consistency with existing patterns in the component

4. **Safety**
   - Edge cases: empty date, very long task title, single tab, no tasks
   - Desktop layout preservation
   - Safari font-size >= 16px on all mobile inputs

5. **System impact**
   - Did any shared component (`input.tsx`, `button.tsx`, `tabs.tsx`) get modified? If so, check all consumers for side effects
   - Performance: no unnecessary re-renders introduced

6. **Tests & validation**
   - Do existing tests still pass?
   - Are any new tests needed for layout changes? (Usually no for pure CSS, but flag if a test was asserting specific classes)

7. **Skeptic's concerns (cross-reference Role 2)**
   - Review each REVISED and UNKNOWN finding from Role 2
   - Is each concern addressed in the implementation, or consciously accepted with documented rationale?
   - Flag any REVISED/UNKNOWN item that was silently ignored

8. **Plan fidelity (cross-reference Role 3 + 3B)**
   - Does the implementation match the Architect's plan?
   - Were the UX Expert's ADJUST items incorporated?
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

## ROLE 6 — UX REVIEW (POST-IMPLEMENTATION)

Review the final implementation through a UX lens one more time, now that real code exists.

**Review cycle: 1 of 2 maximum.**

For each of the four bug fixes, verify:
- The visual result matches the UX Expert's recommendations from Role 3B
- Touch targets are adequate (>= 44px)
- Spacing is consistent with adjacent elements
- The fix doesn't create new visual inconsistencies
- Mobile and desktop both look correct

Output:
- **PASS** — fix looks good on both viewports
- **FAIL** — with specific visual issue and concrete fix recommendation

Loop-back rules:
- **Any FAIL** -> return to ROLE 4 with specific fixes. After fixes, return here and increment review cycle.
- **Review cycle 2 with unresolved FAIL** -> mark **BLOCKED**. Stop.
- **All PASS** -> proceed to ROLE 7.

---

## ROLE 7 — SECURITY REVIEWER

Review the entire implementation through a security lens.

**Review cycle: 1 of 2 maximum.**

Evaluate for this task specifically:
- No new user-controllable content rendered without sanitization (task titles, date strings are already escaped by React, but verify)
- No inline `style=` attributes that could be injection vectors if task data is user-supplied
- No new event handlers or JavaScript logic introduced (these are CSS-only fixes)

Additionally evaluate (standard checklist):
- Authentication & authorization — no new routes or API changes expected
- Input validation & injection — no new inputs; existing inputs unchanged
- Rate limiting & abuse — no new endpoints
- Data at rest & in transit — no changes
- Dependencies — no new packages added

Output:
- **CRITICAL** — must fix before deployment (auth bypass, injection, data exposure)
- **ADVISORY** — risks to document and accept consciously
- **HARDENING** — optional defense-in-depth improvements

For each CRITICAL issue, provide a concrete remediation.

Loop-back rules:
- **CRITICAL issues** -> return to ROLE 4 with explicit fixes required. After fixes, return to ROLE 6 for re-review, then return here (ROLE 7) and increment review cycle.
- **Review cycle 2 with unresolved CRITICAL issues** -> mark the task **BLOCKED**. List all unresolved issues with context. Stop.
- **No CRITICAL issues** -> provide final security sign-off.

---

## Completion

**TASK COMPLETE** when Role 5 (Code Review), Role 6 (UX Review), and Role 7 (Security Review) all approve with no CRITICAL issues.
**BLOCKED** if any reviewer's cycle cap (2) is reached with unresolved CRITICAL issues — stop and escalate to the user.
