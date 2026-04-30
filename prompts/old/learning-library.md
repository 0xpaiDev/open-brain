# Learning Library — Multi-Agent

You will work through this task in sequential roles. Do not skip ahead.
Optional roles (marked "conditional") are included only when relevant — if absent, proceed to the next numbered role.
Review roles (5 and 6) may loop back for fixes, up to 2 cycles each.
The goal: a personal learning library (Topic → Section → Item) with a morning cron that injects 2–3 learning todos into /today from active topics, and a /learning page to groom and review the curriculum — none of which exists today.

---

## Business context (read once, then put on your shelf)

Open-brain is Shu's personal knowledge + productivity system: memory ingestion, RAG chat, daily pulse, todos, training sync. It was built incrementally and there's no structured way to revisit or extend understanding of the stack itself, nor any place to track a broader learning agenda (books, frameworks, concepts). This feature adds a Learning Library: a groomed hierarchy of topics and items that feeds deliberate learning into each day's todo list via a morning cron. It must coexist with the existing todo flow without changing how regular todos behave. See `docs/learning-library-business-case.md` for full requirements.

---

## Project context (grounding for all roles)

### Relevant conventions

1. **Migration discipline** — add a new Alembic migration (next is `0013_learning_library.py`). Enable RLS on every new table: `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` (no policies — app connects as `postgres`).
2. **Cross-DB types** — tests run on SQLite. JSONB must use `JSONB().with_variant(JSON(), "sqlite")`; UUID PKs stored as 32-char hex on SQLite. Route params must be `uuid.UUID`, not `str`.
3. **Terminal ops commit** — every async write path ends in `session.commit()`. `flush()` alone does not persist. `session.refresh()` after commit for server-default columns.
4. **Rate limiting** — every `/v1/*` route needs `@limiter.limit(...)`; no global fallback.
5. **LLM prompt hygiene** — wrap user-supplied text in `<user_input>...</user_input>`. When resolving relative dates, inject `date.today()` into the system prompt (Haiku cutoff gotcha). Reuse `src/llm/prompts.py::build_voice_create_system_prompt` pattern. Use `claude-haiku-4-5-20251001` for the cron.
6. **Cron registration** — cron jobs live in `src/jobs/`, wrapped with `run_tracked(name, coro)` from `src/jobs/runner.py`. Schedule via `crontab` file (supercronic, UTC).
7. **Idempotency** — the learning cron must be safe to re-run same day. Check for existing learning todos for today before creating new ones.
8. **No memory_items sync** — learning items DO NOT flow into `memory_items` / `raw_memory` (business case §7). Learning todos created by the cron DO follow the existing `todo_sync.py` path because they are real todos.
9. **Todo attachment** — how learning-generated todos are distinguished from regular todos is an Architect decision. `TodoItem` already has a `label` field; a junction table, a dedicated column, or an enum are also options. Whatever attachment is chosen, it must not collide with existing filters and must survive the existing todo CRUD + `sync_todo_to_memory` flow.
10. **Feature flag** — follow the existing feature-flag convention (see `module_*_enabled: bool` in `src/core/config.py`). The shape (env-only vs DB-backed) is an Architect decision — whichever is chosen must gate routes, cron, and web consistently.
11. **Mobile input font-size ≥16px** — all web inputs use `text-base md:text-sm`. Base `input.tsx/textarea.tsx/select.tsx` already comply.
12. **Commit format** — `type(scope): description`; scope for this feature is `learning`.

### Architecture snapshot (existing anchors — not a prescription)

This describes what exists today that the feature will interact with. Naming/structure of new tables, routes, files, and schedules is an Architect decision.

