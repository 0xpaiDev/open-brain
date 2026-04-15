# Training Data Memory Integration — Multi-Agent

You will work through this task in sequential roles. Do not skip ahead.
Optional roles (marked "conditional") are included only when relevant — if absent, proceed to the next numbered role.
Review roles (5 and 6) may loop back for fixes, up to 2 cycles each.
The goal: All training data (commitments, Strava activities, weekly summaries) is searchable through the RAG memory system, background jobs are scheduled and running, and every operation is observable on the logs dashboard.

---

## Business context (read once, then put on your shelf)

Open Brain is a personal memory system that ingests natural-language data into PostgreSQL, refines it with Claude, embeds it with Voyage AI, and serves it through hybrid RAG search. The owner tracks fitness commitments (daily pushup challenges, monthly cycling targets) and Strava cycling data. Currently this training data lives in isolated tables — `commitments`, `commitment_entries`, `strava_activities` — invisible to the RAG system. When the user asks "how did my pushup challenge go?" the chat has no answer. Additionally, the commitment miss detection job exists in code but was never scheduled, and weekly training summaries require manual API calls. The fix: sync training data into `memory_items`, schedule the missing cron jobs, and ensure every operation logs to the dashboard.

---

## Project context (grounding for all roles)

### Relevant conventions
1. **Training sync bypasses refinement queue**: `src/pipeline/training_sync.py` follows the direct-create pattern (RawMemory + MemoryItem + embedding in one transaction). All new sync functions must follow this same pattern.
2. **`session.commit()` is required** — `flush()` alone does not persist. Every terminal operation must commit.
3. **`session.refresh(obj)` after commit** — server_default columns expire after flush. Access in async triggers MissingGreenlet.
4. **importance_score is GENERATED**: never UPDATE it directly. Set `base_importance` or `dynamic_importance`.
5. **Immutability**: Corrections create new `memory_items` with `supersedes_memory_id`. No soft deletes.
6. **memory_items.tags is JSONB with GIN index**: Array of colon-namespaced strings (e.g. `["training:weekly"]`). Use this for training data tags.
7. **Task gating**: Sources in `TASK_SKIP_SOURCES` (`src/pipeline/constants.py`) skip Task row creation. Training sources (`training-weekly`, `strava-activity`) should be listed here.
8. **Auto-capture importance capping**: Sources in `AUTO_CAPTURE_SOURCES` (`src/pipeline/constants.py`) have importance capped. Strava activities are auto-captured and should be listed here.
9. **Every `/v1/*` route needs `@limiter.limit()`**: no global fallback — undecorated routes are unprotected.
10. **Tests run on SQLite, prod on PostgreSQL**: all ORM types need `.with_variant()` for cross-DB compat.
11. **Commitment route params must be `uuid.UUID`, not `str`** — SQLite UUID hex mismatch.
12. **`run_tracked(job_name, job_fn)` wraps all scheduled jobs** — creates JobRun record, sends Discord DM on failure.

### Architecture snapshot

**Memory sync pipeline** (direct-create pattern, 3 existing implementations):
- `src/pipeline/todo_sync.py` → `sync_todo_to_memory()` — formats todo content → embed → RawMemory → MemoryItem → supersede old → commit
- `src/pipeline/pulse_sync.py` → `sync_pulse_to_memory()` — formats pulse data → same pattern
- `src/pipeline/training_sync.py` → `sync_weekly_training()` — aggregates week's commitments + Strava + nutrition → same pattern

**Models** (all in `src/core/models.py`):
- `Commitment` — name, exercise, daily_target, metric, cadence (daily/aggregate), targets/progress JSONB, start_date, end_date, status
- `CommitmentEntry` — commitment_id, entry_date, logged_count, status (pending/hit/miss)
- `CommitmentActivity` — junction: commitment_id ↔ strava_activity_id
- `StravaActivity` — strava_id (unique), activity_type, name, distance_m, duration_s, tss, avg_power_w, avg_hr, elevation_m, started_at, raw_data JSONB
- `RawMemory` — source, raw_text, metadata_ JSONB
- `MemoryItem` — raw_id FK, type, content, base_importance, embedding, tags JSONB, is_superseded
- `JobRun` — job_name, started_at, finished_at, status, error_message, duration_seconds

**Scheduler**: Supercronic in Docker (`openbrain-scheduler`), reads `crontab` file. Currently 3 jobs: pulse (05:00 UTC), importance (01:00 UTC), synthesis (Sunday 00:00 UTC).

