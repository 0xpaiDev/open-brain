# Context

Replace the morning pulse's monolithic "generate a question with Haiku" flow with a signal-detector architecture: small Python detectors inspect `MorningContext`, each emits `(signal_type, urgency, payload)` or `None`, a ranker picks the strongest signal above a silence threshold, and a signal-specific prompt renders the one-liner. Current pain: Type B reflective questions feel generic and get skipped; novelty-per-effort is too low, engagement drops. Root cause is structural (no signal → forced filler), not prompt-tuning.

**Phase 1 deliverable (this plan):** `MorningContext` builder, three detectors (`opportunity`, `focus`, `open`), ranker with silence cutoff, signal-specific prompts, `signal_type` column on `daily_pulses`, tests, no regressions. Phase 2+ (recovery/commitment_progress/pattern_drift/learning_primer detectors, cooldowns, multi-signal composition, weekly tuning cron) out of scope but design must not preclude.

**Intended outcome:** When the pulse fires, it earns attention. Silence rate > 0. Signal attribution visible for debugging and future tuning. Adding a detector is <1 day.

---

# Complexity Verdict: **HEAVY** — recommend fresh session

- 6+ implementation steps (context builder, 3 detectors, ranker, prompt layer, migration, route wiring, test suite, label adaptation)
- 3 layers touched (backend job/models/routes, Alembic migration, Discord modal + web UI label adaptation)
- Schema change (`signal_type` column + silence handling on `daily_pulses`)
- Behavioral change in production cron with memory-sync coupling and Discord persistent-view compatibility to preserve
- Skeptic will surface at least 3 HIGH-confidence risks (silence-row idempotency, `_format_pulse_content` assuming "question" semantics, modal label dependency on ai_question text)

**Recommendation:** Execute in a fresh session. Plan saved at `/home/shu/.claude/plans/business-case-signal-driven-jaunty-clock.md`. To execute, start a new conversation and reference this file.

---

# Signal-Driven Morning Pulse — Multi-Agent

You will work through this task in sequential roles. Do not skip ahead.
Review roles (5 and 6) may loop back for fixes, up to 2 cycles each.
The goal: the morning pulse generates output only when a signal detector clears a silence threshold — question, remark, or nudge — picked from a ranker over per-slice detectors, with `signal_type` stored for analytics.

---

## Business context (read once, then put on your shelf)

Open Brain is a single-user organizational-memory system. The Morning Pulse module sends Shu a 05:00 UTC Discord DM (plus web-dashboard surface) with calendar + open todos + an AI-generated question. Replies are parsed into sleep/energy/notes + free-text response, synced into `memory_items` so RAG chat can recall them. The current generator calls Haiku with 5 open todos + yesterday's question and alternates between operational (Type A) and reflective (Type B) questions. Type B questions get skipped in practice — they feel generic because the model has no real signal to work with, and alternation forces reflective output even when nothing reflective is worth saying. The fix is structural: build a pipeline of small signal detectors (each a pure Python function over a `MorningContext`), rank them by urgency, render the winner with a signal-specific prompt, and stay silent on days where nothing clears the bar.

---

## Project context (grounding for all roles)

### Relevant conventions

1. **Alembic migration for new column** — `signal_type` must be added via a new migration file (e.g., `alembic/versions/0014_pulse_signal_type.py`), not `create_all()`. Plain `String(32)` is cross-DB safe; no `.with_variant()` needed.
2. **`_get_settings()` lazy helper** — do NOT do `from src.core.config import settings` at module top in any new detector, context builder, or weather client. Use `_get_settings()` to avoid capturing stale or `None` settings in tests.
3. **Prompt injection defense** — any user-supplied text surfaced to Haiku (memory_items content, todo descriptions, calendar titles, weather location names) must be wrapped in `<user_input>...</user_input>` delimiters in the signal-specific prompt.
4. **Haiku training cutoff → inject current date** — any prompt referencing "today" or relative dates must inject `date.today().isoformat()` into the system prompt, per the pattern in `src/llm/prompts.py::build_voice_create_system_prompt`. Detector payloads should carry ISO dates, not "today/tomorrow".
5. **Tests run on SQLite, prod on PostgreSQL** — fixtures mock the Anthropic + Voyage clients (`_make_mock_llm`, `mock_voyage_client` from `tests/conftest.py`). Detector unit tests should be pure functions over a `MorningContext` fixture — no DB if possible.
6. **`SecretStr` for API keys** — Open-Meteo requires no key, so no new `SecretStr` needed. If any future detector adds a keyed API, wrap it.
7. **`session.commit()` is required; `session.refresh(obj)` after commit** — new `signal_type` column with a default or server-default value will need `refresh()` for the generated `PulseResponse` to carry it.
8. **Every `/v1/*` route needs `@limiter.limit()`** — the existing `POST /v1/pulse/start` rate limit stays. Any new admin analytics route (out of scope Phase 1, but if added) needs its own limiter decorator.
9. **No new required env vars without defaults** — all new settings must default to safe values: detector toggles default on, weather defaults to Kaunas lat/long, silence threshold defaults to a conservative 5.0.
10. **pulse_sync best-effort wrapper** — the try/except in `PATCH /v1/pulse/today` that calls `_try_pulse_sync()` must keep swallowing exceptions; `signal_type` surfacing to memory must not break the sync path if the column is null.
11. **Discord persistent view custom_ids** — `pulse:log` and `pulse:skip` must survive bot restarts. Do NOT rename them. Any new silence-path handling must not introduce new button custom_ids without registering them on cog load.
12. **Commit format** — `feat(pulse): ...` for generation changes, `feat(db): ...` for migration, `test(pulse): ...` for tests.

