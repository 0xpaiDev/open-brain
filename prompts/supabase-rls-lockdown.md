# Supabase RLS Lockdown — Multi-Agent

You will work through this task in six roles, sequentially. Do not skip ahead.
Review roles (5 and 6) may loop back for fixes, up to 2 cycles each.
The goal: Every table in the Supabase database will have Row-Level Security enabled with deny-all policies, ensuring no data is publicly accessible via the Supabase REST/Realtime APIs while preserving full access for the application's direct PostgreSQL connection.

---

## Business context (read once, then put on your shelf)

Open Brain is a single-user personal memory system backed by a Supabase-hosted PostgreSQL database. It has 15+ tables storing personal knowledge, decisions, tasks, todos, and conversation history. All application access goes through a FastAPI backend authenticated by API key — the app never uses the Supabase client SDK or REST API. However, Supabase exposes every table without RLS via its auto-generated PostgREST API, meaning anyone who knows the project URL can read, edit, and delete all data. This is a critical security vulnerability flagged by Supabase's own security advisor on 2026-04-07.

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- All table definitions in `src/core/models.py` — enumerate every table name and its purpose
- All Alembic migration files in `alembic/versions/` — understand the current schema state (migrations 0001–0008)
- The database connection setup in `src/core/database.py` — how the app connects (connection string, SSL, pooling)
- The Supabase project configuration — check `.env.example`, any Supabase client usage, PostgREST or Realtime references
- Any existing SQL policies, RLS mentions, or security-related database code anywhere in the project
- The `alembic/env.py` file — understand how migrations are run (async? target metadata?)

Also trace for each item:
- Where it is created
- Where it is mutated
- Where it is consumed
- Any related tests

Map the data flow end-to-end where applicable.

Produce a findings report with:
- Exact file paths
- Complete list of all 15+ table names
- Relevant code snippets from the migration infrastructure
- Data flow description (app -> SQLAlchemy -> asyncpg -> Supabase direct connection)
- Your honest assessment of structure and quality

Note any surprises or mismatches vs expectations.

Stop. Do not proceed to Role 2 until the findings report is complete.

---

## ROLE 2 — SKEPTIC

Read Role 1's findings report. Your job is to break its assumptions.

Challenge specifically:
- That the application only uses direct PostgreSQL connections — are there any Supabase JS client imports, `supabase-py` usage, or PostgREST calls that would break under a deny-all RLS policy?
- That a deny-all policy is sufficient — could the Supabase `service_role` key be in use anywhere, which bypasses RLS? Is the app connecting as `postgres` user (bypasses RLS) or as an authenticated role?
- That adding RLS via Alembic migration is safe — will `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` interact badly with existing HNSW indexes, GENERATED columns, or composite primary keys?
- That no Supabase features depend on table access — are Supabase Edge Functions, Realtime subscriptions, Storage, or Auth features in use that need table-level access?
- That the migration can be applied without downtime — what happens to in-flight queries from the worker or Discord bot during the migration?

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

1. **RLS Policy Strategy** — Decide between deny-all (no policy = deny when RLS enabled) vs explicit deny-all policy vs authenticated-role policy. For a single-user system using direct postgres connection, the simplest correct approach matters. Justify the choice.

2. **Migration Approach** — Design an Alembic migration (0009) that enables RLS on every table. Decide whether to use raw SQL `op.execute()` statements or if there's a better mechanism. Consider ordering: should RLS be enabled on all tables in a single migration or staged?

3. **Connection Role Verification** — Determine what database role the application connects as. If it's `postgres` (superuser), RLS is bypassed automatically and no application changes are needed. If it's a non-superuser role, policies granting access to that role must be created. This is the single most critical architectural decision.

4. **Testing Strategy** — Design verification that RLS is active: a test or script that attempts access via the Supabase REST API (anon key) and confirms denial. Also ensure existing pytest suite still passes (SQLite-based tests won't exercise RLS, but must not break).

5. **What stays unchanged**
- Application code (`src/api/`, `src/pipeline/`, `src/discord/`) — no changes needed if connecting as superuser
- Existing migrations 0001–0008
- The SQLite test database setup
- API authentication middleware (this is defense-in-depth, not a replacement)

6. **Constraints & Safety**
- The migration must be idempotent — re-running should not error if RLS is already enabled
- `importance_score` is a GENERATED column — verify `ENABLE ROW LEVEL SECURITY` doesn't interact with it
- HNSW and GIN indexes must remain functional after RLS is enabled
- The worker uses `SELECT FOR UPDATE SKIP LOCKED` on `refinement_queue` — verify this still works with RLS
- Rollback: `ALTER TABLE ... DISABLE ROW LEVEL SECURITY` is the clean reverse
- Zero downtime: RLS enable is a metadata change, not a table rewrite — should be instant

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
1. Verify the database connection role by checking `src/core/config.py` and `.env.example` for the connection string format — confirm it uses `postgres` superuser
2. Create Alembic migration `0009_enable_rls_all_tables.py` that enables RLS on every table using `op.execute()` with proper upgrade/downgrade
3. Run the existing test suite (`make test`) to ensure no regressions
4. If the architect's plan calls for explicit policies (non-superuser role), implement those as part of the migration
5. Add a verification note or script documenting how to confirm RLS is active via Supabase dashboard or SQL query

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
- Especially validate: every single table has RLS enabled — missing even one table leaves that table fully exposed

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
- **CRITICAL IMPLEMENTATION issues** -> return to ROLE 4 with explicit fixes required. After fixes, return here (ROLE 5) and increment review cycle.
- **CRITICAL ARCHITECTURAL issues** -> return to ROLE 3 with the specific concern. After ROLE 3 revises the plan, ROLE 4 re-implements the affected parts, then return here (ROLE 5) and increment review cycle.
- **Review cycle 2 with unresolved CRITICAL issues** -> mark the task **BLOCKED**. List all unresolved issues with context. Stop — these need human decision-making.
- **No CRITICAL issues** -> proceed to ROLE 6.

---

## ROLE 6 — SECURITY REVIEWER

Review the entire implementation through a security lens.

**Review cycle: 1 of 2 maximum.**

Evaluate for this task specifically:
- **Table coverage completeness** — Verify every single table in `src/core/models.py` has RLS enabled in the migration. A missed table means that table's data is fully public. Cross-reference the model definitions against the migration's `ALTER TABLE` statements.
- **PostgREST bypass vectors** — Even with RLS enabled, check whether the Supabase `anon` key or `service_role` key could still access data through other channels (Storage, Edge Functions, Realtime). Confirm no Supabase client SDK is used in the codebase.
- **Migration rollback safety** — Verify the downgrade path actually works and doesn't leave the database in a partially-secured state. A failed migration that enables RLS on some tables but not others is worse than no RLS (false sense of security).
- **Connection role audit** — Confirm the production connection role. If it's `postgres` (superuser), RLS is transparently bypassed for the app. If it's any other role, the app will be locked out of its own data without explicit GRANT/POLICY statements.

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
