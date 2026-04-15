# Aggregate Period Commitments — Multi-Agent

You will work through this task in sequential roles. Do not skip ahead.
Optional roles (marked "conditional") are included only when relevant — if absent, proceed to the next numbered role.
Review roles (5 and 6) may loop back for fixes, up to 2 cycles each.
The goal: Support aggregate-period commitments where progress accumulates from Strava activity ingestions across an arbitrary window, with a pace indicator showing ahead/behind schedule — coexisting with existing daily commitments.

---

## Business context (read once, then put on your shelf)

Open Brain is a personal memory and productivity system used by a single user. It has a commitment feature for tracking daily goals (e.g. "50 pushups every day this week") backed by per-day entries that flip to hit/miss. A recent addition ingests Strava cycling activities via webhook. The problem: cycling goals are period-based ("200 km this month"), not daily — the current daily-entry model fires false misses on rest days and can't track cumulative progress across a window. This change adds aggregate-period commitments so cycling targets accumulate from Strava data with a pace indicator, while daily commitments continue working unchanged.

---

## Project context (grounding for all roles)

### Relevant conventions
1. Schema changes require Alembic migration — never `create_all()`. Embedding column is JSONB in ORM but `vector(1024)` in DDL.
2. Tests run on SQLite, prod on PostgreSQL — all ORM types need `.with_variant()` for cross-DB compat (JSONB→JSON).
3. Every `/v1/*` route needs `@limiter.limit()` — no global fallback.
4. RLS enabled on all tables — new tables must include `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` in migration.
5. Commitment entries are pre-generated: `POST /v1/commitments` creates all `commitment_entries` rows upfront. Miss detection cron flips yesterday's pending→miss.
6. Strava webhook is public but HMAC-verified — in `_PUBLIC_PATHS`. POST validates HMAC-SHA256.
7. `strava_activities.strava_id` is UNIQUE — prevents duplicate inserts from webhook retries.
8. Commitment route params must be `uuid.UUID`, not `str` — SQLite stores UUIDs as 32-char hex.
9. `memory_items.tags` is JSONB with GIN index — colon-namespaced strings (e.g. `["training:weekly"]`).
10. `importance_score` is GENERATED — never UPDATE directly. Set `base_importance` or `dynamic_importance`.

### Architecture snapshot
**Commitment model** (`src/core/models.py`): `Commitment` has `name`, `exercise`, `daily_target` (int), `metric` (reps/minutes/tss), `start_date`, `end_date`, `status` (active/completed/abandoned). One-to-many `CommitmentEntry` rows (one per day, pre-generated), each with `logged_count`, `status` (pending/hit/miss). Unique constraint on `(commitment_id, entry_date)`.

**Strava pipeline** (`src/api/routes/strava.py`): Webhook receives activity events, HMAC-verified. `_fetch_and_upsert_activity()` hits Strava API, upserts into `strava_activities` table (`strava_id` UNIQUE). Handles create/update/delete events. `StravaActivity` stores `distance_m`, `duration_s`, `tss`, `avg_power_w`, `avg_hr`, `elevation_m`, `started_at`, `raw_data` JSONB.

**Miss detection** (`src/jobs/commitment_miss.py`): Nightly cron bulk-updates entries where `entry_date == yesterday AND status == pending` → `miss`. Only targets active commitments.

**API routes** (`src/api/routes/commitments.py`): CRUD + `/log` endpoint for daily logging. `_compute_streak` walks entries newest-first counting consecutive hits.

**Frontend** (`web/hooks/use-commitments.ts`, `web/components/dashboard/commitment-list.tsx`): `CommitmentCard` shows day counter, 7-day streak dots, log input buttons. `createCommitment` exists in hook but no creation form component exists yet (creation form is on Settings page per recent commit `b37d792`).

### Recent changes
- `b37d792` (2026-04-12): Added commitment creation form to Settings page (web)
- `0c6add6` (2026-04-12): Fixed migration to use JSONB for tags column with jsonb_ops GIN index
- `9ed1626` (2026-04-11): Added commitments, Strava webhook, pulse nutrition, tags — migration 0010
- Migrations currently at 0010. Commitment miss cron not yet scheduled in Docker.
- Strava OAuth token refresh is manual (tech debt T1).

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- The `Commitment` and `CommitmentEntry` models in `src/core/models.py` — full column definitions, constraints, relationships
- The `StravaActivity` model in `src/core/models.py` — all stored fields, especially `distance_m`, `tss`, `started_at`
- The Strava webhook handler in `src/api/routes/strava.py` — specifically `_fetch_and_upsert_activity()` and how create/update/delete events are processed
- The commitment routes in `src/api/routes/commitments.py` — the POST creation logic (entry pre-generation), the `/log` endpoint, and `_compute_streak`
- The miss detection job in `src/jobs/commitment_miss.py` — the query that selects entries to flip
- The commitment creation form on the Settings page (recent commit `b37d792`) — what fields it collects, how it calls `createCommitment`
- `web/hooks/use-commitments.ts` — the hook's API calls and state shape
- `web/components/dashboard/commitment-list.tsx` — `CommitmentCard` rendering, streak dots, log input
- All commitment tests: `tests/test_commitments.py`, `web/__tests__/hooks/use-commitments.test.ts`, `web/__tests__/components/commitment-list.test.tsx`
- The training sync pattern in `src/pipeline/training_sync.py` — as a reference for how Strava data syncs bypass the refinement queue

