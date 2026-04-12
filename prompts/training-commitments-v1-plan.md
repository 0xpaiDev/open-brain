# Training & Commitments V1 — Consolidated Plan

Session 1 output. Handoff artifact for Session 2 (Roles 4–6).

---

## ROLE 1 — EXPLORER FINDINGS REPORT

### 1.1 DailyPulse Model (`src/core/models.py:448-477`)

**Schema:**
```python
class DailyPulse(Base):
    __tablename__ = "daily_pulse"
    id            = UUID PK, default uuid4
    pulse_date    = DateTime(timezone=True), NOT NULL, UNIQUE
    raw_reply     = Text, nullable
    sleep_quality = Integer, nullable
    energy_level  = Integer, nullable
    wake_time     = String(10), nullable
    parsed_data   = JSON_TYPE, nullable
    ai_question   = Text, nullable
    ai_question_response = Text, nullable
    notes         = Text, nullable
    status        = String(20), default "sent"
    discord_message_id = String(30), nullable
    created_at    = DateTime(timezone=True), server_default now()
    updated_at    = DateTime(timezone=True), server_default now(), onupdate now()
```

**Lifecycle:** Created by `POST /v1/pulse/start` (status="sent"). Mutated by `PATCH /v1/pulse/today` (only non-None fields applied — conditional assignment pattern). Sync to memory triggered when status reaches "completed" or "parsed".

**No relationships** to MemoryItem — linking is indirect via `RawMemory.metadata_["pulse_id"]`.

### 1.2 Pulse Routes (`src/api/routes/pulse.py`)

| Endpoint | Purpose |
|---|---|
| `POST /v1/pulse/start` (L158-237) | Create today's pulse with AI question |
| `POST /v1/pulse` (L243-278) | Create pulse for specific date |
| `GET /v1/pulse/today` (L285-312) | Fetch today's pulse or 404 |
| `PATCH /v1/pulse/today` (L318-375) | Update reply fields (KEY for nutrition extension) |
| `GET /v1/pulse` (L381-407) | Paginated history |
| `GET /v1/pulse/{pulse_date}` (L414-459) | Get by date |

**PATCH behavior (critical):** Only non-None fields are applied via individual `if body.X is not None` checks. New nullable fields added to `PulseUpdate` and `DailyPulse` will be safely ignored when not submitted. Existing pulse records with NULL in new columns will not break.

**Pydantic schemas:**
- `PulseUpdate` (L74-94): All fields `| None = None`. Validators for sleep/energy (1-5) and status (enum).
- `PulseResponse` (L99-113): All DailyPulse columns mirrored.

### 1.3 Pulse Sync (`src/pipeline/pulse_sync.py`)

**Pattern:** `sync_pulse_to_memory(session, pulse, voyage_client)` →
1. Format content via `_format_pulse_content(pulse)` — joins non-None field strings
2. Embed via Voyage API
3. Supersede existing memory_items matching `RawMemory.metadata_["pulse_id"]`
4. Create `RawMemory(source="daily-pulse", metadata_={"pulse_id": ...})`
5. Create `MemoryItem(type="daily_pulse", base_importance=0.5, embedding=...)`
6. Commit

**Best-effort wrapper** `_try_pulse_sync()` (L35-46 in pulse.py): catches all exceptions, logs warning, never raises. Imported lazily inside function body.

### 1.4 Todo Sync (`src/pipeline/todo_sync.py`)

Same pattern as pulse sync but with:
- Event-type-driven content formatting ("todo" vs "todo_completion")
- Priority-to-importance mapping: high=0.7, normal=0.5, low=0.3
- `supersede_memory_for_todo()` helper for hard-delete path (marks `is_superseded=True` without writing new embedding)

### 1.5 Memory Service (`src/api/services/memory_service.py:48-139`)

**`ingest_memory(session, text, source, metadata, supersedes_id)`** →
1. SHA-256 content hash with 24h dedup window
2. Validate supersedes_id if provided
3. Create `RawMemory` + `RefinementQueue` atomically
4. Returns `IngestResult(raw_id, status="queued"|"duplicate", supersedes_id)`

**Key:** This flows through the full refinement pipeline (Claude extraction + Voyage embedding). No bypass mechanism for pre-structured data. The worker picks up RefinementQueue entries and runs the full extraction prompt.

### 1.6 Constants (`src/pipeline/constants.py`)

```python
AUTO_CAPTURE_SOURCES = frozenset({"claude-code", "claude_code_memory", "claude_code_history", "claude_code_project"})
TASK_SKIP_SOURCES = AUTO_CAPTURE_SOURCES | {"claude-code-manual", "daily-pulse"}
```

New sources for Strava/commitments need to be registered here.

### 1.7 Config (`src/core/config.py`)

