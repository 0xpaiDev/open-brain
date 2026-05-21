# Morning Pulse Briefing — Design Spec

**Date:** 2026-05-21
**Status:** Approved

## Context

The morning pulse currently generates a single reflective or operational question via an LLM renderer. The question is always generic — it does not surface what actually matters that day. The goal is to replace it with an actionable briefing: a bullet list assembled from real signals (deadlines, commitment pace, calendar events, calendar named days). The briefing always renders — presence/absence is not the urgency signal, the content is.

## Goal

Replace the single-question pulse with a multi-signal bullet briefing that is fast, specific, and non-repetitive. Remove the `notes` field. Shift cron -1h.

---

## Signal Detectors

All detectors run every morning. All signals above the silence threshold contribute a bullet — no single winner. Order: deadline → commitment pace → named day → focus → open (fallback).

### 1. Deadline detector *(new)*
- **Source:** `TodoItem` where `due_date == today`
- **Fires if:** ≥1 todo due today
- **Urgency:** 8.0
- **Bullet (template):** `"N task(s) due today: Title1, Title2, Title3"` (max 3 titles, then `"…"`)
- **File:** `src/pulse_signals/detectors/deadline.py`

### 2. Commitment pace detector *(new)*
- **Source:** all aggregate `Commitment` rows; reuse `_compute_pace()` from `src/api/routes/commitments.py:323`
- **Fires if:** any commitment with `pace.overall < 0.85` (behind) or `pace.overall > 1.2` (well ahead)
- **Urgency:** 7.5
- **Bullet:** LLM-rendered (commitment_pace_system_prompt). Payload: commitment name, metric, actual, target, pace, yesterday_activity (bool). Example behind: `"Cycling behind pace — 34 km logged of 50 km target (68%)"`. Example ahead + rested: `"Strong cycling week — well ahead of pace. Good day to rest."`
- **File:** `src/pulse_signals/detectors/commitment_pace.py`

### 3. Calendar named-day detector *(new)*
- **Source:** `calendar.events` — all-day events from Google Calendar
- **Fires if:** any all-day event exists for today (birthdays, holidays, etc.)
- **Urgency:** 6.5
- **Bullet (template):** `"Today: EventTitle"` (one bullet per matching event, max 3)
- **Detection:** `CalendarEvent.all_day == True`
- **File:** `src/pulse_signals/detectors/named_day.py`

### 4. Focus detector *(existing, unchanged)*
- **Source:** timed calendar events matching `pulse_focus_keywords`
- **Urgency:** 7.0
- **Bullet:** LLM-rendered (existing focus_system_prompt)
- **File:** `src/pulse_signals/detectors/focus.py` — no changes

### 5. Opportunity detector *(existing, unchanged)*
- **Source:** weather — dry today, wet next 3 days
- **Urgency:** 6.0
- **Bullet:** LLM-rendered (existing opportunity_system_prompt)
- **File:** `src/pulse_signals/detectors/opportunity.py` — no changes

### 6. Open detector *(reworked — fallback only)*
- **Fires if:** always (urgency 5.0 — ensures at least one bullet on quiet days)
- **Bullet (template):**
  - If ≥1 open todo and ≥1 calendar event: `"N open tasks · X event(s) today"`
  - If ≥1 open todo, no events: `"N open tasks — nothing else scheduled"`
  - If no todos, no events: `"Clear schedule — nothing due or scheduled"`
- **No LLM call.** Reflective question prompt removed.
- **File:** `src/pulse_signals/detectors/open.py` — rework

---

## Output Format

`ai_question` DB column stores the full briefing as newline-separated bullets (each prefixed `• `). `signal_type` stores `"briefing"` for all new-format pulses.

**High-signal example:**
```
• Today: Paulius's birthday
• 3 tasks due today: Buy milk, Call dentist, Submit report
• Cycling behind pace — 34 km logged of 50 km target (68%)
• Demo at 14:00 — nail the scope decision before you walk in
```