- **Models** (`src/core/models.py`): `TodoItem` (around lines 393–447) has `description`, `priority`, `status`, `due_date`, `label`. `TodoHistory` is append-only audit.
- **Routes** (`src/api/routes/todos.py`): existing CRUD + history pattern to mirror.
- **Services** (`src/api/services/`): `memory_service.py::ingest_memory` is the canonical ingest helper — learning data should not flow through it per business case §7.
- **Cron** (`src/jobs/`): existing `pulse.py`, `commitment_miss.py`, `training_weekly.py`, wrapped by `runner.py::run_tracked`. Scheduled via the top-level `crontab` file (supercronic, UTC).
- **LLM** (`src/llm/prompts.py`, `src/llm/client.py`): `AnthropicClient`, Haiku model ID. Prompts inject today's ISO date for relative date framing (see `build_voice_create_system_prompt`).
- **Web** (`web/app/`, `web/hooks/`): existing pages include `/dashboard`, `/memory`, `/chat`, `/diary`, `/analytics`, `/logs`, `/settings`. Hook pattern: custom `use-<resource>.ts` with fetch + useState + useEffect.
- **Config** (`src/core/config.py`): `module_*_enabled` flags (around lines 90–94) — existing feature-flag convention.

### Recent changes

- `6532cd7 feat(training): sync Strava activities and commitment summaries into memory` — reinforces the pattern of direct-create syncs bypassing refinement queue (learning library will NOT sync at all, but same direct-create discipline applies to todo creation from cron).
- `c9faa68 feat(web): animated segmented tab control for SmartComposer` — confirms web UI patterns (Tailwind + shadcn). Use the same component conventions on `/learning`.
- Migration 0012 (Strava tokens) is the most recent schema change — confirms RLS/UUID/JSONB conventions still hold.

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- `TodoItem` and `TodoHistory` in `src/core/models.py` — field types, constraints, indexes, relationships
- `src/api/routes/todos.py` — POST/GET/PATCH/DELETE flow, rate-limit decorators, history writes, `sync_todo_to_memory()` call sites
- `src/pipeline/todo_sync.py` — confirm memory-sync contract (we will leave this unchanged, but cron-created learning todos will pass through it)
- `src/jobs/runner.py`, `src/jobs/pulse.py`, `src/jobs/commitment_miss.py`, and `crontab` — the canonical cron pattern (entrypoint signature, `run_tracked`, scheduling format)
- `src/llm/prompts.py::build_voice_create_system_prompt` and `src/llm/client.py` — Haiku date-injection pattern and client API
- `src/core/config.py` lines ~90–120 — `module_*_enabled` conventions
- Latest migration file under `alembic/versions/` (0012) — RLS, JSONB variant, UUID PK patterns
- `web/app/dashboard/page.tsx` and one existing list page (e.g. `web/app/memory/page.tsx`) plus one corresponding `web/hooks/use-*.ts` — data-fetching and rendering conventions
- `tests/` layout — how existing job + route tests are structured (look at tests that cover `pulse.py`, `commitment_miss.py`, and todo routes)

Also trace for each item:
- Where it is created
- Where it is mutated
- Where it is consumed
- Any related tests

Map the data flow end-to-end where applicable: cron → LLM → todo creation → todo_sync → /today rendering.

Produce a findings report with:
- Exact file paths
- Relevant code snippets (schemas, decorator stacks, sync call signatures)
- Data flow description
- Your honest assessment of structure and quality

Note any surprises or mismatches vs the Architecture snapshot above.

Stop. Do not proceed to Role 2 until the findings report is complete.

---

## ROLE 2 — SKEPTIC

Read Role 1's findings report. Your job is to derive concerns from what the Explorer actually found — not from a pre-seeded list. Surprises in the findings are the most valuable signal; chase them.

### Grounding rules
- Every challenge must cite specific evidence from the Explorer's findings (file path, code snippet, data shape)
- Label each challenge: **HIGH** (contradicting evidence found), **MEDIUM** (ambiguous evidence), **LOW** (speculation)
- For LOW challenges: go back to the codebase and upgrade to MEDIUM/HIGH, or drop with "Insufficient evidence, not blocking"
- Do not carry LOW challenges forward to the Architect

