# Mobile UI Fixes: Viewport Jumping, Safari Auto-Zoom, Safe-Area Nav — Multi-Agent

You will work through this task in six roles, sequentially. Do not skip ahead.
Review roles (5 and 6) may loop back for fixes, up to 2 cycles each.
The goal: The webapp renders without layout jumps on mobile browsers with appearing/disappearing toolbars, never triggers Safari's auto-zoom on input focus, and the bottom nav bar sits above the iOS home indicator with properly spaced items.

---

## Business context (read once, then put on your shelf)

Open Brain is a personal knowledge management system with a Next.js 16 web dashboard (Tailwind v4, dark MD3 theme). The primary mobile user accesses it on an iPhone through Safari. Three persistent UI annoyances make the mobile experience feel broken: the layout jumps when Safari's bottom toolbar appears/disappears, tapping the chat input triggers Safari's auto-zoom (font-size < 16px), and the bottom navigation bar overlaps the iOS home gesture area. These are all well-understood mobile web problems with known CSS solutions — the fixes are surgical and low-risk.

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- The root layout at `web/app/layout.tsx` — specifically the viewport meta tag (or lack thereof), the `<html>` and `<body>` class names, and the content wrapper's padding/height classes
- The chat page at `web/app/chat/page.tsx` — the `100dvh` calc that controls chat height, and how it accounts for top nav + bottom tabs
- The chat input textarea at `web/components/chat/chat-input.tsx` — the `text-sm` class on the main textarea (line ~124-132) and the `text-xs` external context textarea (line ~87-97)
- The bottom tabs nav at `web/components/layout/bottom-tabs.tsx` — the `fixed bottom-0` positioning, padding, and absence of safe-area-inset handling
- The global CSS at `web/app/globals.css` — any existing viewport or safe-area utilities
- The settings page at `web/app/settings/page.tsx` — input and select elements using `text-sm`
- The reusable Input and Textarea components at `web/components/ui/input.tsx` and `web/components/ui/textarea.tsx` — they already use `text-base md:text-sm` (correct pattern)

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
- That `dvh` alone is sufficient for the jumping layout — some older iOS versions don't support `dvh`, and the viewport meta tag's `interactive-widget=resizes-visual` might be needed alongside it to fully prevent toolbar-triggered layout shifts
- That setting font-size to 16px on mobile inputs is the only factor in Safari auto-zoom — the `<meta name="viewport">` tag must NOT contain `user-scalable=no` or `maximum-scale=1` (which are accessibility violations) but MUST contain `width=device-width, initial-scale=1` to let the 16px rule work correctly
- That `env(safe-area-inset-bottom)` works without `viewport-fit=cover` in the viewport meta tag — the `env()` values are all zero unless `viewport-fit=cover` is set, making the safe-area fix a two-part change
- That the bottom nav only needs bottom padding — check whether the top nav also needs `env(safe-area-inset-top)` on devices with a Dynamic Island or notch, and whether the content wrapper's `pb-20` needs to grow to accommodate the added safe-area padding on the nav

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

1. **Viewport meta tag** — Add/update the viewport meta tag in `web/app/layout.tsx` using Next.js `metadata.viewport` export. Must include `width=device-width, initial-scale=1, viewport-fit=cover`. Do NOT add `maximum-scale=1` or `user-scalable=no` (accessibility violation). The `viewport-fit=cover` is required for `env(safe-area-inset-*)` to return non-zero values.

2. **Safe-area padding on bottom nav** — Add `pb-[env(safe-area-inset-bottom)]` (or a custom utility class in globals.css) to the bottom tabs component so it clears the iOS home indicator. Decide whether to use Tailwind's arbitrary value syntax or a CSS custom property. Also decide whether the content wrapper's `pb-20` needs adjustment.

3. **Font-size normalization on all mobile inputs** — The chat input textarea and external context textarea in `chat-input.tsx` need `text-base md:text-sm` (matching the pattern already used by the reusable Input/Textarea components). Same for select elements in smart-composer.tsx and settings/page.tsx. This prevents Safari auto-zoom without disabling user zoom.

4. **Layout height stability** — Evaluate whether the existing `100dvh` usage in `chat/page.tsx` is sufficient or whether `interactive-widget=resizes-visual` (or `resizes-content`) should be added to the viewport meta to prevent toolbar-triggered reflows. Choose the right `interactive-widget` value and justify it.

5. **What stays unchanged**
- The `h-full` / `min-h-full` on html/body — these are fine
- Desktop layout (md+ breakpoints) — all changes scoped to mobile via responsive prefixes
- The reusable Input/Textarea shadcn components — they already handle font-size correctly
- No JavaScript solutions for viewport height — CSS-only

6. **Constraints & Safety**
- No `user-scalable=no` or `maximum-scale=1` — these are accessibility violations and Apple ignores them in recent Safari anyway
- Changes must not break existing desktop layout
- `env(safe-area-inset-bottom)` must have a fallback of `0px` for browsers that don't support it
- No new npm dependencies
- Rollback: all changes are CSS/meta-only, trivially revertible

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
1. **Viewport meta tag** — Add or update the viewport export in `web/app/layout.tsx` with `width=device-width, initial-scale=1, viewport-fit=cover` and the chosen `interactive-widget` value
2. **Global CSS safe-area utility** — Add any needed utility classes or CSS custom properties in `web/app/globals.css` for safe-area-inset handling (if Tailwind arbitrary values aren't sufficient)
3. **Bottom nav safe-area padding** — Update `web/components/layout/bottom-tabs.tsx` to add bottom padding that clears the home indicator
4. **Content wrapper padding adjustment** — Update the main content wrapper in `web/app/layout.tsx` if the bottom nav's added safe-area padding changes its total height
5. **Chat input font-size fix** — Update `web/components/chat/chat-input.tsx` to use `text-base md:text-sm` on both the main textarea and the external context textarea
6. **Settings & smart-composer font-size fix** — Update `web/app/settings/page.tsx` and `web/components/memory/smart-composer.tsx` select/input elements to use `text-base md:text-sm`

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
- Especially validate: no `maximum-scale=1` or `user-scalable=no` appears anywhere in the viewport meta, and all mobile input font sizes are >= 16px (`text-base`)

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
- Viewport meta tag must NOT disable user zoom (`user-scalable=no`, `maximum-scale=1`) — this is both an accessibility violation (WCAG 1.4.4) and a security concern (users must be able to zoom to inspect phishing attempts)
- `viewport-fit=cover` extends content into safe areas — verify no interactive elements (buttons, links) are rendered behind the status bar or home indicator without proper inset padding
- CSS `env()` values come from the browser — verify they are only used in CSS (not passed to JavaScript or APIs) and cannot be manipulated to cause layout injection

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