Settings pattern: `BaseSettings` with `model_config = ConfigDict(env_file=".env")`. Lazy init via `get_settings()`. `SecretStr` for API keys. Feature flags for modules (`module_pulse_enabled`, etc.).

**Timezone:** `pulse_timezone: str = "UTC"` (L89). Used by `_today_midnight_utc()` in pulse routes to determine day boundaries.

### 1.8 MemoryItem Model (`src/core/models.py:110-161`)

Key columns: `id`, `raw_id` (FK→raw_memory), `type` (String 50), `content`, `summary`, `base_importance`, `dynamic_importance`, `importance_score` (GENERATED), `embedding` (vector 1024), `supersedes_id`, `is_superseded`, `project` (String 100, indexed).

**No `tags` column exists.** Only `project` (single string) and `type` for categorization.

### 1.9 Dashboard (`web/app/dashboard/page.tsx:1-27`)

```tsx
<div className="py-8 space-y-6">
  <OverdueModal />
  <h1>Today</h1>           {/* title + date */}
  <MorningPulse />
  <CalendarStrip />
  <TaskList />
</div>
```

Client-rendered. Each component fetches its own data. Tailwind spacing `space-y-6`.

### 1.10 TaskList Component (`web/components/dashboard/task-list.tsx`, ~1017 lines)

Header with icon + count badge. Search input. Label filter chips. Tabs: Today / This Week / All. History collapsible. AddTaskForm at bottom. Uses `useTodos()` and `useTodoLabels()` hooks.

**Component patterns:** `TaskRow` (L387-599), `DoneTaskRow` (L602-613), `AddTaskForm` (L621-749), `EditTodoSheet` with BottomSheet (L252-385), `DeferPopover` (L84-160).

### 1.11 MorningPulse Component (`web/components/dashboard/morning-pulse.tsx`, ~320 lines)

States: PulseSkeleton → NoPulse → PulseForm → PulseSummary.

**PulseForm layout:** Two-column grid (md breakpoint). Left: AI question + answer + notes. Right: wake time + sleep quality (1-5 circles) + energy level (1-5 circles). Submit button at bottom.

**PulseSummary:** Compact badges (wake time, sleep stars, energy bolts, AI Q&A, notes).

**Design tokens in use:** `bg-surface-container`, `bg-surface-container-high`, `rounded-2xl`, `bg-gradient-to-r from-primary to-primary-container`, `text-on-primary`, `text-on-surface-variant`.

### 1.12 Settings Page (`web/app/settings/page.tsx`, ~209 lines)

Three sections: RAG Chat (model selector), Voice Input (language select), Projects (CRUD with color picker). Uses `useProjectLabels()` hook.

### 1.13 API Middleware (`src/api/middleware/auth.py`)

```python
_PUBLIC_PATHS = {"/health", "/ready"}
```

All requests not in `_PUBLIC_PATHS` require valid `X-API-Key` header. No per-route or pattern-based exemptions. To exempt Strava webhook, must add paths to `_PUBLIC_PATHS`.

### 1.14 Cron Jobs (`src/jobs/`)

`pulse.py`, `importance.py`, `synthesis.py`, `runner.py`. All use `datetime.now(UTC)`. Job execution tracked in `job_runs` table via `run_tracked()` wrapper.

**Timezone:** Jobs use UTC internally. Day boundary calculation in pulse routes uses `pulse_timezone` setting. No job currently implements timezone-aware day rollover for miss detection.

### 1.15 Alembic Migrations (`alembic/versions/`)

9 migrations (0001-0009). Latest: 0009 enables RLS on all 18 tables. Naming: `{NNNN}_{action}_{target}.py`. All new tables must include `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` in upgrade.

### 1.16 CSS Design System (`web/app/globals.css`)

**MD3 dark theme.** Key tokens:
- `--color-primary: #adc6ff` (blue), `--color-primary-container: #4d8eff`
- `--color-tertiary: #ffb3ad` (salmon/red), `--color-tertiary-container: #ff5451`
- `--color-surface: #131313`, `--color-surface-container: #201f1f`, `--color-surface-container-high: #2a2a2a`
- `--color-on-surface: #e5e2e1`, `--color-on-surface-variant: #c2c6d6`
- `--color-error: #ffb4ab`, `--color-outline: #8c909f`
- Fonts: Space Grotesk (headlines), Inter (body/label)
- Border radius: `--radius: 0.5rem`, uses `rounded-2xl` for cards

**Existing patterns:** `bg-surface-container rounded-2xl p-6` for cards, `bg-gradient-to-r from-primary to-primary-container text-on-primary` for CTAs, `active:scale-95 transition-transform` for press feedback.

### 1.17 Surprises / Non-Obvious

