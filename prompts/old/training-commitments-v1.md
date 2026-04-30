# Training & Commitments V1 — Multi-Agent

The goal: A training accountability system with commitment challenges, Strava webhook integration, morning pulse nutrition check-in, weekly training summaries synced to memory, and a tag system — all visible on the dashboard alongside todos.

## Session boundaries

This prompt is too large for a single context window. Execute in two sessions:

**Session 1 — Design (Roles 1–3.5)**
Run Roles 1 through 3.5. At the end, write the consolidated output to `prompts/training-commitments-v1-plan.md` containing:
- Explorer findings report (file paths, code snippets, data flows)
- Skeptic reconciled findings (HIGH/MEDIUM items only)
- Architect implementation plan (all 11 sections)
- UI/UX design brief (from Role 3.5)

End the session after writing the plan file.

**Session 2 — Implementation (Roles 4–6)**
Start by reading `prompts/training-commitments-v1-plan.md` and this prompt's Business Context and Project Context sections. Then execute Roles 4 through 6. The plan file is your single source of truth — do not re-explore the codebase except to verify specific details during implementation.

---

Review roles (5 and 6) may loop back for fixes, up to 2 cycles each.

---

## Business context (read once, then put on your shelf)

Open Brain is a personal async memory system with a PostgreSQL backend, FastAPI API, and a Next.js dashboard. It ingests natural language, refines it via Claude/Voyage AI, and stores structured knowledge for hybrid retrieval (RAG). The system already tracks todos and daily pulse check-ins. This change adds a training accountability layer: commitment challenges (daily exercise targets with streak tracking), automatic Strava activity ingestion, lightweight nutrition logging in the morning pulse, weekly training summaries ingested into the memory pool for RAG queryability, and a general-purpose tag system. The user is a solo dev who cycles and does bodyweight training — this system must be in his face daily to drive behavior, not buried in a menu.

---

## Project context (grounding for all roles)

### Relevant conventions

1. Every `/v1/*` route needs `@limiter.limit()` — no global fallback; undecorated routes are unprotected
2. `importance_score` is GENERATED — never UPDATE it directly; set `base_importance` or `dynamic_importance`
3. Immutability: `raw_memory` is append-only; corrections create new `memory_items` with `supersedes_memory_id`
4. All ORM types need `.with_variant()` for cross-DB compat (JSONB→JSON, Vector→JSON) — tests run on SQLite, prod on PostgreSQL
5. RLS enabled on all tables — new tables must include `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` in their migration
6. `session.commit()` is required — `flush()` alone does not persist; `session.refresh(obj)` after commit for server_default columns
7. Prompt injection defense: all user input wrapped in `<user_input>...</user_input>` delimiters in LLM prompts
8. Settings from env only — no config files; `SecretStr` for API keys
9. Auto-capture sources have importance capped via `AUTO_CAPTURE_SOURCES` in `src/pipeline/constants.py`; task-skip sources in `TASK_SKIP_SOURCES`
10. Memory ingest lives in `src/api/services/memory_service.py` — do not re-inline dedup/RawMemory/RefinementQueue logic
11. Mobile input font-size >= 16px — use `text-base md:text-sm` pattern
12. `memory_type` uses underscores (not hyphens) — frontend `TYPE_CONFIG` keys must match
13. Git commit format: `type(scope): description`
14. Alembic for migrations, never `create_all()` — embedding column is JSONB in ORM but `vector(1024)` in DDL

### Architecture snapshot

**Backend**: FastAPI app (`src/api/`) with routes in `src/api/routes/`, services in `src/api/services/`. Worker pipeline in `src/pipeline/`. Models in `src/core/models.py`. Config in `src/core/config.py`. Cron jobs in `src/jobs/`.

**Database**: Supabase PostgreSQL with 18 tables. Key tables for this task:
- `memory_items` — refined knowledge with embeddings, importance scores, `project` soft-reference field
- `raw_memory` — append-only input log (required for memory ingest flow)
- `daily_pulse` — one row per day; columns for sleep_quality, energy_level, wake_time, parsed_data (JSONB), notes, status
- `todo_items` — existing task management; dashboard shows these in `TaskList` component
- `job_runs` — execution log for cron jobs

