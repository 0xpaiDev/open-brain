# Operations Log Dashboard — Multi-Agent

You will work through this task in six roles, sequentially. Do not skip ahead.
Review roles (5 and 6) may loop back for fixes, up to 2 cycles each.
The goal: A `/logs` page in the web dashboard that shows job runs (synthesis, pulse, importance), memory ingestion pipeline status, and dead-letter failures — with filters, status indicators, and expandable detail views — so the operator can quickly tell if something is broken without SSHing into the server.

---

## Business context (read once, then put on your shelf)

Open Brain is a personal knowledge management system with a FastAPI backend, async worker pipeline, scheduled cron jobs (synthesis, pulse, importance), and a Next.js web dashboard. Currently, the only way to check if a job failed or the pipeline stalled is to SSH into the server and read logs. The backend already exposes three monitoring endpoints — `GET /v1/jobs/status`, `GET /v1/queue/status`, and `GET /v1/dead-letters` — plus a `JobRun` table that records every scheduled job execution with status, duration, and error messages. This task builds a frontend page that surfaces all of this existing data in a filterable, scannable dashboard so failures are immediately visible.

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- The three backend monitoring endpoints: `GET /v1/jobs/status` (in `src/api/routes/jobs.py`), `GET /v1/queue/status` and `GET /v1/dead-letters` (in `src/api/routes/queue.py`) — read their exact response shapes, query params, and rate limits
- The `JobRun` model in `src/core/models.py` and how `run_tracked()` in `src/jobs/runner.py` populates it — understand what fields are available (job_name, started_at, finished_at, status, error_message, duration_seconds)
- The `RefinementQueue` and `FailedRefinement` models — understand the pipeline states (pending/processing/done/failed) and dead-letter fields (error_reason, last_output, attempt_count, retry_count, resolved_at)
- The existing web dashboard page structure: `web/app/` routing, `web/components/layout/sidebar.tsx` and `web/components/layout/bottom-tabs.tsx` for navigation, `web/lib/api.ts` for the fetch wrapper, `web/lib/types.ts` for TypeScript interfaces
- The `TaskList` component (`web/components/dashboard/task-list.tsx`) as the most complete example of filtering, tabs, and pagination in the frontend
- The `useMemories` and `useTodos` hooks in `web/hooks/` for the data fetching pattern (useState + useEffect + api() wrapper)
- Check if `GET /v1/jobs/status` returns a list of historical runs or just the latest per job — this determines whether we need a new endpoint for job run history

Also trace for each backend endpoint:
- The exact JSON response schema (field names, types, nesting)
- Query parameters and defaults
- Rate limit decorators

Map the data flow: backend tables → API endpoints → what the frontend will consume.

Produce a findings report with:
- Exact file paths
- Response schemas for each endpoint
- Data flow description
- Assessment of whether the existing endpoints are sufficient or if new ones are needed (especially: do we need a paginated job run history endpoint?)
- Any surprises or gaps

Stop. Do not proceed to Role 2 until the findings report is complete.

---

## ROLE 2 — SKEPTIC

Read Role 1's findings report. Your job is to break its assumptions.

Challenge specifically:
- Does `GET /v1/jobs/status` return enough historical data for a useful log view, or does it only return the last run per job? If only the latest, the dashboard will be nearly empty — we may need a new `GET /v1/jobs/history` endpoint that paginates `job_runs` rows
- Are the dead-letter `last_output` fields actually populated in practice, or could they be null/empty? The "expand for details" feature depends on this data existing
- Is the `GET /v1/queue/status` response sufficient to show per-item pipeline status, or does it only return aggregate counts? If only counts, we can't show individual pipeline items
- Does the frontend `api()` wrapper handle 429 (rate limit) responses gracefully, or will frequent polling of the logs page trigger rate limit errors with no user feedback?
- Will auto-refresh / polling conflict with the existing rate limits on these endpoints (e.g., `/v1/queue/status` is 30/min)?

Additionally challenge:
- Hidden dependencies or coupling
- Data shape assumptions
- Edge cases (empty job history, all jobs successful, no dead letters)
- Backward compatibility risks (new nav item, new types)
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