Probe these broad areas — find the specific concerns inside each from the findings, do not invent them generically:
- **Data integrity** — what can silently corrupt or orphan learning data? What invariants are implicit in the business case but not enforced by any schema the Explorer found?
- **Idempotency & re-run behavior** — the business case says "running twice on the same day produces no duplicate todos"; what in the existing cron patterns supports or breaks this?
- **Coupling with existing todo flow** — does the reuse of any existing field/label/route introduce collisions, hidden filters, or backward-compat risk? What did the Explorer find that suggests the chosen attachment point is or isn't safe?
- **Cost & scale** — at the volumes the business case names ("dozens of topics with dozens of items"), what in the LLM client / prompt patterns the Explorer found becomes a liability?
- **Failure modes** — what does the fallback actually need to cover, given the specific failure paths the Explorer observed in similar crons?
- **State preservation on deactivation/completion** — business case is explicit that no progress is ever lost; which code paths the Explorer found could violate that?
- **Test coverage gaps** — where are similar features thin on tests today, and does that predict risk here?

You are NOT limited to the above. If the Explorer surfaced something surprising — a quirk in `run_tracked`, an undocumented constraint, a pattern that diverges from CLAUDE.md — pull on that thread. Unexpected findings beat expected ones.

For each challenge, label:
**HIGH** | **MEDIUM** | **LOW** → [upgraded/dropped]

For anything MEDIUM or HIGH:
- Revisit the codebase if needed
- Update findings with corrected understanding

Stop. Present the reconciled findings (HIGH and MEDIUM items only) before Role 3 begins.

---

## ROLE 3 — SENIOR ARCHITECT

Read the reconciled findings from Roles 1 and 2. Design the implementation from those findings — do not assume the shape. If the Explorer surfaced a pattern, follow it; if the Skeptic flagged a risk, resolve it in the design.

Your job is to make and justify the key decisions this feature requires. The business case (`docs/learning-library-business-case.md`) defines WHAT. You define HOW, grounded in what actually exists in the codebase.

### Decisions you must make (with reasoning for each)

1. **Schema shape** — what tables, columns, relationships, indexes, and constraints does the three-layer hierarchy (Topic → Section → Item) need? What stays nullable, what gets defaults, what needs composite constraints? Follow existing migration conventions (see Project Context). Include the migration filename.

2. **Where learning-generated todos attach to the existing todo system** — evaluate attachment options against the Explorer's findings (reusing `TodoItem.label`, a new column, a dedicated junction, a new `todo_kind` enum). Choose one. Explain why the alternatives were rejected based on what the Skeptic surfaced about collision/compat risk.

3. **Idempotency mechanism for the daily cron** — design it. What state determines "already ran today"? What happens if the user deletes one of today's learning todos and cron fires again? What does this mean for the user's "on-demand fetch" manual trigger? Anchor the design in whatever pattern existing crons (`pulse`, `commitment_miss`, `training_weekly`) use — or diverge and justify.

4. **Completion cascade** — when a learning todo is marked done, what (if anything) happens to the underlying learning item? Business case is ambiguous; pick a default and justify. Consider failure modes (cascade write fails — does the todo completion still succeed?) and the reverse direction (item checked off directly on /learning — does it create or mutate a todo?).

5. **Feature flag surface** — "learning mode on/off" — is this an env-only module flag (matching `module_*_enabled` in `src/core/config.py`), a DB-backed per-user toggle, or both? Choose based on where existing modules draw the line. The flag must gate routes, cron, AND the web page consistently.

6. **LLM call shape** — input (what data structure goes into the prompt), output contract (JSON schema), date injection, feedback window, fallback trigger conditions, fallback determinism. Decide what gets pre-filtered before the LLM sees it. Cite the existing prompt pattern you are following (likely `build_voice_create_system_prompt`).

7. **API surface** — list the routes, methods, auth, and rate-limit buckets. Group by resource. Call out any route that deviates from existing CRUD patterns and why.

8. **Web architecture** — page structure, hook shape, /today integration surface. How does the learning badge render without diverging from existing todo-list components? Minimum-diff principle.

### Required sections regardless of decisions above