**Frontend**: Next.js app in `web/`. Dashboard at `web/app/dashboard/page.tsx` renders `MorningPulse`, `CalendarStrip`, `TaskList`, `OverdueModal`. Settings page at `web/app/settings/page.tsx`. Hooks in `web/hooks/`. Components in `web/components/`.

**Memory ingest flow**: `POST /v1/memory` → `memory_service.ingest_memory()` → `raw_memory` + `refinement_queue` → worker pipeline → `memory_items` with embedding. Todo/pulse sync modules in `src/pipeline/todo_sync.py` and `src/pipeline/pulse_sync.py` follow the same best-effort pattern.

**Cron jobs**: Importance (3 AM daily), synthesis (2 AM Sunday), pulse (7 AM daily). Run as separate Docker services via host cron.

### Recent changes

- 2026-04-11: Todo edit + hard-delete with `supersede_memory_for_todo()` pattern
- 2026-04-11: Web voice unification — `SmartComposer` voice tab posts to `POST /v1/voice/command`
- 2026-04-10: Voice intent classifier broadened for Siri dictation variety
- Tech debt M1: `sync_todo_to_memory()` doesn't wire `supersedes_memory_id` pointer (low impact)

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:

- The `DailyPulse` model in `src/core/models.py` and the pulse routes in `src/api/routes/pulse.py` — understand how pulse data is submitted (especially the web modal flow via `PATCH /v1/pulse/today`) and what columns exist for extending with nutrition fields
- The `MorningPulse` dashboard component (`web/components/dashboard/morning-pulse.tsx`) and the pulse hook (`web/hooks/use-pulse.ts` or similar) — understand the current modal fields and submission flow
- The `memory_service.ingest_memory()` function in `src/api/services/memory_service.py` — understand the shared ingest helper and how to create memory items programmatically (for weekly training summary)
- The `todo_sync.py` and `pulse_sync.py` in `src/pipeline/` — understand the sync-to-memory pattern (best-effort try/except wrapping) that the training weekly sync should follow
- The dashboard page (`web/app/dashboard/page.tsx`) and `TaskList` component — understand the layout and component composition pattern for adding a new Commitments section
- The settings page (`web/app/settings/page.tsx`) — understand the current settings UI for adding commitment creation
- The existing Alembic migrations in `alembic/versions/` — understand naming and RLS patterns (especially migration 0009 for RLS)
- `src/pipeline/constants.py` — understand `AUTO_CAPTURE_SOURCES` and `TASK_SKIP_SOURCES` for registering new sources
- `src/core/config.py` — understand settings pattern for adding Strava OAuth credentials

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

- **DailyPulse column extension safety**: Adding `clean_meal` and `alcohol` boolean columns to `daily_pulse` — will existing pulse records (with NULL) break any downstream parsers or the web modal submission? Does `PATCH /v1/pulse/today` blindly overwrite all fields or only submitted ones?
- **Tag storage on memory_items**: The spec calls for colon-namespaced tags. Does `memory_items` have a tags column? If not, is the `parsed_data` JSONB or `project` field being used for categorization, and would adding a tags array column conflict with the existing schema?
- **Strava webhook verification**: Strava's webhook subscription requires a GET verification endpoint that echoes a `hub.challenge` token. This endpoint must be publicly reachable and cannot use API key auth. Does the existing middleware (`X-API-Key` on all `/v1/*`) allow exempting specific routes?
- **Commitment "miss" detection timing**: The spec says "day ends, it's a miss." What timezone does the system use for day boundaries? `daily_pulse` uses `pulse_date` — is there a precedent for timezone-aware day rollovers, or will the cron job need to handle this?
- **Weekly sync job and the ingest pipeline**: The weekly training summary is ingested as a memory item. Will it flow through the full refinement pipeline (Claude extraction + Voyage embedding)? The summary is already structured — double-processing through Claude extraction could mangle it. Check if `ingest_memory()` has a way to skip extraction or pass pre-structured data.

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

Read the reconciled findings from Roles 1 and 2. Design the implementation from scratch based on what was actually discovered in the codebase. Do not write code yet.

### What you're designing for

These are the business requirements — the *what*, not the *how*. Design the best technical solution given what the Explorer found.