1. **No tags column on memory_items** — only `project` (single string) and `type`. Tag system requires a new column or table.
2. **ingest_memory() always queues for full refinement** — no bypass for pre-structured data. Weekly training summary will be re-processed by Claude extraction prompt.
3. **Pulse and todo sync bypass ingest_memory()** — they create RawMemory + MemoryItem directly (with embedding), skipping the refinement queue entirely. This is the pattern for pre-structured data.
4. **Soft FKs for labels** — todo_labels and project_labels use String columns, not real FK constraints. Allows delete without cascade.
5. **Auth middleware is path-set based** — simple `_PUBLIC_PATHS` set check, easy to extend for Strava webhook.
6. **Always dark theme** — no light mode. All new UI must target dark palette only.

---

## ROLE 2 — SKEPTIC RECONCILED FINDINGS

### Challenge 1: DailyPulse Column Extension Safety
**Rating: MEDIUM → Resolved**

**Evidence:** `PATCH /v1/pulse/today` (L350-365) uses individual `if body.X is not None` checks for each field. New nullable columns (`clean_meal`, `alcohol`) with `None` defaults in `PulseUpdate` will be safely skipped when not submitted. Existing pulse records will have NULL in new columns — this is fine because:
- `_format_pulse_content()` (pulse_sync.py:23-42) already skips None fields (`if pulse.X is not None`)
- `PulseSummary` component conditionally renders only populated fields

**Remaining concern:** The PulseForm component renders a fixed set of fields. New fields must be added to both the form AND the summary. The form's two-column grid layout needs to accommodate the new fields without breaking the responsive layout.

**Resolution:** Add new fields to PulseForm's right column (alongside sleep/energy), render as simple toggles. Add to PulseSummary as conditional badges. Add to `_format_pulse_content()` for memory sync.

### Challenge 2: Tag Storage on memory_items
**Rating: HIGH**

**Evidence:** `memory_items` has NO `tags` column (confirmed by reading model at L110-161). Only `project` (String 100, single value) and `type` (String 50, single value). The spec calls for colon-namespaced tags (`training:strava`, `training:commitment`).

**Options considered:**
1. **New `tags` column on memory_items** — JSONB array. Simple, queryable with `@>` operator in PostgreSQL, requires GIN index.
2. **Separate `memory_tags` junction table** — normalized, but overkill for single-user system.
3. **Abuse `project` field** — single string, cannot hold multiple tags.

**Resolution:** Add a `tags` column to `memory_items` as `JSONB` (default `[]`). Use `.with_variant(JSON, "sqlite")` for test compat. Add GIN index in migration. Query with PostgreSQL `@>` operator (contains). For SQLite tests, use JSON functions.

### Challenge 3: Strava Webhook Auth Exemption
**Rating: HIGH → Resolved**

**Evidence:** `_PUBLIC_PATHS = {"/health", "/ready"}` in `src/api/middleware/auth.py:12`. Simple set membership check. Strava webhook needs GET (verification) and POST (events) at a public endpoint.

**Resolution:** Add Strava webhook paths to `_PUBLIC_PATHS`: `{"/health", "/ready", "/v1/strava/webhook"}`. Both GET and POST share the same path. POST validates Strava's HMAC-SHA256 signature via `X-Hub-Signature` header (replaces API key auth with webhook-specific auth).

### Challenge 4: Commitment "Miss" Detection Timezone
**Rating: MEDIUM → Resolved**

**Evidence:** `pulse_timezone` setting (config.py:89) is the established precedent. `_today_midnight_utc()` in pulse.py (L143-152) converts configured timezone to UTC midnight for day boundary comparison. Tests verify this (test_pulse.py:499-520).

**Resolution:** The commitment miss detection cron job must use the same `pulse_timezone` setting for day boundaries. "Yesterday" in the user's timezone = the day to check for misses. Reuse `_today_midnight_utc()` pattern or import it.

### Challenge 5: Weekly Sync and the Ingest Pipeline
**Rating: HIGH → Resolved with design decision**

**Evidence:** `ingest_memory()` (memory_service.py:48-139) creates `RawMemory` + `RefinementQueue`. The worker's refinement pipeline runs Claude extraction + Voyage embedding on queued items. The weekly training summary is already structured — double-processing through Claude extraction would:
1. Waste an LLM call
2. Risk mangling the structured format
3. Add latency

**But:** `pulse_sync.py` and `todo_sync.py` show the alternative pattern — create `RawMemory` + `MemoryItem` directly with a pre-computed embedding, bypassing the refinement queue entirely. This is exactly the right pattern for pre-structured data.

**Resolution:** Weekly training sync should follow the pulse/todo sync pattern: create `RawMemory(source="training-weekly")` + `MemoryItem(type="training_weekly", embedding=...)` directly. Skip the refinement queue. Register `"training-weekly"` in `TASK_SKIP_SOURCES` to prevent Task extraction.