Also trace for each item:
- Where it is created
- Where it is mutated
- Where it is consumed
- Any related tests

Map the data flow end-to-end: Strava webhook → activity upsert → (new) progress accumulation → commitment status.

Produce a findings report with:
- Exact file paths
- Relevant code snippets
- Data flow description
- Your honest assessment of structure and quality

Note any surprises or mismatches vs the Architecture snapshot above.

Stop. Do not proceed to Role 2 until the findings report is complete.

---

## ROLE 2 — SKEPTIC

Read Role 1's findings report. Your job is to break its assumptions — but only with evidence.

### Grounding rules
- Every challenge must cite specific evidence from the Explorer's findings (file path, code snippet, data shape)
- Label each challenge: **HIGH** (contradicting evidence found), **MEDIUM** (ambiguous evidence), **LOW** (speculation)
- For LOW challenges: go back to the codebase and upgrade to MEDIUM/HIGH, or drop with "Insufficient evidence, not blocking"
- Do not carry LOW challenges forward to the Architect

Challenge specifically:
- Whether the existing `daily_target` (Integer) and single `metric` column can represent multiple metric targets (km + TSS) — or if the schema needs a fundamentally different shape for aggregate commitments
- Whether `CommitmentEntry` per-day rows make sense for aggregate commitments, or if they add unnecessary complexity when only the period total matters
- Whether `_fetch_and_upsert_activity()` in the Strava webhook handler returns enough data to link an activity to a commitment (does it know about commitments at all today?)
- Whether the miss detection cron's "yesterday's pending→miss" logic will incorrectly fire for aggregate commitments that span weeks/months
- Whether `_compute_streak` and the frontend's 7-day streak dots are safe when an aggregate commitment has no daily entries
- Whether Strava `update` and `delete` webhook events are handled in a way that allows progress rollback (decrementing cumulative totals)

Additionally challenge:
- Hidden dependencies or coupling
- Data shape assumptions
- Edge cases (null, async timing, partial state)
- Backward compatibility risks
- Missing or weak test coverage

For each challenge, label:
**HIGH** | **MEDIUM** | **LOW** → [upgraded/dropped]

For anything MEDIUM or HIGH:
- Revisit the codebase if needed
- Update findings with corrected understanding

Stop. Present the reconciled findings (HIGH and MEDIUM items only) before Role 3 begins.

---

## ROLE 3 — SENIOR ARCHITECT

Read the reconciled findings. Design the implementation. Do not write code yet.

Produce a concrete implementation plan covering:

1. **Schema evolution** — How to extend the `Commitment` model for aggregate type. Key decisions: add a `cadence` enum column (daily vs aggregate), a `targets` JSONB column for multi-metric targets (e.g. `{"km": 200, "tss": 400}`), and a `progress` JSONB column for cumulative actuals. Decide whether aggregate commitments still pre-generate `CommitmentEntry` rows or skip them entirely. Consider: a new `commitment_activities` junction table linking `commitment_id` ↔ `strava_activity.id` for dedup and audit trail.

2. **Strava webhook integration** — How the webhook handler connects activity ingestion to commitment progress. After upserting a `StravaActivity`, find all active aggregate commitments whose date window contains the activity's `started_at`, accumulate the relevant metrics, and update progress. Handle update events (recalculate from linked activities) and delete events (remove link, recalculate). Dedup by `strava_id` via the junction table.

3. **Pace calculation** — The formula for computing pace ratio on dashboard load. `pace_ratio = (actual / target) / (elapsed_days / total_days)`. Decide where this is computed: API response (server-side) vs frontend derivation. Consider multiple metrics — pace per metric, plus an overall indicator.