**Quiet-day example:**
```
• 4 open tasks — nothing else scheduled
```

---

## Backend Changes

| File | Change |
|------|--------|
| `src/pulse_signals/ranker.py` | Rework: return all signals above threshold (list), not single winner |
| `src/pulse_signals/render.py` | New `build_briefing(signals, llm, today)` — iterates list, assembles bullets; LLM called only for commitment_pace and focus bullets |
| `src/pulse_signals/prompts.py` | Delete `_OPEN_BODY` + `open_system_prompt`; add `commitment_pace_system_prompt` |
| `src/pulse_signals/detectors/deadline.py` | New file |
| `src/pulse_signals/detectors/named_day.py` | New file |
| `src/pulse_signals/detectors/commitment_pace.py` | New file |
| `src/pulse_signals/detectors/open.py` | Rework: template-only, no LLM |
| `src/api/routes/pulse.py` | Update `POST /v1/pulse/start` to use multi-signal path; pass `session` to deadline + commitment detectors |
| `src/core/config.py` | Update `pulse_signal_detectors` default: `"deadline,commitment_pace,named_day,focus,opportunity,open"` |
| `crontab` | Shift pulse line: `0 5 * * *` → `0 4 * * *` |

### New migration

- Drop `notes` column from `DailyPulse`
- File: `alembic/versions/0022_drop_pulse_notes.py` (verify latest revision number with `ls alembic/versions/` before creating)

---

## Frontend Changes

| File | Change |
|------|--------|
| `web/components/dashboard/morning-pulse.tsx` | Remove `notes` textarea from form and summary; render `ai_question` as bullet list (split on `\n`, render each line as `<li>`) |
| `web/hooks/use-pulse.ts` | Remove `notes` from submit payload |

---

## Commitment Pace Detector — Key Reuse

- `_compute_pace(targets, progress, start_date, end_date, today)` in `src/api/routes/commitments.py:323` — call directly; returns `{metric: ratio, "overall": ratio}`
- Pace thresholds (matching frontend badge logic in `web/components/dashboard/commitment-list.tsx:164`):
  - `>= 1.0` ahead, `< 0.85` behind (tighter than the 0.7 badge threshold to nudge earlier)
- Detector needs DB session to query `Commitment` rows → pass `session` through detector interface

### New prompt: `commitment_pace_system_prompt`

```
You are writing a single morning nudge about a fitness commitment's pace.
Rules:
- 20 words max, warm but direct.
- If behind: state the gap plainly, no guilt.
- If well ahead and yesterday had activity: suggest rest.
- No questions.
```

---

## Detector Interface Change

Current `detect(ctx: MorningContext) -> Signal | None` is session-less. Deadline and commitment_pace detectors need DB access. Two options:

**Chosen:** add optional `session: AsyncSession | None = None` parameter to the base interface; only deadline and commitment_pace use it. Existing detectors ignore it.

---

## Silence Behaviour

If ALL detectors return `None` (below threshold) — impossible in practice since open detector always fires at 5.0 — status stays `"silent"` as today. The open detector guarantees at least one bullet.

---

## Cron Change

`crontab` line 3: `0 5 * * *` → `0 4 * * *`

Comment update: `# Morning pulse - 04:00 UTC (07:00 Europe/Vilnius summer)`

---

## Verification

1. **Unit tests** — each new detector tested in isolation with mock `MorningContext` and mock session
2. **Ranker test** — verify multi-signal list returned, order correct
3. **Render test** — verify `build_briefing` assembles correct bullet strings, LLM called only for focus/commitment_pace signals
4. **Integration test** — `POST /v1/pulse/start` returns `ai_question` with `•` bullets, `signal_type="briefing"`
5. **Frontend** — bullets render as `<li>` list in the pulse card; notes field absent from form
6. **Migration** — `notes` column dropped cleanly; existing rows unaffected
7. **Cron** — verify `crontab` updated and supercronic picks it up in Docker