### Additional Challenges

**MEDIUM: Commitment entry partial logging** — spec says "partial logging within the day (e.g., 10 in morning + 10 later)". This means logging adds to the day's count, not replaces. The API must use `SET count = count + delta` or track individual log entries. If using a single `logged_count` column, concurrent adds could race. Resolution: Use `logged_count += delta` with optimistic locking (version column or just accept last-write-wins for single-user).

**MEDIUM: Strava TSS availability** — TSS (Training Stress Score) is not universally available from Strava API. It's only on rides with a power meter. Activities may have estimated TSS or none. Resolution: Store TSS as nullable. Weekly goal progress uses whichever metric is available (TSS preferred, duration as fallback).

---

## ROLE 3 — ARCHITECT IMPLEMENTATION PLAN

### 3.1 Data Model

#### New Tables

**`commitments`** — Challenge definitions
```
id              UUID PK, default uuid4
name            String(100), NOT NULL          -- "Push-ups challenge"
exercise        String(100), NOT NULL          -- "push-ups"
daily_target    Integer, NOT NULL              -- 50
metric          String(20), default "reps"     -- "reps" | "minutes" | "tss"
start_date      Date, NOT NULL
end_date        Date, NOT NULL
status          String(20), default "active"   -- "active" | "completed" | "abandoned"
created_at      DateTime(tz), server_default now()
updated_at      DateTime(tz), server_default now(), onupdate now()
```

Rationale: Separate table (not a column on todos) because commitments have fundamentally different semantics — daily entries, streak tracking, no defer. `metric` field allows weekly-goal commitments (TSS from Strava) alongside daily-rep commitments.

**`commitment_entries`** — One row per commitment per day
```
id              UUID PK, default uuid4
commitment_id   UUID FK → commitments.id, NOT NULL
entry_date      Date, NOT NULL
logged_count    Integer, default 0
status          String(20), default "pending"  -- "pending" | "hit" | "miss"
created_at      DateTime(tz), server_default now()
updated_at      DateTime(tz), server_default now(), onupdate now()

UNIQUE(commitment_id, entry_date)
INDEX(commitment_id, entry_date)
```

Rationale: Pre-generated entries per day (created on commitment creation or via daily cron). `logged_count` is incremented by log actions. Status transitions: pending → hit (when logged_count >= daily_target) or pending → miss (by nightly cron). No "undo" — once missed, it stays missed. For weekly metrics (TSS), entries represent the week, not individual days.

**`strava_activities`** — Cached Strava activity data
```
id              UUID PK, default uuid4
strava_id       BigInteger, NOT NULL, UNIQUE   -- Strava's activity ID
activity_type   String(50)                     -- "Ride", "Run", etc.
name            String(200)
distance_m      Float, nullable                -- meters
duration_s      Integer, nullable              -- seconds
tss             Float, nullable                -- Training Stress Score (nullable: not all rides have power)
avg_power_w     Float, nullable
avg_hr          Integer, nullable
elevation_m     Float, nullable
started_at      DateTime(tz), NOT NULL
raw_data        JSON_TYPE, nullable            -- Full Strava API response for future use
created_at      DateTime(tz), server_default now()
```

Rationale: Denormalize key metrics for fast dashboard queries. Keep `raw_data` JSON for anything we might need later without schema changes. `strava_id` UNIQUE prevents duplicates from webhook retries.

#### Extensions to Existing Tables

**`daily_pulse`** — Add 2 nullable Boolean columns:
```
clean_meal      Boolean, nullable              -- True = clean eating day, False = cheat
alcohol         Boolean, nullable              -- True = had alcohol, False = none
```

Rationale: Nullable booleans. Existing records get NULL (= not yet answered). PATCH endpoint's `if body.X is not None` pattern handles this cleanly.

**`memory_items`** — Add 1 nullable JSONB column:
```
tags            JSONB, nullable, default '[]'  -- Array of colon-namespaced strings
```

With GIN index: `CREATE INDEX ix_memory_items_tags ON memory_items USING GIN (tags)`.
ORM: `mapped_column(JSON_TYPE, nullable=True, default=list)` with `.with_variant()` for SQLite.

### 3.2 Migration Strategy

**Single migration: `0010_training_commitments.py`**

Upgrade:
1. Create `commitments` table
2. Create `commitment_entries` table
3. Create `strava_activities` table
4. Add `clean_meal` and `alcohol` columns to `daily_pulse`
5. Add `tags` column to `memory_items`
6. Create GIN index on `memory_items.tags`
7. Enable RLS on all 3 new tables
8. Add unique constraint on `commitment_entries(commitment_id, entry_date)`
9. Add unique constraint on `strava_activities(strava_id)`