**Strava webhook**: `POST /v1/strava/webhook` → `_fetch_and_upsert_activity()` → `_link_activity_to_commitments()`. Activities stored in `strava_activities` table, linked to aggregate commitments via `commitment_activities` junction.

**Job monitoring**: `run_tracked()` in `src/jobs/runner.py` → creates `JobRun` row → exposed via `GET /v1/jobs/status` and `GET /v1/jobs/history`. Web dashboard at `/logs` reads these endpoints.

### Recent changes
- 2026-04-12: Aggregate commitments with Strava progress tracking shipped (migration 0012, `commitment_activities` junction, `_link_activity_to_commitments()`)
- 2026-04-12: Strava TSS calculation from normalized power and FTP
- 2026-04-11: Strava OAuth token auto-refresh with DB-backed store
- PROGRESS.md explicitly lists "commitment_miss cron not yet wired" as tech debt item T2

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- `src/jobs/commitment_miss.py` — the `detect_misses()` function, how it uses `run_tracked()`, what SQL it runs, how it logs
- `src/pipeline/training_sync.py` — the `sync_weekly_training()` function end-to-end, how it formats content, creates RawMemory + MemoryItem, handles superseding
- `src/api/routes/strava.py` — the webhook handler, `_fetch_and_upsert_activity()`, `_link_activity_to_commitments()`, and `update_commitment_progress()`
- `src/pipeline/constants.py` — `AUTO_CAPTURE_SOURCES` and `TASK_SKIP_SOURCES` sets
- `src/jobs/runner.py` — `run_tracked()` implementation, how it creates JobRun records and handles errors
- `crontab` file — current scheduled jobs and their timing
- `src/pipeline/todo_sync.py` and `src/pipeline/pulse_sync.py` — the direct-create sync pattern (embedding + RawMemory + MemoryItem)
- `src/core/models.py` — Commitment, CommitmentEntry, StravaActivity, RawMemory, MemoryItem models
- `src/api/routes/training.py` — the manual `/v1/training/weekly-sync` endpoint
- `src/llm/embeddings.py` or wherever `embed_text()` lives — its signature and how it's called from sync functions

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
- That `run_tracked()` can be used standalone from a new job file (does it require database session setup, Voyage client init, or other bootstrapping beyond what `commitment_miss.py` already does?)
- That the direct-create pattern from `training_sync.py` can be reused for individual Strava activities without modification (different data shape, different superseding logic — activities don't have a "week_start" key)
- That adding a Strava activity memory sync inside the existing webhook handler won't impact webhook response time (Strava expects fast responses, embedding calls take time)
- That the `embed_text()` function is available at job-execution time (does it need a Voyage client that's only initialized in certain contexts?)
- That commitment summary generation can reuse `sync_weekly_training()` data-gathering logic or if commitment stats need separate calculation

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

1. **Schedule commitment_miss cron job** — Add entry to `crontab`, verify `detect_misses()` already uses `run_tracked()`, confirm it will show on the logs dashboard. Decide timing (must run after midnight in user's timezone, before morning pulse).

2. **Schedule weekly training summary cron job** — Create a new job file `src/jobs/training_weekly.py` that calls `sync_weekly_training()` wrapped in `run_tracked()`. Add crontab entry. Decide timing (after synthesis? before? same day?). The manual API endpoint stays for ad-hoc runs.

3. **Commitment summary sync on completion** — Design a new function in `src/pipeline/training_sync.py` (or new file) that generates a rich end-of-commitment memory when a commitment transitions to "completed". Decide: where is this triggered (inside `detect_misses()` when it completes aggregate commitments? as a separate post-completion hook? in the commitment PATCH endpoint?). Define the content format, base_importance, tags, and superseding strategy. Must use `run_tracked()` or be called within a tracked job.

4. **Strava activity memory sync** — Design a new function in `src/pipeline/` that syncs a `StravaActivity` row into `memory_items`. Define: content format (natural-language summary of the ride/run with key metrics), base_importance, tags (e.g. `["training:strava", "strava:ride"]`), superseding strategy for activity updates. Decide: trigger point (inside webhook handler after `_fetch_and_upsert_activity()`? if so, handle the latency concern from the Skeptic). Add `"strava-activity"` to `AUTO_CAPTURE_SOURCES` and `TASK_SKIP_SOURCES` in `constants.py`.

5. **Test plan**
- Test `detect_misses()` scheduling produces JobRun records (may already have tests — check)
- Test `sync_weekly_training()` as a scheduled job produces JobRun records
- Test commitment summary generation: mock a completed commitment with entries, verify RawMemory + MemoryItem created with correct content, tags, importance
- Test Strava activity sync: mock a StravaActivity, verify RawMemory + MemoryItem created, verify superseding on activity update
- Test Strava activity sync handles missing optional fields (null tss, null avg_power_w)
- Test that `AUTO_CAPTURE_SOURCES` and `TASK_SKIP_SOURCES` contain the new sources
- The Implementer will write these tests FIRST, before any production code

6. **What stays unchanged**
- `commitment_miss.py` logic (only adding crontab entry, not modifying the job itself — unless commitment summary hook needs to be added)
- `training_sync.py::sync_weekly_training()` existing function (only adding new functions alongside it)
- Strava webhook verification and token management
- All existing memory sync patterns (todo_sync, pulse_sync)
- Database schema (no migrations — all tables exist)
- Frontend/dashboard (it already reads `job_runs`)

7. **Constraints & Safety**
- **Webhook latency**: Strava expects webhook responses within seconds. If embedding takes too long, the sync must be fire-and-forget (log failure, don't block response). Consider: can the sync be deferred to a queue/background task, or is the embed fast enough inline?
- **Embedding cost**: Each Strava activity sync costs one Voyage AI embedding call. At typical activity volume (1-3/day), this is negligible. But batch imports could spike — consider rate awareness.
- **Idempotency**: Activity updates from Strava (same strava_id, new data) must supersede the old memory, not create duplicates. Use `RawMemory.metadata_["strava_activity_id"]` for lookup.
- **No schema changes**: All required tables and columns exist. No migrations.
- **Failure isolation**: Each sync operation is best-effort (wrapped in try/except). A failed Strava memory sync must not prevent the activity from being stored or linked to commitments.
- **Rollback**: All changes are additive (new crontab entries, new sync functions). Rollback = remove crontab entries and revert code. No data migration to undo.

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

Read the architect's plan.

Implement exactly as specified.

### Step 1 — Write tests first (mandatory)
Based on the Architect's test plan:
- Write test file(s) covering all specified contracts, edge cases, and invariants
- Follow the project conventions listed in the Project Context section above
- Run the tests
- Confirm they fail for the expected reasons (missing implementation)
- If they fail for unexpected reasons (import errors, broken setup, wrong assumptions), STOP and reconcile before continuing

### Step 2 — Strava activity memory sync function
- Create the new sync function following the direct-create pattern from `todo_sync.py`/`pulse_sync.py`
- Register `"strava-activity"` in `AUTO_CAPTURE_SOURCES` and `TASK_SKIP_SOURCES` in `constants.py`
- Run tests, confirm they pass

### Step 3 — Commitment summary generation function
- Create the commitment summary sync function
- Format rich natural-language content: completion rate, streaks, daily breakdown, pace against target
- Wire it into the commitment completion flow (wherever the Architect decided)
- Run tests, confirm they pass

### Step 4 — Schedule commitment_miss cron job
- Add entry to `crontab`
- Verify `detect_misses()` already creates JobRun via `run_tracked()`
- If commitment summary hook was designed to trigger from `detect_misses()`, add it here
- Run tests

### Step 5 — Schedule weekly training summary cron job
- Create `src/jobs/training_weekly.py` (or equivalent)
- Add crontab entry
- Run tests, confirm they pass

### Step 6 — Wire Strava activity sync into webhook handler
- Add the sync call after `_fetch_and_upsert_activity()` in the webhook handler
- Wrap in try/except for failure isolation
- Handle the update and delete event types (supersede on update, mark superseded on delete)
- Run tests

### Final verification
- Run the full test suite (`make test` and `cd web && npm test`)
- Verify each convention from the Project Context checklist
- Validate outputs/logs for correctness: check that new sources appear in constants, new jobs appear in crontab

Final check:
- Re-read the business context
- Verify the implementation matches the original intent
- Especially validate: every sync operation creates a `RawMemory` + `MemoryItem` with embedding, every scheduled job uses `run_tracked()`, and the strava webhook handler remains fast and failure-isolated

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
- **Strava webhook handler modification**: the sync call runs inside a public endpoint. Verify it can't be exploited to trigger excessive embedding calls (cost amplification) via crafted webhook events.
- **Memory content from external data**: Strava activity names and data flow into `memory_items.content` which feeds into LLM prompts during RAG search. Verify no prompt injection vector from Strava activity names/descriptions.
- **Job scheduling**: New cron entries run as the scheduler container's user. Verify no privilege escalation or command injection via job parameters.

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