### Architecture snapshot

The pulse generation layer is the seam. Today:

- `src/jobs/pulse.py::send_morning_pulse()` (line 440) is the cron entry. It calls `_fetch_open_todos`, `fetch_today_events` (`src/integrations/calendar.py`), and `_generate_ai_question` (line 256, the target of replacement).
- `_generate_ai_question(llm, open_todos, yesterday_question)` wraps one Haiku call with `PULSE_QUESTION_SYSTEM_PROMPT` (lines 32-82) and heuristic A/B alternation (line 284-292).
- The question is written into `DailyPulse.ai_question` (`src/core/models.py:458-490`). Columns relevant to this task: `id`, `pulse_date` (UNIQUE), `status` (sent/replied/parsed/parse_failed/skipped/completed/expired), `ai_question`, `ai_question_response`, `parsed_data` (JSONB), created/updated timestamps. No current `signal_type`, `signal_payload`, or "silent" status.
- `POST /v1/pulse/start` (`src/api/routes/pulse.py:164-243`) is the web/manual generation entry; `GET /v1/pulse/today` (line 291) pre-checks idempotency; `PATCH /v1/pulse/today` (line 324) triggers `_try_pulse_sync()` on transition to `completed`/`parsed`.
- `src/pipeline/pulse_sync.py::_format_pulse_content()` (line 23-46) builds a natural-language string that includes `f"AI question: {q} Response: {r}"` — this **assumes ai_question is literally a question**. A remark will render as `"AI question: Hard ride yesterday. Keep today easy. Response: ok"` which is semantically off.
- Discord modal `PulseModal` (`src/integrations/modules/pulse_cog.py:74-129`) builds a dynamic response field label from `ai_question[:45]` — if `ai_question` is None (silence path) the field should not render; if it's a remark the label semantics shift.
- Web surface `web/components/dashboard/morning-pulse.tsx` + `web/hooks/use-pulse.ts` render the question as a blockquote with "Your answer" label. Same dependency.
- Anthropic client: `src/llm/client.py::AnthropicClient.complete(system_prompt, user_content, max_tokens)`. Settings: `anthropic_model` (default `claude-haiku-4-5-20251001`).
- Calendar: `fetch_today_events(settings)` returns `CalendarState(events, tomorrow_preview)`. Empty state on failure (google deps optional).
- Weather: **no existing integration** — the `opportunity` detector needs a new `src/integrations/weather.py` (Open-Meteo, no API key).
- Commitments: `src/core/models.py` `Commitment` (daily | aggregate cadence, `targets`/`progress` JSONB). **No "weekly" cadence concept.** For Phase 1, `opportunity` must NOT depend on commitment queries — see decision 1 below.
- Memory retrieval: `src/retrieval/` has hybrid_search; for pulse detectors we likely only need simple `SELECT ... FROM memory_items WHERE created_at > ... ORDER BY created_at DESC LIMIT n` queries, not full ranking.
- Learning cron `src/jobs/learning_daily.py` runs 04:30 UTC, 30 min before pulse. It writes `todo_items` with `learning_item_id` — these are already captured by `_fetch_open_todos`. No direct coupling to change.
- Feature flags in `src/core/config.py:105-111`: `pulse_timezone`, `module_pulse_enabled`, `discord_pulse_user_id`, `pulse_accept_freetext`. New settings slot in here.
- All tables have RLS enabled (migration 0009). New columns on existing tables inherit; no new DDL needed beyond the migration itself.

### Recent changes

- **Learning Library V1 shipped** (`6eadebe`, 2026-04-11) — introduced `learning_daily` cron at 04:30 UTC. Not a direct dependency, but the 30-minute gap to pulse at 05:00 UTC must be preserved (learning todos must be visible when pulse fetches open todos).
- **Commitment completion bugfix + daily completion on end_date** (`92a73f4`, recent) — `Commitment.status` semantics locked: `active|completed|abandoned`, with `goal_reached` derived on read. Phase 2's `commitment_progress` detector will query this; Phase 1 does not.
- **Bulk todo defer endpoint** (`5d2672e`, latest) — `POST /v1/todos/defer-all`. No direct impact.
- **Alembic head is 0013** (`learning_library`). New migration will be `0014`.
- **~1204 tests (957 backend + 247 Vitest)** — regression baseline. Existing `tests/test_pulse.py` and `tests/test_pulse_sync.py` must continue to pass.
- No recent churn in `src/jobs/pulse.py`, `src/api/routes/pulse.py`, or `src/integrations/modules/pulse_cog.py` — the generation seam is stable enough to refactor.

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- `src/jobs/pulse.py` in full — confirm `_generate_ai_question` (≈line 256), `send_morning_pulse` (≈line 440), `_fetch_open_todos`, `_build_morning_embed`, and the exact call path from cron to DB write.
- `src/api/routes/pulse.py` — confirm `POST /v1/pulse/start`, `GET /v1/pulse/today`, `PATCH /v1/pulse/today`, and the `_try_pulse_sync` trigger on status transitions to `completed` / `parsed`.
- `src/core/models.py::DailyPulse` (≈line 458) — confirm all columns, types, defaults, unique constraints, and the set of valid `status` strings in use today.
- `src/pipeline/pulse_sync.py::_format_pulse_content` — exact string-building logic; what happens if `ai_question` is None or not a question.
- `src/integrations/modules/pulse_cog.py::PulseModal` — the dynamic-label field and how it handles `ai_question=None`; the `pulse:log`/`pulse:skip` custom_id registration.
- `web/components/dashboard/morning-pulse.tsx` + `web/hooks/use-pulse.ts` — the "Your answer" label, blockquote rendering, and what happens when `ai_question` is null in the response.
- `src/integrations/calendar.py` — `fetch_today_events`, `CalendarState`, `CalendarEvent` shape (title, start, end, location, all_day, calendar).
- `src/llm/client.py::AnthropicClient.complete` signature and current error modes.
- `src/llm/prompts.py` — confirm the `<user_input>` delimiter and `date.today()` injection pattern used for voice create (build_voice_create_system_prompt).
- `src/core/config.py` — exact slot (line 105–111) where `pulse_*` settings live; pattern for defaulted settings.
- `alembic/versions/0013_learning_library.py` — shape of recent migrations (up/down, `op.add_column` pattern, revision/down_revision headers).
- `tests/test_pulse.py` + `tests/test_pulse_sync.py` + `tests/conftest.py` — existing patterns for mocking LLM, fixtures for `CalendarState`/`CalendarEvent`, datetime helpers, DB session fixture shape.