**Commitment system**: Users create time-bound challenges (exercise name, daily target, duration). System generates a daily entry for each day. Each day is either completed (with a logged count) or missed — no defer. Partial logging within the day (e.g., 10 in morning + 10 later). Streak/miss history visible on the commitment card.

**Dashboard visibility**: Commitments section on the main dashboard alongside todos. Each active commitment shows as a card: name, progress (Day X/Y), streak visualization, today's status. Weekly goal commitments (e.g., TSS target) show a progress bar filled by Strava data.

**Strava webhook**: Receive activity events on ride completion. Extract and store structured metrics (distance, duration, TSS, power, HR, elevation). Stored data feeds weekly goal progress on commitment cards.

**Pulse nutrition check-in**: Add two binary fields to the morning pulse: clean/cheat meal day, alcohol yes/no. Two taps. Stored for future analysis, not displayed beyond the check-in itself in V1.

**Weekly training sync to memory**: Weekly process (cron or manual trigger for MVP) summarizes the week's commitments, training metrics, and check-in data. Ingested as a single memory item so RAG can answer questions like "how was my training last month."

**Tag system**: Colon-namespaced tags (`training:strava`, `training:commitment`, etc.) on memory items. General-purpose — same pattern for any future domain.

### Hard constraints (non-negotiable)

- New tables must have RLS enabled in the migration (project convention)
- New `/v1/*` routes must have `@limiter.limit()` (no global fallback)
- ORM types must use `.with_variant()` for SQLite test compat
- Strava webhook verification endpoint must be publicly reachable (no API key auth)
- New columns on existing tables must be nullable (backward compatibility)
- Memory ingest must go through `memory_service.ingest_memory()` — do not re-inline the dedup/queue logic
- This is a single-user system — no multi-tenancy concerns

### Your deliverables

Produce a concrete implementation plan. For each area, provide your reasoning — if multiple approaches exist, list them and justify the chosen one. The plan must cover:

1. **Data model** — new tables and any extensions to existing tables. Design the schema based on the Explorer's findings about existing patterns (UUID PKs, index strategy, JSONB usage, relationship patterns). Address how commitment entries relate to the challenge definition, and how Strava activities feed into weekly metric commitments.

2. **Migration strategy** — how many migrations, what goes in each, reversibility.

3. **API design** — endpoints for commitment CRUD, logging, Strava webhooks, training data access, and weekly sync. Decide how to handle the Strava webhook auth exemption based on how the existing API key middleware actually works (from Explorer findings).

4. **Strava integration** — webhook verification flow, event processing, activity detail fetching, OAuth token management, deduplication strategy, rate limiting approach.

5. **Weekly training sync** — how to summarize the week's data and ingest it as a memory item. Address the Skeptic's concern about whether the summary should flow through the full refinement pipeline or bypass extraction.

6. **Tag system** — storage mechanism, indexing, query pattern, and how tags are applied during the weekly sync.

7. **Frontend** — dashboard commitments section, commitment creation UI, pulse modal extension. Design based on Explorer's findings about existing component patterns and layout structure.

8. **Cron jobs** — commitment miss detection (marking uncompleted days), weekly sync scheduling. Address timezone handling based on how existing cron jobs (pulse, importance) handle day boundaries.

9. **Test plan** — what contracts must be tested, what invariants must hold. The Implementer writes these FIRST.

10. **What stays unchanged** — explicitly list what must not be touched.