4. **Miss detection adaptation** — How to modify `src/jobs/commitment_miss.py` so it checks aggregate commitments only at window end, not daily. The cron runs nightly — it should check if `end_date == yesterday` for aggregate commitments, then compare cumulative progress vs targets. Daily commitments keep their existing per-day logic unchanged.

5. **API surface changes** — New/modified endpoints. `POST /v1/commitments` needs to accept `cadence` and `targets` for aggregate type. `GET /v1/commitments/{id}` response should include `progress`, `targets`, and `pace` for aggregate type. Consider whether `/log` should be disabled for aggregate commitments (Strava-only source).

6. **Frontend changes** — The commitment creation form (Settings page) needs a cadence toggle (daily vs aggregate) that shows different fields. `CommitmentCard` needs a variant for aggregate type: progress bars per metric, pace indicator (green/amber/red), no streak dots, no log buttons. The dashboard `CommitmentList` renders both types.

7. **Test plan**
- Backend: aggregate commitment creation with multi-metric targets, Strava webhook updating progress, dedup on duplicate webhook, update/delete event recalculation, miss detection at window end only, pace calculation accuracy, daily commitments unaffected
- Frontend: creation form cadence toggle, aggregate card rendering with pace indicator, edge cases (0% progress, 100%+, exactly on pace)
- Invariants: no double-counting, activities outside window ignored, daily commitments unchanged