Also trace for each item:
- Where `DailyPulse.ai_question` is written (cron + `POST /v1/pulse/start`).
- Where `ai_question` is read (modal dynamic label, web blockquote, pulse_sync formatter, `PulseResponse`/`PulseListResponse` Pydantic models).
- How `PulseResponse` is constructed from the ORM — if a new column doesn't flow through automatically, find the field list.
- Any reference to `"What's one thing you want to accomplish today?"` fallback (line ≈305 in pulse.py).
- Grep for `weather`, `meteo`, `open-meteo` across repo to confirm zero existing integration.
- Grep for `signal_type`, `signal_payload` to confirm no prior attempt.

Produce a findings report with:
- Exact file paths + line numbers
- Relevant code snippets (short — signatures + critical lines)
- Data flow from cron → DB → Discord modal / web UI → pulse_sync → memory_items
- Your honest assessment of how much of the existing code path is safe to keep vs must be replaced.

Note any surprises or mismatches vs the Architecture snapshot above (e.g., if `ai_question` is already nullable; if `status="expired"` is actually used anywhere; if the modal's dynamic-label code already handles `None`).

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

- **Silence-row idempotency.** If we skip the Discord DM on silence days, do we still write a `DailyPulse` row? If not, the next cron invocation (or a `POST /v1/pulse/start` from the web) will regenerate. If yes, with what `status`? Does `GET /v1/pulse/today` pre-check correctly short-circuit against silence rows? The business case says "existing idempotency must be preserved."
- **`_format_pulse_content()` assumes question semantics.** When `signal_type="opportunity"` and `ai_question="Best ride weather all week today — Fri–Sat look wet."`, the formatter produces `"AI question: Best ride weather... Response: ..."` which becomes an embedding that misrepresents the pulse. Confirm this is actually a problem (or whether the formatter will elide this section if no response) and propose a fix or flag it for the Architect.
- **Modal dynamic label brittleness.** The Discord modal label derives from `ai_question[:45]`. If the winning signal is a remark with no question mark, what's the user flow? Is there an interactive "log" step that still makes sense, or does the remark just need a "👍 / Skip" acknowledgement? Check `PulseModal.on_submit` and the `ai_response` field gating.
- **Web surface assumes question.** `morning-pulse.tsx` renders `ai_question` as a blockquote with hardcoded "Your answer" label. Does the hook handle `ai_question=None` at all? If silence day → no render, how does the user know "today was silent"? Or should silence skip the card entirely?
- **One Haiku call vs zero.** The business case says detectors are deterministic Python + one Haiku call for final phrasing. But the `open` (reflective fallback) detector needs Haiku to produce the question text at all — it has no structured payload to template from. So `open` collapses to today's behavior + a signal_type label. Is that correct? If yes, what's the functional win for the `open` case in Phase 1?
- **`opportunity` detector without a commitments query.** Phase 1 scope lists `opportunity` as in-scope but the weekly-commitments concept is explicitly deferred. What can `opportunity` actually do in Phase 1? Weather-only ("ride weather today") without a weekly ride commitment is a weak signal. Architect needs a concrete Phase 1 definition of what `opportunity` fires on, or `opportunity` should be dropped from Phase 1 in favor of another detector.
- **`focus` detector and calendar quality.** `focus` depends on "pivotal calendar event today." How does the detector decide what's pivotal? By title keyword match? Attendee count? Duration? If it's keyword-based, who maintains the keyword list? If it's LLM-classified, that's a second Haiku call per pulse.
- **Cooldowns deferred but signal_type still mono-day.** If `open` fires 3 days running, each day gets the same signal_type and the novelty problem isn't solved. Scope says cooldowns are Phase 2 — is that acceptable, or does Phase 1 need a minimal "don't repeat signal_type from yesterday" check?
- **Cron runs before web dashboard user is awake.** The 05:00 UTC cron generates and writes the row. If the detectors misbehave and produce silence every day, the web dashboard shows "no pulse today" with no debugging affordance. Is there a manual re-trigger path? (`POST /v1/pulse/start` with a force flag?)
- **Open-Meteo reliability.** Timeouts and rate limits. What's the detector behavior when weather fetch fails — swallow and return None (lose the opportunity signal) or fall through to a lower-urgency detector?
- **Memory retrieval for `MorningContext`.** "Recent relevant memory_items" is in scope. How is "relevant" defined for Phase 1? Last N days by `created_at`? Filtered by tags? If it's an embedding search, that's an extra Voyage call per pulse. If it's tag-filtered, we need a tag convention.
- **signal_type values are an unbounded string.** If we store `signal_type: String(32)` with no CHECK constraint, typos slip through. Worth adding a CHECK constraint vs. app-level enum vs. waiting for Phase 2?
- **Existing test coverage.** `_generate_ai_question` is currently mocked at the LLM level. Rewriting to detectors changes the seam — which tests need rewriting, which can stay? Is there a meaningful "generation produced something" integration test that breaks?

Additionally challenge:
- Hidden dependencies or coupling
- Data shape assumptions
- Edge cases (null, async timing, partial state)
- Backward compatibility risks (existing `DailyPulse` rows have `signal_type=NULL` — does any read path break?)
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

1. **Module layout** — where do `MorningContext`, detectors, ranker, prompts, and weather client live?
   - Proposal baseline: new package `src/pulse_signals/` with `context.py`, `ranker.py`, `prompts.py`, `detectors/{opportunity,focus,open}.py`. Weather stays in `src/integrations/weather.py`. Refactor `src/jobs/pulse.py::_generate_ai_question` to call `pulse_signals.run_detection(context) -> Signal | None` and render via `pulse_signals.render(signal, llm)`.
   - Alternative: keep everything in `src/jobs/pulse.py` as private helpers. Justify which and why.
   - Decide whether `pulse_signals.Signal` is a `@dataclass` or a Pydantic model. Prefer `@dataclass` — detectors are internal, no serialization needed; payload is `dict[str, Any]`.

2. **`MorningContext` shape** — exact fields and their types. Specify:
   - `today: date` (local `PULSE_TIMEZONE`, not UTC — existing pulse uses timezone-aware logic)
   - `calendar: CalendarState` (reuse existing)
   - `weather: WeatherSnapshot | None` (new; fields: `today_min_temp`, `today_max_temp`, `today_precip_mm`, `today_wind_kmh`, `next_7_days: list[DayForecast]`; None on fetch failure)
   - `open_todos: list[TodoItem]` (reuse existing query)
   - `yesterday_pulse: DailyPulse | None`
   - `recent_memories: list[MemoryItem]` — Phase 1 definition: last 7 days, `memory_type in ("daily_pulse", "todo", "todo_completion")`, limit 20, ordered by `created_at DESC`. NO embedding search (cost). Tag filter deferred.
   - Decide the builder entry: `async def build_morning_context(session, settings, http) -> MorningContext`.

3. **Detector protocol** — exact interface. Proposal:
   ```python
   @dataclass
   class Signal:
       signal_type: str         # "opportunity" | "focus" | "open" | ...
       urgency: float           # 0.0 - 10.0
       payload: dict[str, Any]  # detector-specific
   
   class Detector(Protocol):
       name: str  # matches signal_type
       def detect(self, ctx: MorningContext) -> Signal | None: ...
   ```
   Decide: are detectors classes, functions, or Protocol-conformant instances? Registration pattern (module-level list vs settings-driven)?

4. **Phase 1 detector definitions** — concrete logic for each:
   - **`opportunity`** — given the Phase 2 deferral of commitments, define what it fires on in Phase 1 with only weather data. Candidates: "noticeably better weather today than next 3 days" (precip threshold, temp band). Without a commitment, how is this actionable? If there's no clean definition, either (a) fold `opportunity` into Phase 2 and replace with `scheduled_focus` or `todo_pressure`, or (b) commit to a narrow weather-only definition that only fires ~1-2x/week. Decide and justify.
   - **`focus`** — fires when today has at least one calendar event classified as "pivotal" AND there's a clear call-to-action. Deterministic rule: if `event.title` matches configurable keyword list (`pulse_focus_keywords: list[str] = ["1:1", "demo", "review", "interview", "launch", "presentation"]`) OR event duration >= 60 min AND has `attendees` marker in title (heuristic: `@` or "with"). Payload: `{event_title, start_time, reason}`.
   - **`open`** — fires if no higher-priority signal fires AND a minimum activity-floor condition is met (e.g., ≥1 open todo OR ≥1 calendar event). Urgency = base value (e.g., 5.0). Payload: top 3 open todos + calendar summary. This IS today's generic path with a name; acknowledge the Phase 1 value is the architecture, not the content.
   - Urgency scoring formulas per detector. Define thresholds explicitly.

5. **Ranker + silence threshold** — exact logic:
   - `select_signal(signals: list[Signal], threshold: float) -> Signal | None` — pick max-urgency signal; return None if below threshold.
   - Default threshold: `pulse_silence_threshold: float = 5.0` in settings.
   - Tie-break rule (stable order matters for tests): detector order defined in a registry list.
   - Should the ranker log all detector outputs (even None) for analytics? Proposal: yes — store full ranker trace in `DailyPulse.parsed_data` under key `"signal_trace"` (already JSONB, already nullable, no schema change needed).

6. **Signal-specific rendering** — one Haiku call per fired signal, per-signal system prompt:
   - `render_signal(signal, llm) -> str` picks a prompt template by `signal.signal_type` and passes `signal.payload` as the user message.
   - Prompts live in `src/pulse_signals/prompts.py` as constants: `OPPORTUNITY_SYSTEM_PROMPT`, `FOCUS_SYSTEM_PROMPT`, `OPEN_SYSTEM_PROMPT`.
   - Each prompt: ≤30 tokens of instruction, injects `date.today().isoformat()`, wraps payload fields in `<user_input>`, caps output at 80 tokens, expects a single sentence (may or may not end with `?`).
   - Silence path: no LLM call.

7. **Schema change** — `alembic/versions/0014_pulse_signal_type.py`:
   - `ALTER TABLE daily_pulses ADD COLUMN signal_type VARCHAR(32)` (nullable, no default — existing rows stay NULL which is interpreted as "pre-signal" legacy).
   - No CHECK constraint in Phase 1 — add in Phase 2 once the enum stabilizes.
   - Update `DailyPulse` ORM model and `PulseResponse` + `PulseListResponse` + `PulseCreate` Pydantic schemas.
   - Down migration drops the column.

8. **Silence-path handling — the critical decision.** Three options:
   - **(a) Status `silent`** — add `"silent"` to `_VALID_STATUSES`. Create `DailyPulse` row with `status="silent"`, `ai_question=None`, `signal_type=None`. No Discord DM, no modal. `GET /v1/pulse/today` returns it, so idempotency holds.
   - **(b) Status `sent` with `ai_question=None`** — reuses existing status but couples "silent" to a nullability check. Downstream (modal, web UI) already doesn't handle `ai_question=None` — requires more downstream changes.
   - **(c) Skip DB write entirely** — breaks idempotency and the cron-vs-manual-start interaction.
   
   **Decide and justify.** Preferred: (a) — cleanest semantics, minimal coupling. Need to update `_try_pulse_sync` to skip silent rows (nothing to sync), and update `PATCH /v1/pulse/today` to reject transitions out of `silent` (or define what a status=silent → completed transition even means).

9. **Discord & web UX for non-question signals** — label adaptation:
   - Discord modal: if `ai_question` ends with `?` → "Your answer" label; else → "Thoughts?" label. Keep same `ai_response` field.
   - Web: same rule. `morning-pulse.tsx` label = `pulse.ai_question?.endsWith("?") ? "Your answer" : "Thoughts"`.
   - Silence day: web shows "No pulse today" card with subtle "Why?" debug link (if env `pulse_signal_debug_ui=True`, show signal trace).
   - Discord silence day: no DM at all. That's the whole point.

10. **`_format_pulse_content` adaptation** — the memory-sync formatter assumes question semantics. Change: if `signal_type` is present and not `"open"`, format as `f"Daily pulse ({signal_type}) for {date}: {ai_question} Response: {response}"`. If `"open"` or legacy NULL, keep the existing `f"AI question: {q}"` format. Write a test for each case.

11. **Settings additions** (`src/core/config.py`):
    - `pulse_silence_threshold: float = 5.0`
    - `pulse_signal_detectors: str = "focus,opportunity,open"` (comma-separated, order = tie-break priority)
    - `pulse_weather_enabled: bool = True`
    - `pulse_weather_latitude: float = 54.8985` (Kaunas)
    - `pulse_weather_longitude: float = 23.9036`
    - `pulse_focus_keywords: str = "1:1,demo,review,interview,launch,presentation"` (comma-separated)
    - `pulse_signal_debug_ui: bool = False`
    - All defaulted; none required.

12. **Test plan** — what contracts must be tested, what invariants must hold:
    - Per-detector unit tests over hand-crafted `MorningContext` fixtures: happy path, not-firing path, edge cases (empty calendar, missing weather, etc.).
    - Ranker unit tests: empty list → None, single signal above threshold → picked, single signal below threshold → None, multiple signals → highest urgency picked, tie → detector-order wins.
    - Prompt rendering tests: mocked `llm.complete` called with correct system_prompt + user_content for each signal_type; 80-token cap enforced.
    - Migration test: apply 0014, column exists, nullable, round-trip NULL.
    - `_format_pulse_content` tests for each signal_type path + legacy NULL.
    - Route tests: `POST /v1/pulse/start` on a "silent" context creates a row with `status="silent"`, `signal_type=None`, no Discord call (mock `send_dm_via_rest`); second call is idempotent.
    - Silence path: `GET /v1/pulse/today` returns the silent row; `PATCH /v1/pulse/today` attempt to set `status="completed"` on a silent row — define expected behavior (reject vs allow).
    - Discord modal label logic test (Python): `ai_question=None` → no ai_response field; `ai_question="Tight run."` → "Thoughts?" label; `ai_question="What's your plan?"` → "Your answer" label.
    - Web tests (Vitest): silence card renders; question label for `?`-ending; "Thoughts" label for remarks; existing pulse tests still pass.
    - Regression: all tests in `tests/test_pulse.py` and `tests/test_pulse_sync.py` still pass.
    - Weather client tests: httpx mock for success, timeout, 429, schema-mismatch — all return None or raise gracefully.
    - **Implementer writes tests FIRST, before any production code.**

13. **What stays unchanged**
    - `DailyPulse.pulse_date` UNIQUE constraint and `_pulse_already_sent_today` pre-check logic.
    - Discord `pulse:log` / `pulse:skip` custom_id registration and persistent view behavior.
    - `_try_pulse_sync` trigger on `completed`/`parsed` transitions.
    - `send_dm_via_rest`, `get_or_create_dm_channel` (Discord REST delivery path).
    - `fetch_today_events` signature and behavior.
    - `POST /v1/pulse/start` auth + rate limit decorators.
    - Existing Pydantic request/response models' existing fields — only add `signal_type`.
    - `src/llm/client.py` and the Anthropic model selection.
    - Learning cron timing (04:30 UTC, 30 min before pulse).

14. **Constraints & Safety**
    - **Performance.** Max one Voyage call (unchanged) + one Haiku call (for rendering) per pulse. Weather fetch is one httpx call with 5s timeout. Target: pulse cron completes under 10s end-to-end on the e2-medium VM.
    - **Backward compatibility.** Existing `DailyPulse` rows have `signal_type=NULL`; all read paths (web, API, memory sync) must handle NULL. Migration is additive only.
    - **Failure modes.**
      - Weather fetch fails → `ctx.weather=None` → `opportunity` detector returns None → ranker falls through.
      - All detectors return None → silence path (row with `status="silent"`).
      - Haiku call fails during rendering → fallback string: the existing `"What's one thing you want to accomplish today?"` (preserves current failure contract). Log the failure with `signal_type` for debugging.
      - Migration rollback: `down()` drops `signal_type`; no data loss (rows with non-null `signal_type` lose that label on rollback — acceptable since it's pure analytics metadata).
    - **Rollback strategy.** Feature-flag escape hatch: `pulse_signal_detectors=""` (empty string) → skip new pipeline entirely, fall through to legacy `_generate_ai_question` (preserve the function, don't delete, until the new path has burned in for a week). This gives a 1-line env change to revert behavior without redeploying.
    - **Migration plan.** Deploy flow: (1) apply 0014 migration, (2) deploy code with feature flag defaulting to new path, (3) watch next 7 pulses via `parsed_data.signal_trace`, (4) if bad, flip `pulse_signal_detectors=""` to fall back. Week 2 cleanup: remove legacy `_generate_ai_question` if signals burn in well.

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

Read the architect's plan. Implement exactly as specified.

### Step 1 — Write tests first (mandatory)

Following the Architect's test plan, write these test files in this order:

1. `tests/test_pulse_signals_context.py` — `build_morning_context` builder tests: happy path, weather-fetch-fail, empty calendar, no-recent-memories; uses `async_session`, mocks httpx for weather.
2. `tests/test_pulse_signals_detectors.py` — one test class per detector; hand-crafted `MorningContext` fixtures; covers fire + not-fire + edge cases.
3. `tests/test_pulse_signals_ranker.py` — ranker pure-function tests: empty, below-threshold, above-threshold, tie-break.
4. `tests/test_pulse_signals_prompts.py` — rendering tests with mocked `llm.complete`; verifies per-signal-type prompt routing, `<user_input>` wrapping, ISO date injection, 80-token cap, and the Haiku-failure fallback.
5. `tests/test_weather_client.py` — Open-Meteo client: success, timeout, 429, schema mismatch all return None or raise gracefully.
6. `tests/test_pulse_signal_type_migration.py` — applies migration 0014, asserts column exists, nullable, round-trips a value and a NULL.
7. Extend `tests/test_pulse_sync.py` — `_format_pulse_content` for each signal_type and legacy NULL.
8. Extend `tests/test_pulse.py` — silence path writes row with `status="silent"`, skips Discord send; legacy fallback via `pulse_signal_detectors=""`; idempotency on silent rows.
9. `web/__tests__/morning-pulse.silence.test.tsx` and `web/__tests__/morning-pulse.label.test.tsx` — silence card renders; "Your answer" vs "Thoughts" label rule.

Run the tests with `make test` (backend) and `cd web && npm test` (frontend).

Confirm they fail for the expected reasons (missing `src/pulse_signals/*`, missing `signal_type` column, missing web changes). If they fail for unexpected reasons (import errors, broken fixtures, SQLite FK issues), STOP and reconcile before continuing.

### Step 2+ — Implement production code

Work in this order (foundational → integration):

1. **Alembic migration 0014** — `alembic/versions/0014_pulse_signal_type.py`. `op.add_column("daily_pulses", sa.Column("signal_type", sa.String(32), nullable=True))`. Run `alembic upgrade head` against SQLite to confirm migration applies.

2. **`DailyPulse` ORM + Pydantic schemas** — add `signal_type: Mapped[str | None] = mapped_column(String(32), nullable=True)` to `src/core/models.py::DailyPulse`. Add `signal_type: str | None = None` to `PulseResponse`, `PulseListResponse` items, and any creation schemas. Update `status` literal to include `"silent"` if using status approach.

3. **Settings** — add the 7 new settings to `src/core/config.py` with the defaults specified in the plan.

4. **Weather client** — `src/integrations/weather.py`. Async `fetch_weather_snapshot(settings, http) -> WeatherSnapshot | None`. 5s timeout, swallow all network errors, return None. Dataclass `WeatherSnapshot` with the fields specified.

5. **`MorningContext` builder** — `src/pulse_signals/context.py`. `build_morning_context(session, settings, http)` wires calendar + weather + open_todos + yesterday_pulse + recent_memories into a single dataclass.

6. **Detectors** — `src/pulse_signals/detectors/{focus,opportunity,open}.py`. Pure functions over `MorningContext`.

7. **Ranker** — `src/pulse_signals/ranker.py`. `select_signal(signals, threshold)`. Reads `settings.pulse_signal_detectors` for order + gating.

8. **Prompts + renderer** — `src/pulse_signals/prompts.py` (constants) + `src/pulse_signals/render.py::render_signal(signal, llm, today)`. Each prompt wraps payload in `<user_input>` and injects `today.isoformat()`.

9. **Pulse job rewire** — refactor `src/jobs/pulse.py::send_morning_pulse()` to call `build_morning_context` → `run_detectors` → `select_signal` → if None: silence path (write `status="silent"` row via `POST /v1/pulse` body), else `render_signal` + existing embed + DM flow. Keep legacy `_generate_ai_question` intact as fallback when `settings.pulse_signal_detectors == ""`. Write the full ranker trace into `parsed_data["signal_trace"]`.

10. **Route wiring** — `POST /v1/pulse/start` (src/api/routes/pulse.py:164-243): same rewire, mirror silence handling, write `signal_type` through to DB. Ensure `PATCH /v1/pulse/today` rejects transitions out of `status="silent"` with a clear error (or defines the allowed transition — Architect decides).

11. **`_format_pulse_content` update** — `src/pipeline/pulse_sync.py:23-46` — per-signal-type formatting per the plan.

12. **Discord modal label adaptation** — `src/integrations/modules/pulse_cog.py::PulseModal`. "Your answer" vs "Thoughts?" rule. Skip modal entirely on `status="silent"` (shouldn't even be reachable — silent days get no DM).

13. **Web label + silence card** — `web/components/dashboard/morning-pulse.tsx` + `web/hooks/use-pulse.ts`. Conditional label rule, silence card render, optional debug trace (gated by `pulse_signal_debug_ui`).

After each step:
- Run the test suite (both new and existing tests)
- Fix any failures before continuing

### Final verification

- `make test` (backend, full suite — ~957 tests)
- `make lint` (ruff + black + mypy)
- `cd web && npm test` (Vitest ~247 tests)
- `cd web && npx playwright test` if any e2e pulse tests exist
- `make start` → manually hit `POST /v1/pulse/start` with detectors enabled. Verify DB row has `signal_type`, `parsed_data.signal_trace`. Inspect logs for detector outputs.
- Hand-verify silence path: set `pulse_silence_threshold=10.0` (force silence), trigger pulse, check row `status="silent"`, verify no Discord DM attempted.
- Hand-verify legacy fallback: set `pulse_signal_detectors=""`, trigger pulse, confirm legacy `_generate_ai_question` runs.
- Verify each convention from the Project Context checklist (1–12) against the diff.

Final check:
- Re-read the business context
- Verify the implementation matches the original intent: silence is actually possible; signal attribution is in the DB; adding a new detector touches only `src/pulse_signals/detectors/` + one line in `pulse_signal_detectors` env.
- **Most important invariant:** existing `GET /v1/pulse/today` idempotency holds, Discord persistent view custom_ids (`pulse:log`, `pulse:skip`) survive bot restarts, memory sync on `completed`/`parsed` continues working.

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
   - Did the Implementer stay in Phase 1 scope, or sneak Phase 2 detectors in?

3. **Code quality**
   - Readability, structure, naming
   - Consistency with existing patterns (dataclasses, async session usage, httpx client injection)

4. **Safety**
   - Edge cases (null `signal_type`, empty `pulse_signal_detectors`, weather fetch timeout mid-render)
   - Backward compatibility (existing NULL rows render correctly in web + memory sync)
   - Failure handling (Haiku failure → fallback string; all-detectors-None → silence row)

5. **System impact**
   - Hidden coupling or side effects
   - Performance implications (target < 10s end-to-end per pulse)

6. **Tests & validation**
   - Are tests sufficient and meaningful?
   - Is the detector test pattern reusable for Phase 2 detectors?
   - What critical paths are untested (e.g., race conditions on the silence row, migration rollback)?

7. **Skeptic's concerns (cross-reference Role 2)**
   - For each MEDIUM/HIGH finding from Role 2: is it addressed in code, or consciously deferred with a comment or tech-debt note in PROGRESS.md?
   - Flag silently-ignored items.

8. **Plan fidelity (cross-reference Role 3)**
   - Does the implementation match the Architect's plan?
   - Were any deviations from the plan justified and documented by the Implementer?
   - Flag any undocumented deviation as a scope issue.

9. **Convention compliance (cross-reference Project Context)**
   - Alembic migration (not create_all)? ✓/✗
   - `_get_settings()` lazy helper used in new modules? ✓/✗
   - `<user_input>` delimiters around all memory / todo / calendar text in detector prompts? ✓/✗
   - `date.today()` injected in prompts referencing "today"? ✓/✗
   - `session.commit()` after new-row writes; `session.refresh()` for `signal_type` to populate? ✓/✗
   - Rate limiter decorator on any new route? ✓/✗
   - No new required env vars without defaults? ✓/✗
   - pulse_sync try/except preserved? ✓/✗
   - Discord custom_ids (`pulse:log`, `pulse:skip`) unchanged? ✓/✗
   - Commit message format `feat(pulse):`, `feat(db):`, `test(pulse):`? ✓/✗

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

- **Open-Meteo SSRF / outbound request safety.** URL is constructed from `pulse_weather_latitude` + `pulse_weather_longitude` settings. Verify the client uses a hardcoded `https://api.open-meteo.com` base (not a config-driven URL). Verify lat/long are cast to float before URL-formatting (no injection via env var with malicious content). Verify httpx timeout is set (no indefinite hang → DoS).

- **Prompt injection via memory_items / todos / calendar titles in detector payloads.** User content (memory content strings, todo descriptions, calendar event titles) flows into the signal-specific Haiku prompt as the user message. Verify:
  - Each signal prompt template wraps variable content in `<user_input>...</user_input>` delimiters.
  - System prompt explicitly tells Haiku to ignore any instructions embedded in user_input tags.
  - Even if injected, the worst-case output is a single ≤80-token message to the user — not tool invocation or data exfil — so blast radius is low. Confirm with a trace test.

- **LLM cost-abuse exposure.** One Haiku call per pulse × at most 1 pulse/day × 1 user = trivially bounded. Verify no code path can call `render_signal` more than once per `POST /v1/pulse/start` invocation. Verify weather client is not called per-detector (only in context builder).

- **`parsed_data.signal_trace` disclosure.** The trace includes raw detector payloads — may contain calendar titles, todo descriptions, memory excerpts. `GET /v1/pulse/today` returns `parsed_data`. Confirm this route is API-key gated (it is — `_PUBLIC_PATHS` exclusion stays). Confirm the trace is not written to any log that external services could read.

- **Silent-status row as an auth bypass vector?** No — status="silent" is a DB value, `/v1/pulse/*` routes still require API key. Confirm the silence path does not create any unauthenticated endpoint or side-effect.

Additionally evaluate (standard checklist):
- Authentication & authorization — are new/modified routes properly protected? (Existing `@limiter.limit()` + API key middleware preserved?)
- Input validation & injection — SQL (all through ORM), XSS (web renders `ai_question` in a blockquote — confirm React escapes by default and no `dangerouslySetInnerHTML` is used), prompt injection (see above).
- Rate limiting & abuse — new settings do not add new endpoints. Existing rate limits on `POST /v1/pulse/start` are unchanged.
- Data at rest & in transit — `signal_type` is a free-form short string; no PII. Memory excerpts in `parsed_data.signal_trace` could be sensitive — ensure it's not included in any error response body or log line beyond structlog at debug level.
- Dependencies — Open-Meteo via `httpx` (already a dep); no new packages. Confirm via `git diff pyproject.toml`.

Output:
- **CRITICAL** — must fix before deployment (SSRF, prompt injection exploit path, auth bypass, secret leak)
- **ADVISORY** — risks to document and accept consciously (e.g., Open-Meteo availability, LLM output variance)
- **HARDENING** — optional defense-in-depth improvements (e.g., weather response schema validation with Pydantic, daily detector-invocation cap, structured audit log for silent days)

For each CRITICAL issue, provide a concrete remediation.

Loop-back rules:
- **CRITICAL issues** → return to ROLE 4 with explicit fixes required. After fixes, return to ROLE 5 for re-review, then return here (ROLE 6) and increment review cycle.
- **Review cycle 2 with unresolved CRITICAL issues** → mark the task **BLOCKED**. List all unresolved issues with context. Stop.
- **No CRITICAL issues** → provide final security sign-off.

---

## Completion

**TASK COMPLETE** when Role 5 and Role 6 both approve with no CRITICAL issues.
**BLOCKED** if any reviewer's cycle cap (2) is reached with unresolved CRITICAL issues — stop and escalate to the user.

---

## Verification (end-to-end)

Once Role 5 and Role 6 approve, the user verifies:

1. `make test` — full backend suite passes (target: ~960+ tests, zero regressions).
2. `cd web && npm test` — frontend tests pass.
3. `make lint` — clean.
4. `make start` then:
   - `curl -X POST http://localhost:8000/v1/pulse/start -H "X-API-Key: $OPEN_BRAIN_API_KEY"` — inspect DB row: `signal_type` set, `parsed_data.signal_trace` populated.
   - Force silence: set `PULSE_SILENCE_THRESHOLD=10.0`, delete today's row, re-trigger → `status="silent"`, no Discord DM.
   - Legacy fallback: `PULSE_SIGNAL_DETECTORS=""`, delete row, re-trigger → legacy `_generate_ai_question` runs; `signal_type=NULL`.
5. MCP check via Open Brain: `mcp__open-brain__get_context` with a pulse-related query — confirm recent pulse memories still surface in RAG results after a full end-to-end pulse cycle (sync on `completed`/`parsed` still working).
6. Production deploy: apply migration 0014, roll out code, monitor next 7 pulses, review signal distribution. If bad, flip `PULSE_SIGNAL_DETECTORS=""` to revert without redeploy.

---

## Critical files (to be modified)

- **New:**
  - `src/pulse_signals/__init__.py`
  - `src/pulse_signals/context.py`
  - `src/pulse_signals/ranker.py`
  - `src/pulse_signals/prompts.py`
  - `src/pulse_signals/render.py`
  - `src/pulse_signals/detectors/__init__.py`
  - `src/pulse_signals/detectors/opportunity.py`
  - `src/pulse_signals/detectors/focus.py`
  - `src/pulse_signals/detectors/open.py`
  - `src/integrations/weather.py`
  - `alembic/versions/0014_pulse_signal_type.py`
  - `tests/test_pulse_signals_context.py`
  - `tests/test_pulse_signals_detectors.py`
  - `tests/test_pulse_signals_ranker.py`
  - `tests/test_pulse_signals_prompts.py`
  - `tests/test_weather_client.py`
  - `tests/test_pulse_signal_type_migration.py`
  - `web/__tests__/morning-pulse.silence.test.tsx`
  - `web/__tests__/morning-pulse.label.test.tsx`

- **Modified:**
  - `src/core/models.py` (DailyPulse + `signal_type` column)
  - `src/core/config.py` (7 new settings)
  - `src/jobs/pulse.py` (rewire generation; keep legacy as fallback)
  - `src/api/routes/pulse.py` (silence path, `signal_type` in response; `POST /v1/pulse/start` rewire)
  - `src/pipeline/pulse_sync.py` (per-signal-type formatting in `_format_pulse_content`)
  - `src/integrations/modules/pulse_cog.py` (modal label rule)
  - `web/components/dashboard/morning-pulse.tsx` (label rule + silence card)
  - `web/hooks/use-pulse.ts` (silence state handling if needed)
  - `tests/test_pulse.py` (silence path + legacy fallback)
  - `tests/test_pulse_sync.py` (`_format_pulse_content` per signal_type)

## Reusable existing utilities (do not duplicate)

- `src/integrations/calendar.py::fetch_today_events` — reuse as-is
- `src/llm/client.py::AnthropicClient.complete` — reuse for signal rendering
- `src/jobs/pulse.py::_fetch_open_todos` — reuse in `MorningContext` builder
- `src/jobs/pulse.py::_build_morning_embed`, `_build_pulse_components`, `_send_pulse_dm` — reuse as-is for the fire-signal delivery path
- `src/pipeline/pulse_sync.py::_try_pulse_sync` — trigger unchanged on `completed`/`parsed`
- `tests/conftest.py::_make_mock_llm`, `mock_voyage_client`, `async_session`, `set_test_env` — reuse for new test files