11. **Constraints & safety** — performance, backward compatibility, failure modes, rollback strategy.

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
python3 ~/.claude/skills/ui-ux-pro-max/scripts/search.py "fitness tracker commitment dashboard training accountability" --design-system -p "Open Brain"
```

### Step 2 — Evaluate and adapt
Review the generated design system against:
- The existing UI patterns in the codebase (discovered by the Explorer): Material Design 3 tokens (primary, on-surface-variant), `font-headline` typography, card-based layout in dashboard, `MorningPulse` expandable card pattern, `TaskList` list-based layout
- The project's current design language: Tailwind CSS with custom color tokens, shadcn/ui base components (`input.tsx`, `textarea.tsx`, `select.tsx`), responsive `text-base md:text-sm` pattern
- The Architect's plan constraints: commitment cards must sit naturally between CalendarStrip and TaskList

**Consistency rule:** A new feature must look like it belongs in the existing app, not like a redesign. If the generated design system conflicts with established patterns:
- Keep existing color tokens, typography, and spacing
- Adopt only the recommendations that fill gaps (e.g., streak visualization pattern, progress bar styling, toggle component for pulse)

### Step 3 — Produce a design brief
Output a concise design brief for the Implementer containing:
- **Color tokens** — mapped to existing CSS variables where they exist, new tokens only if needed (e.g., streak-hit green, streak-miss red)
- **Typography** — only if introducing new text styles not already in the system
- **Component patterns** — commitment card layout, streak visualization (checkmarks/crosses in a row), progress bar for weekly metrics, log input (number entry), binary toggle for pulse nutrition fields
- **Interaction patterns** — tap to log reps (number input with quick-add buttons?), streak animation, progress bar fill transition, pulse toggle haptic feedback consideration
- **Anti-patterns** — avoid complex multi-step logging flows (must be < 2 taps), avoid hiding streak history behind navigation, avoid using color alone for hit/miss (accessibility)
- **Pre-delivery checklist** — contrast ratios on streak indicators, cursor-pointer on log buttons, focus states on inputs, reduced-motion support for progress bar animations, 16px minimum input font size

The Implementer treats this brief as a constraint alongside the Architect's plan.

Stop. Present the design brief before Role 4 begins.

### End of Session 1

Write the consolidated plan to `prompts/training-commitments-v1-plan.md` containing all four outputs (Explorer findings, Skeptic reconciliation, Architect plan, Design brief). This file is the handoff artifact for Session 2. End the session here.

---

## ROLE 4 — IMPLEMENTER

> **Session 2 starts here.** Read `prompts/training-commitments-v1-plan.md` and this prompt's Business Context and Project Context sections before proceeding.

Read the Architect's plan. If Role 3.5 produced a design brief, read that too — it is a binding constraint for all UI work.

Implement exactly as the Architect specified. The plan is your work order — follow its structure, sequencing, and decisions. Do not freelance.

### Step 1 — Write tests first (mandatory)
Based on the Architect's test plan (section 9):
- Write test files covering all specified contracts, edge cases, and invariants
- Follow project conventions: pytest + pytest-asyncio for backend (SQLite test DB), Vitest for frontend
- Run the tests
- Confirm they fail for the expected reasons (missing implementation)
- If they fail for unexpected reasons (import errors, broken setup, wrong assumptions), STOP and reconcile before continuing

### Step 2+ — Implement production code
Work through the Architect's plan in order, starting with the lowest-risk foundational layer (typically: migration → models → backend routes → services → jobs → frontend).

After each logical step:
- Run the test suite (both new and existing tests)
- Fix any failures before continuing

### Final verification
- Run the full test suite (`make test` + `cd web && npm test`)
- Verify each convention from the Project Context checklist (all 14 items)
- Perform manual verification where applicable (create a commitment, log reps, check dashboard, submit pulse with new fields)
- Validate that existing tests still pass (no regressions)

Final check:
- Re-read the business context
- Verify the implementation matches the original intent
- Especially validate: commitments are visible on the dashboard alongside todos, not buried in a sub-page

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

- **Strava webhook endpoint exposure**: The GET verification and POST event endpoints bypass API key auth. Verify that POST validates the Strava webhook signature (`X-Hub-Signature` header with HMAC-SHA256 of the body using the verify token). Ensure no other routes are accidentally unprotected.
- **Strava OAuth token storage**: If stored in env vars, verify `SecretStr` usage and no raw logging. If stored in DB, verify encryption at rest and no exposure via API responses.
- **Tag injection via memory items**: Tags are user-influenced strings (set during weekly sync, but future: user-settable). Verify JSONB storage doesn't allow SQL injection via crafted tag values. Verify tag values are validated (length, charset).
- **Commitment entry manipulation**: Verify that logging counts cannot go negative, cannot exceed reasonable bounds, and that completed entries cannot be re-opened by re-logging.
- **Rate limiting on new endpoints**: Verify all new `/v1/*` routes have `@limiter.limit()`. Pay special attention to Strava webhook (needs to accept bursts but not be abusable) and commitment log (user-facing, moderate limit).

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