8. **What stays unchanged**
- Daily commitment creation, entry pre-generation, `/log` endpoint, streak logic
- Strava webhook verification (HMAC) and activity upsert into `strava_activities`
- Miss detection for daily commitments (yesterday's pending→miss)
- Memory sync patterns (todo_sync, pulse_sync, training_sync)
- All other API routes and frontend pages

9. **Constraints & Safety**
- Migration must be additive (new columns nullable or with defaults, new table) — no breaking changes to existing rows
- Aggregate progress recalculation on update/delete should recompute from linked activities, not try to decrement (safer against race conditions)
- Pace calculation must handle division by zero (day 1 of window where elapsed = 0)
- Frontend must gracefully handle commitments with zero progress and commitments past deadline
- Rollback: migration is additive, so rollback = drop new columns/table. No data loss for existing commitments.

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

## ROLE 3.5 — SENIOR UI/UX EXPERT (conditional — included because this task has UI surface)

> This role requires the UI/UX Pro Max skill installed globally at `~/.claude/skills/ui-ux-pro-max/`.

Read the Architect's plan. Before any implementation begins, generate a design system for the UI components in this task.

### Step 1 — Generate design system
Run the design system generator with the project context:
```bash
python3 ~/.claude/skills/ui-ux-pro-max/scripts/search.py "personal productivity fitness tracker dashboard commitment progress" --design-system -p "Open Brain"
```

### Step 2 — Evaluate and adapt
Review the generated design system against:
- The existing UI patterns in the codebase (discovered by the Explorer): `CommitmentCard` with streak dots, progress bars, quick-log buttons; shadcn/ui components; Tailwind CSS; `text-base md:text-sm` mobile pattern
- The project's current design language: card-based layout, green/red/grey status colors for hit/miss/pending, flame emoji streak badge
- The Architect's plan constraints: aggregate cards need progress bars per metric, pace indicator, no streak dots or log buttons

**Consistency rule:** A new feature must look like it belongs in the existing app, not like a redesign. If the generated design system conflicts with established patterns:
- Keep existing color tokens, typography, and spacing
- Adopt only the recommendations that fill gaps (e.g., amber pace indicator, multi-metric progress bars, responsive breakpoints for wider progress display)

### Step 3 — Produce a design brief
Output a concise design brief for the Implementer containing:
- **Color tokens** — green (ahead of pace), amber (behind pace), red (missed/failed), grey (no data yet) — mapped to existing Tailwind classes where possible
- **Typography** — only if introducing new text styles not already in the system
- **Component patterns** — aggregate card layout: metric name + progress bar + percentage, pace indicator badge, deadline countdown, responsive stacking
- **Interaction patterns** — progress bar animation on data load, pace indicator tooltip showing exact ratio, empty state for new commitment with no activities yet
- **Anti-patterns** — avoid daily-style streak dots on aggregate cards, avoid manual log buttons on Strava-only commitments, avoid showing individual activity breakdown (keep it aggregate)
- **Pre-delivery checklist** — contrast ratios on pace indicators, `text-base md:text-sm` on any new inputs, cursor-pointer on interactive elements, reduced-motion support for progress bar animation

The Implementer treats this brief as a constraint alongside the Architect's plan.

Stop. Present the design brief before Role 4 begins.

---

## ROLE 4 — IMPLEMENTER

Read the architect's plan. Read the design brief from Role 3.5 — it is a binding constraint for all UI work.

Implement exactly as specified.

### Step 1 — Write tests first (mandatory)
Based on the Architect's test plan:
- Write backend tests in `tests/test_commitments.py` (extend existing file) covering: aggregate creation with multi-metric targets, Strava webhook progress update, dedup, update/delete recalculation, miss detection at window end, pace calculation, daily commitments unchanged
- Write frontend tests extending `web/__tests__/components/commitment-list.test.tsx` and `web/__tests__/hooks/use-commitments.test.ts` covering: aggregate card rendering, pace indicator colors, creation form cadence toggle
- Run the tests — confirm they fail for expected reasons (missing implementation)
- If they fail for unexpected reasons (import errors, broken setup), STOP and reconcile

### Step 2 — Alembic migration (0011)
- Add `cadence` column to `commitments` (String, default "daily" for backward compat)
- Add `targets` JSONB column to `commitments` (nullable, for aggregate multi-metric targets)
- Add `progress` JSONB column to `commitments` (nullable, for aggregate cumulative actuals)
- Create `commitment_activities` junction table (commitment_id FK, strava_activity_id FK, unique constraint on pair) for dedup and audit
- Enable RLS on new table
- Use `.with_variant()` for JSONB columns (JSON for SQLite)

### Step 3 — Backend models and API
- Update `Commitment` model with new columns
- Update `POST /v1/commitments` to accept aggregate cadence with `targets` dict — skip entry pre-generation for aggregate type
- Update `GET /v1/commitments/{id}` to include `progress`, `targets`, `pace` for aggregate type
- Disable `/log` for aggregate commitments (return 400)
- Add progress accumulation logic in Strava webhook handler: after activity upsert, find matching aggregate commitments, insert into junction table (ON CONFLICT ignore for dedup), recalculate progress from linked activities
- Handle Strava update events: recalculate from all linked activities (not incremental)
- Handle Strava delete events: remove junction row, recalculate

### Step 4 — Miss detection
- Modify `detect_misses()` to handle aggregate commitments: when `end_date == yesterday`, compare progress vs targets → mark commitment as completed or set status appropriately
- Keep daily miss logic unchanged

### Step 5 — Frontend
- Update creation form on Settings page: add cadence toggle, show metric targets fields for aggregate, show daily fields for daily
- Create `AggregateCommitmentCard` component: progress bars per metric, pace indicator badge, deadline info
- Update `CommitmentList` to render appropriate card type based on cadence
- Update `use-commitments.ts` hook if API response shape changes

### Step 6 — Integration verification
- Run full backend test suite (`make test`)
- Run frontend tests (`cd web && npm test`)
- Verify each convention from the Project Context checklist

After each step:
- Run the test suite (both new and existing tests)
- Fix any failures before continuing

### Final verification
- Run the full test suite
- Verify each convention from the Project Context checklist
- Validate: existing daily commitments (pushups, curls) work identically after the change
- Validate: no double-counting from duplicate Strava webhooks
- Validate: pace calculation handles edge cases (day 1, 100%+, exactly on pace)

Final check:
- Re-read the business context
- Verify the implementation matches the original intent
- Especially validate: daily commitments are completely unaffected — same creation, same entries, same miss detection, same streak logic, same frontend rendering

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
   - Review each MEDIUM and HIGH finding from Role 2
   - Is each concern addressed in the implementation, or consciously accepted with documented rationale?
   - Flag any item that was silently ignored

8. **Plan fidelity (cross-reference Role 3)**
   - Does the implementation match the Architect's plan?
   - Were any deviations from the plan justified and documented by the Implementer?
   - Flag any undocumented deviation as a scope issue

9. **Convention compliance (cross-reference Project Context)**
   - Does the implementation follow every convention listed in the Project Context checklist?
   - Flag any violation

10. **Design compliance (cross-reference Role 3.5)**
    - Does the implementation follow the design brief?
    - Are color tokens, spacing, and typography consistent with the brief and existing patterns?
    - Were anti-patterns avoided?
    - Does the new UI feel cohesive with existing screens?
    - Were pre-delivery checklist items satisfied?

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
- Strava webhook HMAC verification still covers the new progress-accumulation code path — no bypass possible
- The `commitment_activities` junction table can't be manipulated to inflate progress (e.g., linking an activity to a commitment it doesn't belong to date-wise)
- Pace calculation inputs can't cause division-by-zero or overflow in the API response
- New JSONB columns (`targets`, `progress`) are validated on input — no arbitrary JSON injection into the database
- Aggregate commitment creation validates date ranges (start_date <= end_date, start_date >= today)

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