Downgrade:
1. Drop `tags` column from `memory_items`
2. Drop `clean_meal`, `alcohol` columns from `daily_pulse`
3. Drop `strava_activities`, `commitment_entries`, `commitments` (in FK order)

Rationale: Single migration keeps the feature atomic. All additions are nullable or new tables — safe to apply to a running system. Downgrade drops in reverse order.

### 3.3 API Design

#### Commitment Endpoints

| Method | Path | Purpose | Rate Limit |
|---|---|---|---|
| `POST /v1/commitments` | Create a new commitment | 10/min |
| `GET /v1/commitments` | List commitments (active by default, `?status=all`) | 30/min |
| `GET /v1/commitments/{id}` | Get commitment with entries | 30/min |
| `PATCH /v1/commitments/{id}` | Update commitment (abandon, etc.) | 10/min |
| `POST /v1/commitments/{id}/log` | Log count for today's entry | 30/min |

**POST /v1/commitments** creates the commitment row AND pre-generates `commitment_entries` for each day in the range. For weekly metric commitments (TSS), generate one entry per week instead.

**POST /v1/commitments/{id}/log** body: `{ "count": 10 }`. Increments `logged_count` on today's entry. Auto-transitions status to "hit" if `logged_count >= daily_target`. Returns updated entry with streak info.

#### Strava Endpoints

| Method | Path | Purpose | Auth |
|---|---|---|---|
| `GET /v1/strava/webhook` | Webhook verification (Strava subscription) | PUBLIC |
| `POST /v1/strava/webhook` | Webhook event receiver | PUBLIC (HMAC verified) |
| `GET /v1/strava/activities` | List cached activities | API key |

**Webhook auth:** Add `"/v1/strava/webhook"` to `_PUBLIC_PATHS` in auth middleware. POST validates `X-Hub-Signature` header (HMAC-SHA256 of body with verify token). GET echoes `hub.challenge` when `hub.verify_token` matches.

#### Training Endpoints

| Method | Path | Purpose | Rate Limit |
|---|---|---|---|
| `POST /v1/training/weekly-sync` | Trigger weekly training summary sync | 5/min |
| `GET /v1/training/summary` | Get current week's training data | 30/min |

#### Pulse Extension

No new endpoints. Extend existing `PulseUpdate` schema with `clean_meal: bool | None = None` and `alcohol: bool | None = None`. Extend `PulseResponse` similarly.

### 3.4 Strava Integration

**OAuth:** Store `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `STRAVA_VERIFY_TOKEN`, `STRAVA_ACCESS_TOKEN`, `STRAVA_REFRESH_TOKEN` as env vars. All `SecretStr` except `STRAVA_CLIENT_ID` (public) and `STRAVA_VERIFY_TOKEN`.

Rationale: Single-user system — no need for DB-stored OAuth per user. Token refresh can be manual or automated via a refresh job.

**Webhook flow:**
1. **Verification (GET):** Strava sends `hub.mode=subscribe`, `hub.challenge=<token>`, `hub.verify_token=<your_token>`. Respond with `{"hub.challenge": <token>}` if verify_token matches.
2. **Event (POST):** Strava sends `{"aspect_type": "create"|"update"|"delete", "object_type": "activity", "object_id": 12345, "owner_id": 67890}`. Validate HMAC signature. On "create"/"update" for activity type: fetch full activity details from Strava API, upsert into `strava_activities`.
3. **Dedup:** `strava_id` UNIQUE constraint handles retries. On conflict, update metrics.

**Activity detail fetch:** `GET https://www.strava.com/api/v3/activities/{id}` with Bearer token. Extract: distance, moving_time, type, average_watts, average_heartrate, total_elevation_gain, name, start_date. TSS calculation: if power data available, compute from normalized power; otherwise leave NULL.

**Rate limiting:** Strava API has 100 requests per 15 minutes. For webhook events, process synchronously (one activity per event). No batching needed for single-user volume.

### 3.5 Weekly Training Sync

**Pattern:** Follow `pulse_sync.py` / `todo_sync.py` — create `RawMemory` + `MemoryItem` directly with pre-computed embedding. Skip the refinement queue.

**New module:** `src/pipeline/training_sync.py`

**Function:** `sync_weekly_training(session, voyage_client)` →
1. Query `commitment_entries` for the past 7 days — compute hits, misses, streaks per commitment
2. Query `strava_activities` for the past 7 days — aggregate distance, duration, TSS
3. Query `daily_pulse` for the past 7 days — aggregate clean_meal count, alcohol count
4. Format into natural language summary string
5. Embed via Voyage API
6. Supersede previous week's training memory (find by `RawMemory.metadata_["week_start"]`)
7. Create `RawMemory(source="training-weekly", metadata_={"week_start": "2026-04-06"})` + `MemoryItem(type="training_weekly", base_importance=0.6, embedding=..., tags=["training:weekly"])`
8. Commit