1. **New backend endpoint (if needed)** — If `/v1/jobs/status` only returns latest-per-job, design a `GET /v1/jobs/history` endpoint that paginates `job_runs` with filters (job_name, status, date range). Define the response schema. If existing endpoints are sufficient, document why no new endpoint is needed.

2. **Frontend page structure** — Layout of the `/logs` page: what sections it has (job runs, queue status, dead letters), how they're organized (tabs vs. stacked sections), and what components are needed. Follow existing patterns from TaskList and the dashboard page.

3. **Data fetching strategy** — Custom hooks for each data source (useJobHistory, useQueueStatus, useDeadLetters). Polling interval for auto-refresh (respect rate limits). Loading/error states. Consider whether to poll or use manual refresh.

4. **Filtering and status indicators** — What filters to expose (job name, status, date range). How to visually indicate failures (color coding, icons, badges). How to show "system healthy" vs "something is wrong" at a glance — consider a summary banner at the top.

5. **Detail expansion** — How to show error messages, dead-letter `last_output`, and job duration. Collapsible rows, slide-out panels, or modal dialogs. What info is shown in the collapsed vs expanded state.

6. **What stays unchanged**
- No changes to existing backend models or tables
- No changes to existing pages or components (except adding nav item)
- No new database migrations
- The `api()` wrapper in `web/lib/api.ts` stays as-is

7. **Constraints & Safety**
- Rate limiting: polling interval must respect existing rate limits (30/min for queue status)
- No new dependencies unless absolutely necessary
- Mobile responsive (follow existing Tailwind patterns, `text-base md:text-sm` for inputs)
- Empty states for when there are no failures / no history
- Error boundary for the page itself
- Follow the existing shadcn/ui + Material Design 3 color system

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
1. **Backend first (if new endpoint needed)** — Add the job history endpoint to `src/api/routes/jobs.py`, add rate limiter, add to router. Run `make test` to verify no regressions.
2. **TypeScript types** — Add response interfaces to `web/lib/types.ts` for job runs, queue status, and dead letters.
3. **Data fetching hooks** — Create hooks in `web/hooks/` following the existing useState + useEffect + api() pattern from `use-memories.ts` and `use-todos.ts`.
4. **Page and components** — Create `web/app/logs/page.tsx` and supporting components under `web/components/logs/`. Follow the TaskList pattern for filtering and the dashboard pattern for page layout.
5. **Navigation** — Add the logs page to `sidebar.tsx` and `bottom-tabs.tsx` nav arrays.
6. **Tests** — Add Vitest tests for the new hooks and key component rendering. Add a backend test for any new endpoint.

After each step:
- Run the existing test suite
- Fix any failures before continuing

After implementation:
- Verify the page renders with mock/real data
- Check mobile responsiveness
- Test filter combinations and empty states

Final check:
- Re-read the business context
- Verify the implementation matches the original intent
- Especially validate: failures are immediately visible and scannable — the operator should be able to tell within 5 seconds if something is broken

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
- **CRITICAL IMPLEMENTATION issues** → return to ROLE 4 with explicit fixes required. After fixes, return here (ROLE 5) and increment review cycle.
- **CRITICAL ARCHITECTURAL issues** → return to ROLE 3 with the specific concern. After ROLE 3 revises the plan, ROLE 4 re-implements the affected parts, then return here (ROLE 5) and increment review cycle.
- **Review cycle 2 with unresolved CRITICAL issues** → mark the task **BLOCKED**. List all unresolved issues with context. Stop — these need human decision-making.
- **No CRITICAL issues** → proceed to ROLE 6.

---

## ROLE 6 — SECURITY REVIEWER

Review the entire implementation through a security lens.

**Review cycle: 1 of 2 maximum.**

Evaluate for this task specifically:
- Are any new endpoints properly protected with `@limiter.limit()` and the existing API key middleware? (CLAUDE.md: "Every `/v1/*` route needs `@limiter.limit()`")
- Does the dead-letter detail view expose `last_output` (raw LLM responses) in a way that could leak sensitive user content? Consider whether to truncate or sanitize.
- If auto-refresh polling is implemented, can it be abused to amplify requests against rate-limited endpoints?

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