**Test plan** — What contracts must be tested (API shapes, cron behavior, cascade semantics, feature-flag gating, idempotency, fallback). What invariants must hold (business case §5 Safety list is the floor: best-effort feedback, fallback on cron failure, no data loss on deactivation). Implementer writes these FIRST.

**What stays unchanged** — explicitly name the modules, tables, and flows this feature must NOT touch. Anchor this in the Explorer's findings.

**Constraints & Safety** — performance, backward compat, migration rollback, failure modes, feature-flag rollback. Tailor each to decisions above.

### How to present

For each decision: state the choice, the alternatives considered, and the evidence-based reason. If Role 2 produced a HIGH or MEDIUM concern in that area, explain how the design resolves or consciously accepts it.

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
python3 ~/.claude/skills/ui-ux-pro-max/scripts/search.py "personal learning dashboard curriculum tree" --design-system -p "open-brain"
```

### Step 2 — Evaluate and adapt
Review the generated design system against:
- Existing open-brain UI patterns (shadcn/ui, Tailwind, existing `/memory`, `/dashboard`, `/chat` pages) — discovered by Explorer
- The project's current design language (CSS variables / tokens used in `globals.css` / `tailwind.config.*`, component primitives in `web/components/ui/`)
- Architect's constraints (tree view with topics → sections → items, active-toggle, inline feedback/notes form, "Learning" badge on /today todos)

**Consistency rule:** the Learning page must look like it belongs in open-brain, not like a redesign. If the generated design system conflicts with established patterns:
- Keep existing color tokens, typography, and spacing
- Adopt only recommendations that fill gaps — e.g. a tree/disclosure component, drag-and-drop reorder affordance, distinct but subtle "Learning" badge treatment on /today

### Step 3 — Produce a design brief
Output a concise design brief for the Implementer containing:
- **Color tokens** — badge color for learning todos (derive from existing accent tokens, not a new hue)
- **Typography** — only if a new hierarchical scale is needed for the topic/section/item tree; otherwise reuse existing
- **Component patterns** — tree disclosure, drag handles (v1 can skip DnD and use up/down buttons), inline feedback/notes form below an item row, empty states
- **Interaction patterns** — hover states on items, check-off animation, optimistic UI for toggles, loading skeletons for tree
- **Anti-patterns** — avoid nested modals; avoid color-coding topics (depth is a label, not a color); do not auto-expand all topics by default on mobile
- **Pre-delivery checklist** — contrast on "Learning" badge vs todo background; cursor-pointer on clickable rows; focus-visible on all interactive elements; `text-base md:text-sm` on every input/textarea (mobile zoom bug); respects `prefers-reduced-motion`

The Implementer treats this brief as a constraint alongside the Architect's plan.

Stop. Present the design brief before Role 4 begins.

---

## ROLE 4 — IMPLEMENTER

Read the architect's plan and the design brief. Implement exactly as specified.

### Step 1 — Write tests first (mandatory)
Write test files covering every contract, invariant, and edge case the Architect's test plan specifies. Follow the project conventions listed in Project Context (mock style, assertion conventions, SQLite UUID handling). Run them, confirm they fail for the expected reasons (missing implementation, not import errors or broken setup). If they fail unexpectedly, STOP and reconcile.

### Step 2+ — Implement production code
Follow the Architect's plan step by step. Work in order from lowest-risk/foundational (schema, models, config) to highest-risk/integration (cron job, web page, /today surface). Do not invent additional structure not in the Architect's plan; if something the plan requires is ambiguous, return to Role 3 rather than guessing.

After each step:
- Run `make test`, `make lint`, and relevant `npm test` / `npx playwright test`
- Fix failures before continuing

### Final verification
- `make test` fully green
- `make lint` clean (ruff + black + mypy)
- `cd web && npm test` and `npx playwright test` green
- Manual end-to-end: start backend + web, create a topic + section + items, toggle the topic active, trigger the cron via whatever manual-trigger path the Architect defined, verify 2–3 learning-tagged todos show on /today distinguished from regular todos, check one off with feedback/notes, confirm the underlying learning item is marked completed per the Architect's cascade decision
- Structured log line from the cron showing counts, fallback status, and feature-flag state (follow existing cron logging style)

Final check:
- Re-read the business context
- Verify the implementation matches the original intent
- Especially validate: **idempotency (re-running same day produces no duplicates) and "no data loss on deactivation" (toggling inactive preserves all state)**

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

1. **Correctness** — does it satisfy the plan? Logical errors, missing cases?
2. **Scope adherence** — any unnecessary changes? Anything explicitly required but missing?
3. **Code quality** — readability, structure, naming, consistency with existing patterns
4. **Safety** — edge cases (null, async, race conditions), backward compat, failure handling
5. **System impact** — hidden coupling, side effects, performance
6. **Tests & validation** — sufficient? Meaningful? Critical paths untested?
7. **Skeptic's concerns (cross-reference Role 2)** — each MEDIUM/HIGH addressed or consciously accepted with rationale
8. **Plan fidelity (cross-reference Role 3)** — deviations justified + documented
9. **Convention compliance (cross-reference Project Context)** — each item in the 12-point checklist satisfied
10. **Design compliance (cross-reference Role 3.5)** — design brief followed, badge/tree consistent, pre-delivery checklist satisfied

Output:
- Issues grouped by severity: CRITICAL / MAJOR / MINOR
- Concrete suggested fixes for each CRITICAL and MAJOR
- For each CRITICAL: **IMPLEMENTATION** (code bug) or **ARCHITECTURAL** (design flaw)

Loop-back rules:
- **CRITICAL IMPLEMENTATION** → return to ROLE 4 with explicit fixes. After fixes, return here (increment cycle).
- **CRITICAL ARCHITECTURAL** → return to ROLE 3 with specific concern. After revision + re-implementation, return here (increment cycle).
- **Review cycle 2 with unresolved CRITICAL** → **BLOCKED**. List unresolved issues. Stop.
- **No CRITICAL** → proceed to ROLE 6.

---

## ROLE 6 — SECURITY REVIEWER

Review the entire implementation through a security lens.

**Review cycle: 1 of 2 maximum.**

Evaluate for this task specifically:
- **User-authored content → LLM**: topic names, feedback, and notes flow into the cron's LLM prompt. Is all user input wrapped in `<user_input>...</user_input>` delimiters? Is prompt-injection protection consistent with existing extraction prompts?
- **Rate-limit coverage on new routes**: every new `/v1/*` learning route decorated with `@limiter.limit(...)`. Worst-case LLM cost: can an authenticated attacker trigger the manual-refresh endpoint in a loop? What's the daily cap?
- **RLS on new tables**: every new table added in the migration has `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`
- **Feature flag honored everywhere**: learning-mode OFF blocks routes, cron, AND web fetches — not just the cron
- **PII / secrets**: no API keys, no emails, no Discord IDs logged in learning-job output; no raw LLM prompts with user notes dumped to logs.

Additionally evaluate (standard checklist):
- Authentication & authorization on new/modified routes
- Input validation & injection (SQL, XSS, prompt injection)
- Rate limiting & abuse; LLM cost exposure
- Data at rest & in transit; secrets in logs; PII handling
- Dependencies — any new packages with known vulns?

Output:
- **CRITICAL** — must fix before deployment (auth bypass, injection, data exposure, missing RLS)
- **ADVISORY** — document and accept (third-party data flows, platform limits)
- **HARDENING** — optional defense-in-depth (daily cost caps, audit logging of trigger calls)

For each CRITICAL: concrete remediation.

Loop-back rules:
- **CRITICAL** → return to ROLE 4 with explicit fixes. After fixes, re-review via ROLE 5, then return here (increment cycle).
- **Review cycle 2 with unresolved CRITICAL** → **BLOCKED**. List unresolved issues. Stop.
- **No CRITICAL** → final security sign-off.

---

## Completion