**Trigger:** `POST /v1/training/weekly-sync` (manual for MVP). Future: cron job on Sunday night.

**Register:** Add `"training-weekly"` to `TASK_SKIP_SOURCES` in constants.py.

### 3.6 Tag System

**Storage:** New `tags` JSONB column on `memory_items`. Default `[]`. Stores array of strings: `["training:strava", "training:weekly"]`.

**Indexing:** GIN index on `tags` column in PostgreSQL. Enables `@>` (contains) queries: `WHERE tags @> '["training:strava"]'::jsonb`.

**SQLite compat:** Use `JSON_TYPE` with `.with_variant()`. Tests use `json_each()` for tag filtering (or skip tag-query tests with PostgreSQL-only markers).

**Application:** Tags are set during sync operations:
- `training_sync.py` sets `tags=["training:weekly"]`
- Strava activity ingestion sets `tags=["training:strava"]`
- Commitment sync sets `tags=["training:commitment"]`

**Query:** Extend `hybrid_search()` to accept optional `tags_filter: list[str]`. If provided, add `AND tags @> :tags_json` to the SQL query. Frontend can pass tags for filtered searches.

**Validation:** Tag strings: 1-50 chars, alphanumeric + colon + hyphen + underscore. Validated in the model or service layer.

### 3.7 Frontend

#### 3.7.1 Dashboard — Commitments Section

**Position:** Between `<CalendarStrip />` and `<TaskList />` in dashboard page.

```tsx
<MorningPulse />
<CalendarStrip />
<CommitmentList />     {/* NEW */}
<TaskList />
```

**CommitmentList component** (`web/components/dashboard/commitment-list.tsx`):
- Header: icon + "Commitments" + active count badge (same pattern as TaskList header)
- For each active commitment: `CommitmentCard`
- Empty state: "No active commitments" with link to settings

**CommitmentCard component:**
- Name + "Day X/Y" progress label
- Streak visualization: row of small circles/indicators for last 7 days (green=hit, red=miss, gray=pending)
- Today's status: if pending, show log button with count input; if hit, show checkmark
- For weekly metric (TSS): progress bar showing current vs target
- Tap "Log" → inline number input (quick-increment: +5, +10, custom) → submits to API → updates card

**Hook:** `useCommitments()` — fetches `GET /v1/commitments?status=active`, exposes `logCount(commitmentId, count)`, `commitments` array.

#### 3.7.2 Settings — Commitment Creation

Add new section to settings page (below Projects):

**"Commitments" section:**
- List of active/completed commitments with status badges
- "New Commitment" form: exercise name, daily target, metric (reps/minutes/tss), start date, end date
- Abandon button on active commitments

#### 3.7.3 Pulse Modal Extension

In `PulseForm` (morning-pulse.tsx), add to the right column (below energy level):

- **Clean meal toggle:** Two-state toggle (Clean / Cheat), default unselected
- **Alcohol toggle:** Two-state toggle (Yes / No), default unselected

Both optional — can submit without selecting either.

In `PulseSummary`, add conditional badges for clean_meal and alcohol.

Extend `submitPulse()` in use-pulse.ts to include `clean_meal` and `alcohol` fields.

### 3.8 Cron Jobs

#### Commitment Miss Detection

**New job:** `src/jobs/commitment_miss.py`

**Schedule:** Run nightly after day boundary (e.g., 23:59 in user's timezone, or 1:00 AM next day).

**Logic:**
1. Get `pulse_timezone` from settings
2. Calculate "yesterday" in that timezone
3. Query `commitment_entries` WHERE `entry_date = yesterday AND status = 'pending'`
4. Set `status = 'miss'` for all matching entries
5. Commit

**Timezone:** Uses `pulse_timezone` setting (same as pulse routes). Configured as `Europe/Vilnius` in production.

#### Weekly Training Sync (future)

**Schedule:** Sunday 22:00 in user's timezone.
**Logic:** Call `sync_weekly_training()` from training_sync.py.

For MVP: manual trigger via `POST /v1/training/weekly-sync`. Cron added later.

### 3.9 Test Plan

#### Backend Tests (pytest)

**Models:**
- `test_commitment_model`: Commitment and CommitmentEntry creation, defaults, constraints
- `test_strava_activity_model`: StravaActivity creation, strava_id uniqueness

**Commitment routes:**
- `test_create_commitment`: POST creates commitment + generates entries for each day
- `test_create_commitment_validation`: Missing fields, end_date before start_date, negative target
- `test_list_commitments`: Default active filter, status=all, empty list
- `test_get_commitment_with_entries`: Returns commitment + entries array with streak info
- `test_log_count`: Increments logged_count, auto-transitions to "hit" when target met
- `test_log_count_already_hit`: Logging more after hit still increments (no cap)
- `test_log_count_missed_entry`: Cannot log on a missed entry (400)
- `test_log_count_future_entry`: Cannot log on future date (400)
- `test_abandon_commitment`: PATCH status to "abandoned"

**Strava webhook:**
- `test_webhook_verification`: GET with correct verify_token returns challenge
- `test_webhook_verification_bad_token`: GET with wrong token returns 403
- `test_webhook_event_create`: POST with valid HMAC creates/updates strava_activity
- `test_webhook_event_invalid_signature`: POST with bad HMAC returns 403
- `test_webhook_event_dedup`: Duplicate strava_id upserts, not duplicates

**Pulse extension:**
- `test_pulse_update_with_nutrition`: PATCH with clean_meal + alcohol updates correctly
- `test_pulse_sync_includes_nutrition`: _format_pulse_content includes clean_meal/alcohol in string

**Training sync:**
- `test_weekly_training_sync`: Creates RawMemory + MemoryItem with correct content, type, tags
- `test_weekly_training_sync_supersedes`: Second sync marks first as superseded

**Tags:**
- `test_memory_item_tags_default`: New memory_items have tags=[]
- `test_memory_item_tags_set`: Can set tags array on creation

**Commitment miss job:**
- `test_miss_detection_marks_pending_as_miss`: Yesterday's pending entries become "miss"
- `test_miss_detection_skips_hit`: Already-hit entries untouched
- `test_miss_detection_timezone`: Respects pulse_timezone for day boundary

#### Frontend Tests (Vitest)

- `test_commitment_list_renders`: Renders active commitments with cards
- `test_commitment_card_log`: Clicking log submits count, updates UI
- `test_commitment_card_streak`: Streak visualization shows correct hit/miss pattern
- `test_pulse_form_nutrition`: Renders clean_meal and alcohol toggles
- `test_pulse_submit_with_nutrition`: Submit includes nutrition fields
- `test_pulse_summary_nutrition`: Summary shows nutrition badges when set

### 3.10 What Stays Unchanged

- `memory_service.ingest_memory()` — not modified, not called by training sync
- `hybrid_search()` — tag filtering is additive, not modifying existing query logic
- `todo_sync.py`, `pulse_sync.py` — untouched
- `TaskList` component — untouched
- `MorningPulse` component's existing fields — new fields are additive
- All existing API endpoints — no breaking changes
- All existing Alembic migrations (0001-0009) — new migration is additive
- Rate limit middleware — same pattern, just new routes decorated
- Discord bot — not involved in this feature

### 3.11 Constraints & Safety

**Performance:**
- Commitment card queries are scoped to active commitments (small set) + their entries (bounded by date range). No performance concern.
- Strava webhook processing is synchronous per event — acceptable for single-user volume.
- GIN index on tags ensures tag filtering doesn't degrade search performance.

**Backward compatibility:**
- All new columns are nullable — existing data is unaffected
- All new tables are additive — no schema changes to existing tables beyond nullable columns
- Frontend changes are additive — existing components gain new optional UI elements

**Failure modes:**
- Strava webhook down: Activities aren't cached. Weekly summary uses whatever data is available. No data loss — Strava retains all data.
- Commitment miss cron fails: Entries stay "pending". Next run catches up (query is idempotent — only flips pending→miss for past dates).
- Training sync fails: No memory item for that week. Manual re-trigger available.

**Rollback:** Downgrade migration drops new tables and columns. Frontend changes can be reverted via git. No destructive operations.

---

## ROLE 3.5 — UI/UX DESIGN BRIEF

### Design System Evaluation

The generated UI/UX design system (Vibrant & Block-based, Barlow Condensed, #F97316 orange) **conflicts with the existing app**. Open Brain uses:
- **MD3 dark theme** with blue primary (#adc6ff), salmon tertiary (#ffb3ad)
- **Space Grotesk + Inter** typography
- **Surface-container card pattern** (rounded-2xl, bg-surface-container)
- **Subtle, information-dense** layout — not bold/energetic/block-based

Per the consistency rule: keep existing tokens, adopt only gap-filling recommendations.

### Color Tokens

**Existing tokens to reuse:**
- Hit/success: `--color-primary` (#adc6ff) or a new green semantic token
- Miss/failure: `--color-tertiary` (#ffb3ad) or `--color-error` (#ffb4ab)
- Pending/neutral: `--color-outline` (#8c909f) or `--color-surface-container-high` (#2a2a2a)
- Progress bar fill: `--color-primary-container` (#4d8eff)

**New tokens (add to globals.css):**
```css
--color-streak-hit: #4ade80;       /* green-400 — distinct from blue primary */
--color-streak-miss: #f87171;      /* red-400 — matches error family */
--color-streak-pending: #6b7280;   /* gray-500 — neutral */
```

Rationale: Using primary blue for "hit" would conflict with its meaning as the app's primary action color. Dedicated green/red for streak indicators is clearer and more accessible. These sit alongside the existing MD3 palette without replacing anything.

### Typography

No new fonts. Use existing:
- **Space Grotesk** (`font-headline`): Commitment name, section headers
- **Inter** (`font-body`): Entry counts, dates, streak labels
- Sizes: follow existing scale. Card titles use `text-lg font-headline`, metadata uses `text-sm text-on-surface-variant`.

### Component Patterns

#### Commitment Card
```
┌─────────────────────────────────────────────┐
│  🏋️ Push-ups Challenge          Day 12/30  │  ← font-headline, text-on-surface
│                                              │
│  ● ● ● ○ ✕ ● ●                  🔥 5-day  │  ← streak dots + streak counter
│                                              │
│  Today: 30/50                    [+10] [Log] │  ← progress + quick-log
│  ████████████░░░░░░░░                        │  ← progress bar
└─────────────────────────────────────────────┘
```

- Container: `bg-surface-container rounded-2xl p-5` (matches MorningPulse)
- Streak dots: 8px circles with `bg-streak-hit`, `bg-streak-miss`, `bg-streak-pending`
- Icons: Lucide icons only (project uses Material Symbols via Lucide wrappers)
- Progress bar: `h-2 rounded-full bg-surface-container-high` track, `bg-primary-container` fill with `transition-all duration-300`

#### Weekly Metric Card (TSS)
Same card shell. Instead of streak dots, show:
- Progress bar: current TSS / target TSS
- Label: "245 / 400 TSS this week"
- Data source badge: "via Strava" in `text-xs text-on-surface-variant`

#### Pulse Nutrition Toggles
```
Clean eating    ○ Yes  ● No        ← segmented control, 2 options
Alcohol         ○ Yes  ● No        ← same pattern
```

- Use segmented button pattern (two adjacent rounded-full buttons)
- Selected: `bg-primary text-on-primary`
- Unselected: `bg-surface-container-high text-on-surface-variant`
- Both default to unselected (neither Yes nor No) — user must tap to set
- Size: `h-9 px-4 text-base md:text-sm` (16px mobile minimum)

#### Log Input (Commitment)
- Inline number display: `text-lg font-headline` showing current count
- Quick-add buttons: `+5`, `+10` pills with `bg-surface-container-high rounded-full px-3 h-8`
- Custom input: tap count to edit, `type="number"` input with `text-base` (16px minimum)
- Submit: primary-styled button, `bg-primary-container text-on-primary-container rounded-full`

### Interaction Patterns

- **Tap to log:** Single tap on quick-add button immediately submits. No confirmation dialog. Optimistic update with rollback on error.
- **Streak animation:** New hit dot scales in from 0 with `transition-transform duration-200`. Respect `prefers-reduced-motion`.
- **Progress bar fill:** `transition-[width] duration-300 ease-out`. Static for reduced motion.
- **Card expand/collapse:** Not needed in V1 — all info visible on card face.

### Anti-Patterns (Avoid)

- No multi-step logging flows — must be < 2 taps to log
- No hiding streak history behind navigation — visible on card
- No color-only hit/miss indication — use filled circle (●) vs cross (✕) shapes alongside colors
- No custom fonts — stick to Space Grotesk + Inter
- No bold/energetic styling (reject generated design system) — keep the calm, information-dense MD3 aesthetic
- No emoji as functional icons — use Lucide SVG icons
- No duplicate DOM for responsive layouts — use single DOM with flex-wrap + responsive classes

### Pre-Delivery Checklist

- [ ] Streak indicators: contrast ratio >= 4.5:1 against `bg-surface-container` (#201f1f). Green #4ade80 on #201f1f = 8.2:1 ✓. Red #f87171 on #201f1f = 5.1:1 ✓.
- [ ] All clickable elements have `cursor-pointer`
- [ ] Focus states visible on log buttons and number inputs (ring-2 ring-ring)
- [ ] `prefers-reduced-motion`: disable scale animations, progress bar transitions
- [ ] All `<input>` elements use `text-base md:text-sm` (16px mobile minimum)
- [ ] Responsive: cards stack vertically on mobile, streak dots wrap if needed
- [ ] No new dependencies for icons (Lucide already installed)
- [ ] Nutrition toggles have accessible labels (`aria-label` or visible label text)

---

## Session 1 Complete

This file is the single source of truth for Session 2 (Roles 4–6). The Implementer should read this file and the Business Context / Project Context sections of `prompts/training-commitments-v1.md` before proceeding.
