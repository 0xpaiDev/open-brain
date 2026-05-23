---\nstatus: shipped\ncreated: 2026-05-21\nshipped: 2026-05-21\n---

# Morning Pulse Briefing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single generic question with a multi-signal bullet briefing: deadlines, commitment pace, named calendar days, and a fallback summary — always rendered, always actionable.

**Architecture:** All configured detectors run every morning; all signals above the silence threshold contribute a bullet. A new `build_briefing()` assembles bullets via templates (LLM only for focus and commitment_pace). The `notes` field is dropped. Cron shifts -1h.

**Tech Stack:** Python (FastAPI, SQLAlchemy async), Alembic, Next.js/React, Vitest

---

## File Map

**New files:**
- `src/pulse_signals/detectors/deadline.py` — todos due today
- `src/pulse_signals/detectors/named_day.py` — all-day calendar events
- `src/pulse_signals/detectors/commitment_pace.py` — pace behind/ahead check

**Modified files:**
- `src/pulse_signals/ranker.py` — add `select_signals` (all above threshold), wire new detectors in `run_detectors`
- `src/pulse_signals/render.py` — add `build_briefing()`, replace `render_signal` usage
- `src/pulse_signals/prompts.py` — add `commitment_pace_system_prompt`, delete `open_system_prompt`
- `src/pulse_signals/detectors/open.py` — template-only fallback, no LLM
- `src/pulse_signals/__init__.py` — export `build_briefing`, `select_signals`
- `src/api/routes/pulse.py` — use `select_signals` + `build_briefing`
- `src/core/config.py` — update `pulse_signal_detectors` default
- `alembic/versions/0022_drop_pulse_notes.py` — drop `notes` column
- `src/core/models.py` — remove `notes` mapped column
- `web/components/dashboard/morning-pulse.tsx` — render bullets, remove notes field
- `web/hooks/use-pulse.ts` — remove `notes` from submit type
- `web/lib/types.ts` — remove `notes` from `PulseResponse`
- `crontab` — shift pulse to 04:00 UTC

**Test files:**
- `tests/test_pulse_signals_detectors.py` — extend with new detectors
- `tests/test_pulse_signals_ranker.py` — test `select_signals`
- `tests/test_pulse_briefing.py` — new file for `build_briefing`

---

## Task 1: Deadline detector

**Files:**
- Create: `src/pulse_signals/detectors/deadline.py`
- Modify: `tests/test_pulse_signals_detectors.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pulse_signals_detectors.py`:

```python
from datetime import UTC, date, datetime
from sqlalchemy import select
from src.pulse_signals.detectors import deadline as deadline_detector
from src.core.models import TodoItem


class TestDeadlineDetector:
    @pytest.mark.asyncio
    async def test_fires_when_todo_due_today(self, async_session):
        today = date(2026, 5, 21)
        due_dt = datetime(2026, 5, 21, 0, 0, 0, tzinfo=UTC)
        todo = TodoItem(description="Call dentist", status="open", due_date=due_dt)
        async_session.add(todo)
        await async_session.commit()

        ctx = _ctx(today=today)
        signal = await deadline_detector.detect(ctx, session=async_session)
        assert signal is not None
        assert signal.signal_type == "deadline"
        assert signal.urgency == 8.0
        assert "Call dentist" in signal.payload["titles"]

    @pytest.mark.asyncio
    async def test_does_not_fire_when_no_todos_due(self, async_session):
        today = date(2026, 5, 21)
        ctx = _ctx(today=today)
        signal = await deadline_detector.detect(ctx, session=async_session)
        assert signal is None

    @pytest.mark.asyncio
    async def test_does_not_fire_for_future_due_date(self, async_session):
        future_dt = datetime(2026, 5, 22, 0, 0, 0, tzinfo=UTC)
        todo = TodoItem(description="Future task", status="open", due_date=future_dt)
        async_session.add(todo)
        await async_session.commit()

        ctx = _ctx(today=date(2026, 5, 21))
        signal = await deadline_detector.detect(ctx, session=async_session)
        assert signal is None

    @pytest.mark.asyncio
    async def test_caps_titles_at_three(self, async_session):
        due_dt = datetime(2026, 5, 21, 0, 0, 0, tzinfo=UTC)
        for i in range(5):
            async_session.add(TodoItem(description=f"Task {i}", status="open", due_date=due_dt))
        await async_session.commit()

        ctx = _ctx(today=date(2026, 5, 21))
        signal = await deadline_detector.detect(ctx, session=async_session)
        assert signal is not None
        assert len(signal.payload["titles"]) == 3
        assert signal.payload["total_count"] == 5
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/shu/projects/open-brain && python -m pytest tests/test_pulse_signals_detectors.py::TestDeadlineDetector -v 2>&1 | tail -20
```

Expected: ImportError or ModuleNotFoundError (file doesn't exist yet).

- [ ] **Step 3: Create the detector**

Create `src/pulse_signals/detectors/deadline.py`:

```python
"""Deadline detector — fires when todos are due today."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import TodoItem
from src.pulse_signals.context import MorningContext
from src.pulse_signals.ranker import Signal

NAME = "deadline"
_URGENCY = 8.0
_MAX_TITLES = 3


async def detect(ctx: MorningContext, *, session: AsyncSession) -> Signal | None:
    day_start = datetime(ctx.today.year, ctx.today.month, ctx.today.day, tzinfo=UTC)
    day_end = day_start + timedelta(days=1)

    stmt = (
        select(TodoItem)
        .where(
            TodoItem.status == "open",
            TodoItem.due_date >= day_start,
            TodoItem.due_date < day_end,
        )
        .order_by(TodoItem.due_date)
    )
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return None

    titles = [r.description for r in rows[:_MAX_TITLES]]
    return Signal(
        signal_type=NAME,
        urgency=_URGENCY,
        payload={
            "titles": titles,
            "total_count": len(rows),
        },
    )
```

- [ ] **Step 4: Run tests**

```bash
cd /home/shu/projects/open-brain && python -m pytest tests/test_pulse_signals_detectors.py::TestDeadlineDetector -v 2>&1 | tail -20
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /home/shu/projects/open-brain && git add src/pulse_signals/detectors/deadline.py tests/test_pulse_signals_detectors.py && git commit -m "feat(pulse): add deadline detector — todos due today"
```

---

## Task 2: Named-day detector

**Files:**
- Create: `src/pulse_signals/detectors/named_day.py`
- Modify: `tests/test_pulse_signals_detectors.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pulse_signals_detectors.py`:

```python
from src.pulse_signals.detectors import named_day as named_day_detector


def _all_day_event(title: str) -> CalendarEvent:
    return CalendarEvent(
        title=title,
        start="2026-05-21",
        end="2026-05-22",
        location=None,
        calendar="primary",
        all_day=True,
    )


class TestNamedDayDetector:
    def test_fires_on_all_day_event(self):
        calendar = CalendarState(
            fetched_at="2026-05-21T04:00:00Z",
            date="2026-05-21",
            events=[_all_day_event("Paulius's birthday")],
            tomorrow_preview=[],
        )
        ctx = _ctx(calendar=calendar)
        signal = named_day_detector.detect(ctx)
        assert signal is not None
        assert signal.signal_type == "named_day"
        assert signal.urgency == 6.5
        assert "Paulius's birthday" in signal.payload["titles"]

    def test_does_not_fire_on_timed_events_only(self):
        ctx = _ctx(
            calendar=CalendarState(
                fetched_at="2026-05-21T04:00:00Z",
                date="2026-05-21",
                events=[_event("1:1 with Tom")],
                tomorrow_preview=[],
            )
        )
        signal = named_day_detector.detect(ctx)
        assert signal is None

    def test_does_not_fire_with_no_events(self):
        ctx = _ctx()
        signal = named_day_detector.detect(ctx)
        assert signal is None

    def test_caps_at_three_titles(self):
        events = [_all_day_event(f"Event {i}") for i in range(5)]
        calendar = CalendarState(
            fetched_at="2026-05-21T04:00:00Z",
            date="2026-05-21",
            events=events,
            tomorrow_preview=[],
        )
        ctx = _ctx(calendar=calendar)
        signal = named_day_detector.detect(ctx)
        assert signal is not None
        assert len(signal.payload["titles"]) == 3
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/shu/projects/open-brain && python -m pytest tests/test_pulse_signals_detectors.py::TestNamedDayDetector -v 2>&1 | tail -10
```

Expected: ImportError.

- [ ] **Step 3: Create the detector**

Create `src/pulse_signals/detectors/named_day.py`:

```python
"""Named-day detector — fires on all-day calendar events (birthdays, holidays)."""

from __future__ import annotations

from src.pulse_signals.context import MorningContext
from src.pulse_signals.ranker import Signal

NAME = "named_day"
_URGENCY = 6.5
_MAX_TITLES = 3


def detect(ctx: MorningContext) -> Signal | None:
    events = ctx.calendar.events if ctx.calendar else []
    all_day = [e for e in events if e.all_day]
    if not all_day:
        return None

    titles = [e.title for e in all_day[:_MAX_TITLES]]
    return Signal(
        signal_type=NAME,
        urgency=_URGENCY,
        payload={"titles": titles},
    )
```

- [ ] **Step 4: Run tests**

```bash
cd /home/shu/projects/open-brain && python -m pytest tests/test_pulse_signals_detectors.py::TestNamedDayDetector -v 2>&1 | tail -10
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /home/shu/projects/open-brain && git add src/pulse_signals/detectors/named_day.py tests/test_pulse_signals_detectors.py && git commit -m "feat(pulse): add named_day detector — all-day calendar events"
```

---

## Task 3: Commitment pace detector

**Files:**
- Create: `src/pulse_signals/detectors/commitment_pace.py`
- Modify: `tests/test_pulse_signals_detectors.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pulse_signals_detectors.py`:

```python
from datetime import date, timedelta
from src.pulse_signals.detectors import commitment_pace as pace_detector
from src.core.models import Commitment, CommitmentEntry


class TestCommitmentPaceDetector:
    @pytest.mark.asyncio
    async def test_fires_when_behind_pace(self, async_session):
        today = date(2026, 5, 21)
        c = Commitment(
            name="Cycling May",
            cadence="aggregate",
            status="active",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
            targets={"km": 300.0},
            progress={"km": 30.0},  # ~10%, should be ~67% through month
            daily_target=0,
        )
        async_session.add(c)
        await async_session.commit()

        ctx = _ctx(today=today)
        signal = await pace_detector.detect(ctx, session=async_session)
        assert signal is not None
        assert signal.signal_type == "commitment_pace"
        assert signal.urgency == 7.5
        assert signal.payload["pace_overall"] < 0.85
        assert "Cycling May" in signal.payload["name"]

    @pytest.mark.asyncio
    async def test_fires_when_well_ahead(self, async_session):
        today = date(2026, 5, 21)
        c = Commitment(
            name="Cycling May",
            cadence="aggregate",
            status="active",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
            targets={"km": 300.0},
            progress={"km": 280.0},  # well ahead at day 21
            daily_target=0,
        )
        async_session.add(c)
        await async_session.commit()

        ctx = _ctx(today=today)
        signal = await pace_detector.detect(ctx, session=async_session)
        assert signal is not None
        assert signal.payload["pace_overall"] > 1.2

    @pytest.mark.asyncio
    async def test_does_not_fire_on_track(self, async_session):
        today = date(2026, 5, 21)
        # Day 21 of 31 = 67.7% elapsed; 200km of 300km = 66.7% → pace ~0.985 (on track)
        c = Commitment(
            name="Cycling May",
            cadence="aggregate",
            status="active",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
            targets={"km": 300.0},
            progress={"km": 200.0},
            daily_target=0,
        )
        async_session.add(c)
        await async_session.commit()

        ctx = _ctx(today=today)
        signal = await pace_detector.detect(ctx, session=async_session)
        assert signal is None

    @pytest.mark.asyncio
    async def test_does_not_fire_for_daily_cadence(self, async_session):
        today = date(2026, 5, 21)
        c = Commitment(
            name="Push-ups",
            cadence="daily",
            status="active",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
            targets=None,
            progress=None,
            daily_target=50,
        )
        async_session.add(c)
        await async_session.commit()

        ctx = _ctx(today=today)
        signal = await pace_detector.detect(ctx, session=async_session)
        assert signal is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/shu/projects/open-brain && python -m pytest tests/test_pulse_signals_detectors.py::TestCommitmentPaceDetector -v 2>&1 | tail -10
```

Expected: ImportError.

- [ ] **Step 3: Create the detector**

Create `src/pulse_signals/detectors/commitment_pace.py`:

```python
"""Commitment pace detector — fires when an aggregate commitment is behind or well ahead of pace."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes.commitments import _compute_pace
from src.core.models import Commitment
from src.pulse_signals.context import MorningContext
from src.pulse_signals.ranker import Signal

NAME = "commitment_pace"
_URGENCY = 7.5
_BEHIND_THRESHOLD = 0.85
_AHEAD_THRESHOLD = 1.2


async def detect(ctx: MorningContext, *, session: AsyncSession) -> Signal | None:
    stmt = select(Commitment).where(
        Commitment.cadence == "aggregate",
        Commitment.status == "active",
        Commitment.start_date <= ctx.today,
        Commitment.end_date >= ctx.today,
    )
    rows = (await session.execute(stmt)).scalars().all()

    for c in rows:
        pace = _compute_pace(c.targets, c.progress, c.start_date, c.end_date, ctx.today)
        if pace is None:
            continue
        overall = pace.get("overall", 0.0)
        if overall < _BEHIND_THRESHOLD or overall > _AHEAD_THRESHOLD:
            primary_metric = next(
                (k for k in (c.targets or {}) if k != "overall"), "overall"
            )
            return Signal(
                signal_type=NAME,
                urgency=_URGENCY,
                payload={
                    "name": c.name,
                    "metric": primary_metric,
                    "actual": (c.progress or {}).get(primary_metric, 0.0),
                    "target": (c.targets or {}).get(primary_metric, 0.0),
                    "pace_overall": round(overall, 2),
                    "is_behind": overall < _BEHIND_THRESHOLD,
                },
            )
    return None
```

- [ ] **Step 4: Run tests**

```bash
cd /home/shu/projects/open-brain && python -m pytest tests/test_pulse_signals_detectors.py::TestCommitmentPaceDetector -v 2>&1 | tail -10
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /home/shu/projects/open-brain && git add src/pulse_signals/detectors/commitment_pace.py tests/test_pulse_signals_detectors.py && git commit -m "feat(pulse): add commitment_pace detector — behind/ahead pace signal"
```

---

## Task 4: Rework open detector (template-only)

**Files:**
- Modify: `src/pulse_signals/detectors/open.py`
- Modify: `tests/test_pulse_signals_detectors.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pulse_signals_detectors.py`:

```python
class TestOpenDetectorReworked:
    def test_fires_always_with_todos_and_events(self):
        calendar = CalendarState(
            fetched_at="2026-05-21T04:00:00Z",
            date="2026-05-21",
            events=[_event("Team standup")],
            tomorrow_preview=[],
        )
        ctx = _ctx(
            calendar=calendar,
            open_todos=[{"description": "Write report", "due_date": None, "priority": "normal"}],
        )
        signal = open_detector.detect(ctx)
        assert signal is not None
        assert signal.payload["todo_count"] == 1
        assert signal.payload["event_count"] == 1

    def test_fires_with_no_todos_no_events(self):
        ctx = _ctx()
        signal = open_detector.detect(ctx)
        assert signal is not None
        assert signal.payload["todo_count"] == 0
        assert signal.payload["event_count"] == 0

    def test_payload_has_no_yesterday_question(self):
        ctx = _ctx()
        signal = open_detector.detect(ctx)
        assert signal is not None
        assert "yesterday_question" not in signal.payload
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/shu/projects/open-brain && python -m pytest tests/test_pulse_signals_detectors.py::TestOpenDetectorReworked -v 2>&1 | tail -10
```

Expected: FAILED (old detector returns None when no todos/events, old payload has yesterday_question).

- [ ] **Step 3: Rewrite the detector**

Replace the full content of `src/pulse_signals/detectors/open.py`:

```python
"""Open detector — always-on fallback.

Produces a template bullet summarising open todos and calendar events.
No LLM call. Fires unconditionally so there is always at least one bullet
on a quiet day.
"""

from __future__ import annotations

from src.pulse_signals.context import MorningContext
from src.pulse_signals.ranker import Signal

NAME = "open"
_URGENCY = 5.0


def detect(ctx: MorningContext) -> Signal | None:
    todo_count = len(ctx.open_todos)
    event_count = len(ctx.calendar.events) if ctx.calendar else 0

    return Signal(
        signal_type=NAME,
        urgency=_URGENCY,
        payload={
            "todo_count": todo_count,
            "event_count": event_count,
        },
    )
```

- [ ] **Step 4: Run tests**

```bash
cd /home/shu/projects/open-brain && python -m pytest tests/test_pulse_signals_detectors.py::TestOpenDetectorReworked -v 2>&1 | tail -10
```

Expected: 3 PASSED.

- [ ] **Step 5: Make sure existing open detector tests still pass (or update them)**

```bash
cd /home/shu/projects/open-brain && python -m pytest tests/test_pulse_signals_detectors.py -v 2>&1 | tail -20
```

If old `TestOpenDetector` tests fail (they test the old behaviour where empty → None), update them to match the new always-fires contract.

- [ ] **Step 6: Commit**

```bash
cd /home/shu/projects/open-brain && git add src/pulse_signals/detectors/open.py tests/test_pulse_signals_detectors.py && git commit -m "refactor(pulse): open detector always fires, template-only, no LLM"
```

---

## Task 5: Add `commitment_pace_system_prompt`, remove `open_system_prompt`

**Files:**
- Modify: `src/pulse_signals/prompts.py`
- Modify: `tests/test_pulse_signals_prompts.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pulse_signals_prompts.py`:

```python
from src.pulse_signals.prompts import commitment_pace_system_prompt

def test_commitment_pace_system_prompt_contains_guardrail():
    from datetime import date
    prompt = commitment_pace_system_prompt(date(2026, 5, 21))
    assert "2026-05-21" in prompt
    assert "Wednesday" in prompt
    assert "user_input" in prompt

def test_open_system_prompt_no_longer_exported():
    import src.pulse_signals.prompts as p
    assert not hasattr(p, "open_system_prompt")
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/shu/projects/open-brain && python -m pytest tests/test_pulse_signals_prompts.py -v -k "commitment_pace or open_system" 2>&1 | tail -10
```

Expected: FAILED.

- [ ] **Step 3: Update prompts.py**

In `src/pulse_signals/prompts.py`, delete `_OPEN_BODY` and `open_system_prompt`, and add:

```python
_COMMITMENT_PACE_BODY = (
    "You are writing a single morning nudge about a fitness commitment's progress.\n\n"
    "Rules:\n"
    "- 20 words max, warm but direct.\n"
    "- If behind (is_behind=true): state the gap plainly, no guilt.\n"
    "- If well ahead (is_behind=false): suggest today is a good day to rest.\n"
    "- No questions. No preamble."
)


def commitment_pace_system_prompt(today: date) -> str:
    return _COMMITMENT_PACE_BODY + "\n\n" + _SHARED_GUARDRAIL.format(
        today=today.isoformat(), weekday=today.strftime("%A")
    )
```

Also remove `open_system_prompt` from the file entirely.

- [ ] **Step 4: Run tests**

```bash
cd /home/shu/projects/open-brain && python -m pytest tests/test_pulse_signals_prompts.py -v 2>&1 | tail -10
```

Expected: all PASSED (including the new ones).

- [ ] **Step 5: Commit**

```bash
cd /home/shu/projects/open-brain && git add src/pulse_signals/prompts.py tests/test_pulse_signals_prompts.py && git commit -m "feat(pulse): add commitment_pace prompt, remove open prompt"
```

---

## Task 6: Ranker — `select_signals` (all above threshold)

**Files:**
- Modify: `src/pulse_signals/ranker.py`
- Modify: `tests/test_pulse_signals_ranker.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pulse_signals_ranker.py`:

```python
from src.pulse_signals.ranker import Signal, select_signals

class TestSelectSignals:
    def test_returns_all_above_threshold(self):
        signals = [
            Signal("deadline", 8.0, {}),
            Signal("commitment_pace", 7.5, {}),
            Signal("open", 5.0, {}),
        ]
        result = select_signals(signals, threshold=5.0, order=["deadline", "commitment_pace", "open"])
        assert len(result) == 3

    def test_excludes_below_threshold(self):
        signals = [
            Signal("deadline", 8.0, {}),
            Signal("open", 4.9, {}),
        ]
        result = select_signals(signals, threshold=5.0, order=["deadline", "open"])
        assert len(result) == 1
        assert result[0].signal_type == "deadline"

    def test_returns_empty_when_none_qualify(self):
        signals = [Signal("open", 4.0, {})]
        result = select_signals(signals, threshold=5.0, order=["open"])
        assert result == []

    def test_order_preserved(self):
        signals = [
            Signal("open", 5.0, {}),
            Signal("deadline", 8.0, {}),
        ]
        result = select_signals(signals, threshold=5.0, order=["deadline", "open"])
        assert result[0].signal_type == "deadline"
        assert result[1].signal_type == "open"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/shu/projects/open-brain && python -m pytest tests/test_pulse_signals_ranker.py::TestSelectSignals -v 2>&1 | tail -10
```

Expected: ImportError (`select_signals` not defined yet).

- [ ] **Step 3: Add `select_signals` to ranker.py**

Add to `src/pulse_signals/ranker.py` after the existing `select_signal` function:

```python
def select_signals(
    signals: list[Signal], threshold: float, order: list[str]
) -> list[Signal]:
    """Return all signals at or above `threshold`, sorted by detector order."""
    qualifying = [s for s in signals if s is not None and s.urgency >= threshold]

    def key(s: Signal) -> int:
        try:
            return order.index(s.signal_type)
        except ValueError:
            return len(order)

    qualifying.sort(key=key)
    return qualifying
```

- [ ] **Step 4: Run tests**

```bash
cd /home/shu/projects/open-brain && python -m pytest tests/test_pulse_signals_ranker.py -v 2>&1 | tail -10
```

Expected: all PASSED (new + existing).

- [ ] **Step 5: Commit**

```bash
cd /home/shu/projects/open-brain && git add src/pulse_signals/ranker.py tests/test_pulse_signals_ranker.py && git commit -m "feat(pulse): add select_signals — returns all above-threshold signals"
```

---

## Task 7: Wire new detectors into `run_detectors`

**Files:**
- Modify: `src/pulse_signals/ranker.py`

The new detectors are async (deadline, commitment_pace) so `run_detectors` must become async and accept a session.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pulse_signals_ranker.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

class TestRunDetectorsWithNewDetectors:
    @pytest.mark.asyncio
    async def test_deadline_detector_called_with_session(self):
        from src.pulse_signals import context as ctx_module
        from src.integrations.calendar import CalendarState

        ctx = MorningContext(
            today=date(2026, 5, 21),
            calendar=CalendarState(fetched_at="", date="", events=[], tomorrow_preview=[]),
            weather=None,
            open_todos=[],
            yesterday_pulse=None,
        )
        mock_session = AsyncMock()

        class MockSettings:
            pulse_signal_detectors = "deadline,open"
            pulse_focus_keywords = ""

        signals = await run_detectors(ctx, MockSettings(), session=mock_session)
        # open detector always fires
        assert any(s.signal_type == "open" for s in signals)
```

- [ ] **Step 2: Run test to confirm failure**

```bash
cd /home/shu/projects/open-brain && python -m pytest tests/test_pulse_signals_ranker.py::TestRunDetectorsWithNewDetectors -v 2>&1 | tail -10
```

Expected: FAILED (run_detectors is sync, no session param).

- [ ] **Step 3: Update `run_detectors` in ranker.py**

Replace the existing `run_detectors` function:

```python
async def run_detectors(
    ctx: MorningContext, settings: Any, *, session: Any = None
) -> list[Signal]:
    """Invoke each configured detector; return all non-None Signals in detector order."""
    from src.pulse_signals.detectors import commitment_pace as commitment_pace_detector
    from src.pulse_signals.detectors import deadline as deadline_detector
    from src.pulse_signals.detectors import focus as focus_detector
    from src.pulse_signals.detectors import named_day as named_day_detector
    from src.pulse_signals.detectors import open as open_detector
    from src.pulse_signals.detectors import opportunity as opportunity_detector

    keywords_raw = getattr(settings, "pulse_focus_keywords", "") or ""
    keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]

    order = _parse_order(getattr(settings, "pulse_signal_detectors", ""))
    signals: list[Signal] = []

    for name in order:
        try:
            if name == deadline_detector.NAME:
                if session is None:
                    logger.warning("pulse_deadline_detector_skipped_no_session")
                    continue
                s = await deadline_detector.detect(ctx, session=session)
            elif name == commitment_pace_detector.NAME:
                if session is None:
                    logger.warning("pulse_commitment_pace_detector_skipped_no_session")
                    continue
                s = await commitment_pace_detector.detect(ctx, session=session)
            elif name == named_day_detector.NAME:
                s = named_day_detector.detect(ctx)
            elif name == focus_detector.NAME:
                s = focus_detector.detect(ctx, keywords=keywords)
            elif name == opportunity_detector.NAME:
                s = opportunity_detector.detect(ctx)
            elif name == open_detector.NAME:
                s = open_detector.detect(ctx)
            else:
                logger.warning("unknown_pulse_detector", name=name)
                continue
        except Exception:
            logger.exception("pulse_detector_failed", name=name)
            continue
        if s is not None:
            signals.append(s)

    return signals
```

- [ ] **Step 4: Run all ranker tests**

```bash
cd /home/shu/projects/open-brain && python -m pytest tests/test_pulse_signals_ranker.py -v 2>&1 | tail -15
```

Expected: all PASSED.

- [ ] **Step 5: Commit**

```bash
cd /home/shu/projects/open-brain && git add src/pulse_signals/ranker.py tests/test_pulse_signals_ranker.py && git commit -m "refactor(pulse): run_detectors async, wires deadline/named_day/commitment_pace"
```

---

## Task 8: `build_briefing` — assemble bullet list

**Files:**
- Modify: `src/pulse_signals/render.py`
- Create: `tests/test_pulse_briefing.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pulse_briefing.py`:

```python
"""Tests for build_briefing() bullet assembly."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from src.pulse_signals.ranker import Signal
from src.pulse_signals.render import build_briefing
from datetime import date


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="Cycling behind — 34 km of 50 km target.")
    return llm


TODAY = date(2026, 5, 21)


class TestBuildBriefing:
    @pytest.mark.asyncio
    async def test_deadline_bullet_single(self, mock_llm):
        signals = [Signal("deadline", 8.0, {"titles": ["Call dentist"], "total_count": 1})]
        result = await build_briefing(signals, llm=mock_llm, today=TODAY)
        assert "• 1 task due today: Call dentist" in result

    @pytest.mark.asyncio
    async def test_deadline_bullet_multiple(self, mock_llm):
        signals = [Signal("deadline", 8.0, {"titles": ["Buy milk", "Call dentist", "Submit report"], "total_count": 5})]
        result = await build_briefing(signals, llm=mock_llm, today=TODAY)
        assert "• 5 tasks due today: Buy milk, Call dentist, Submit report…" in result

    @pytest.mark.asyncio
    async def test_named_day_bullet(self, mock_llm):
        signals = [Signal("named_day", 6.5, {"titles": ["Paulius's birthday"]})]
        result = await build_briefing(signals, llm=mock_llm, today=TODAY)
        assert "• Today: Paulius's birthday" in result

    @pytest.mark.asyncio
    async def test_open_bullet_with_todos_and_events(self, mock_llm):
        signals = [Signal("open", 5.0, {"todo_count": 4, "event_count": 2})]
        result = await build_briefing(signals, llm=mock_llm, today=TODAY)
        assert "• 4 open tasks · 2 event(s) today" in result

    @pytest.mark.asyncio
    async def test_open_bullet_todos_only(self, mock_llm):
        signals = [Signal("open", 5.0, {"todo_count": 3, "event_count": 0})]
        result = await build_briefing(signals, llm=mock_llm, today=TODAY)
        assert "• 3 open tasks — nothing else scheduled" in result

    @pytest.mark.asyncio
    async def test_open_bullet_clear(self, mock_llm):
        signals = [Signal("open", 5.0, {"todo_count": 0, "event_count": 0})]
        result = await build_briefing(signals, llm=mock_llm, today=TODAY)
        assert "• Clear schedule — nothing due or scheduled" in result

    @pytest.mark.asyncio
    async def test_commitment_pace_uses_llm(self, mock_llm):
        signals = [Signal("commitment_pace", 7.5, {
            "name": "Cycling May", "metric": "km",
            "actual": 34.0, "target": 50.0, "pace_overall": 0.68, "is_behind": True
        })]
        result = await build_briefing(signals, llm=mock_llm, today=TODAY)
        mock_llm.complete.assert_called_once()
        assert result.startswith("•")

    @pytest.mark.asyncio
    async def test_multiple_bullets_newline_separated(self, mock_llm):
        signals = [
            Signal("named_day", 6.5, {"titles": ["Women's Day"]}),
            Signal("open", 5.0, {"todo_count": 2, "event_count": 0}),
        ]
        result = await build_briefing(signals, llm=mock_llm, today=TODAY)
        lines = result.split("\n")
        assert len(lines) == 2
        assert all(line.startswith("•") for line in lines)

    @pytest.mark.asyncio
    async def test_empty_signals_returns_fallback(self, mock_llm):
        result = await build_briefing([], llm=mock_llm, today=TODAY)
        assert result == "• Clear schedule — nothing due or scheduled"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/shu/projects/open-brain && python -m pytest tests/test_pulse_briefing.py -v 2>&1 | tail -15
```

Expected: ImportError (`build_briefing` not defined).

- [ ] **Step 3: Add `build_briefing` to render.py**

Add to `src/pulse_signals/render.py` (keep existing `render_signal` for now — it's used by the route and will be removed in Task 9):

```python
from src.pulse_signals.prompts import (
    commitment_pace_system_prompt,
    focus_system_prompt,
    opportunity_system_prompt,
)

_BRIEFING_FALLBACK = "• Clear schedule — nothing due or scheduled"


def _deadline_bullet(payload: dict) -> str:
    titles = payload.get("titles", [])
    total = payload.get("total_count", len(titles))
    title_str = ", ".join(titles)
    suffix = "…" if total > len(titles) else ""
    noun = "task" if total == 1 else "tasks"
    return f"• {total} {noun} due today: {title_str}{suffix}"


def _named_day_bullet(payload: dict) -> str:
    titles = payload.get("titles", [])
    return "• Today: " + ", ".join(titles)


def _open_bullet(payload: dict) -> str:
    todo_count = payload.get("todo_count", 0)
    event_count = payload.get("event_count", 0)
    if todo_count > 0 and event_count > 0:
        return f"• {todo_count} open tasks · {event_count} event(s) today"
    if todo_count > 0:
        return f"• {todo_count} open tasks — nothing else scheduled"
    return "• Clear schedule — nothing due or scheduled"


async def _llm_bullet(signal: Signal, *, llm: Any, today: date) -> str:
    prompt_builders = {
        "focus": focus_system_prompt,
        "opportunity": opportunity_system_prompt,
        "commitment_pace": commitment_pace_system_prompt,
    }
    builder = prompt_builders.get(signal.signal_type)
    if builder is None or llm is None:
        return _BRIEFING_FALLBACK

    system_prompt = builder(today)
    safe_payload = json.dumps(signal.payload, default=str, ensure_ascii=False)
    user_content = f"Signal type: {signal.signal_type}\n<user_input>{safe_payload}</user_input>"

    try:
        raw = await llm.complete(
            system_prompt=system_prompt,
            user_content=user_content,
            max_tokens=_MAX_TOKENS,
        )
    except Exception as exc:
        logger.exception("pulse_briefing_llm_failed", signal_type=signal.signal_type, error=str(exc))
        return _BRIEFING_FALLBACK

    cleaned = (raw or "").strip().strip('"').strip("'")
    return f"• {cleaned}" if cleaned else _BRIEFING_FALLBACK


async def build_briefing(
    signals: list[Signal], *, llm: Any | None, today: date
) -> str:
    """Assemble a newline-separated bullet briefing from all passing signals."""
    if not signals:
        return _BRIEFING_FALLBACK

    _TEMPLATE_BUILDERS = {
        "deadline": _deadline_bullet,
        "named_day": _named_day_bullet,
        "open": _open_bullet,
    }
    _LLM_SIGNAL_TYPES = {"focus", "opportunity", "commitment_pace"}

    bullets: list[str] = []
    for signal in signals:
        if signal.signal_type in _TEMPLATE_BUILDERS:
            bullets.append(_TEMPLATE_BUILDERS[signal.signal_type](signal.payload))
        elif signal.signal_type in _LLM_SIGNAL_TYPES:
            bullets.append(await _llm_bullet(signal, llm=llm, today=today))

    return "\n".join(bullets) if bullets else _BRIEFING_FALLBACK
```

- [ ] **Step 4: Run tests**

```bash
cd /home/shu/projects/open-brain && python -m pytest tests/test_pulse_briefing.py -v 2>&1 | tail -15
```

Expected: all PASSED.

- [ ] **Step 5: Commit**

```bash
cd /home/shu/projects/open-brain && git add src/pulse_signals/render.py tests/test_pulse_briefing.py && git commit -m "feat(pulse): add build_briefing — multi-signal bullet assembler"
```

---

## Task 9: Update `__init__.py` exports and route

**Files:**
- Modify: `src/pulse_signals/__init__.py`
- Modify: `src/api/routes/pulse.py`
- Modify: `src/core/config.py`

- [ ] **Step 1: Check current `__init__.py`**

```bash
cat /home/shu/projects/open-brain/src/pulse_signals/__init__.py
```

- [ ] **Step 2: Update exports**

Ensure `src/pulse_signals/__init__.py` exports `build_briefing` and `select_signals`:

```python
from src.pulse_signals.context import MorningContext, build_morning_context
from src.pulse_signals.ranker import Signal, run_detectors, select_signal, select_signals, trace
from src.pulse_signals.render import build_briefing, render_signal

__all__ = [
    "MorningContext",
    "build_morning_context",
    "Signal",
    "run_detectors",
    "select_signal",
    "select_signals",
    "trace",
    "build_briefing",
    "render_signal",
]
```

- [ ] **Step 3: Update the route in `src/api/routes/pulse.py`**

In the `start_pulse` handler (lines ~210–279), replace the signal path. Find this block:

```python
        signals = run_detectors(ctx, settings)
        order = [p.strip() for p in detector_cfg.split(",") if p.strip()]
        threshold = float(getattr(settings, "pulse_silence_threshold", 5.0))
        chosen = select_signal(signals, threshold=threshold, order=order)
        signal_trace = ranker_trace(signals, order)

        if chosen is None:
            ...
            return _pulse_to_response(pulse)

        ai_question = await render_signal(chosen, llm=llm, today=ctx.today)
        pulse = DailyPulse(
            pulse_date=today_start,
            status="sent",
            ai_question=ai_question,
            signal_type=chosen.signal_type,
            parsed_data={"signal_trace": signal_trace},
        )
```

Replace with:

```python
        from src.pulse_signals import build_briefing, select_signals
        from src.pulse_signals.ranker import trace as ranker_trace

        signals = await run_detectors(ctx, settings, session=session)
        order = [p.strip() for p in detector_cfg.split(",") if p.strip()]
        threshold = float(getattr(settings, "pulse_silence_threshold", 5.0))
        active_signals = select_signals(signals, threshold=threshold, order=order)
        signal_trace = ranker_trace(signals, order)

        if not active_signals:
            silent_payload: dict = {"signal_trace": signal_trace}
            if getattr(settings, "pulse_signal_debug_ui", False):
                silent_payload["debug_ui"] = True
            pulse = DailyPulse(
                pulse_date=today_start,
                status="silent",
                ai_question=None,
                signal_type=None,
                parsed_data=silent_payload,
            )
            session.add(pulse)
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                raise HTTPException(
                    status_code=409, detail="A pulse record already exists for today"
                ) from None
            await session.commit()
            await session.refresh(pulse)
            logger.info("start_pulse_silent", pulse_id=str(pulse.id))
            return _pulse_to_response(pulse)

        ai_question = await build_briefing(active_signals, llm=llm, today=ctx.today)
        pulse = DailyPulse(
            pulse_date=today_start,
            status="sent",
            ai_question=ai_question,
            signal_type="briefing",
            parsed_data={"signal_trace": signal_trace},
        )
```

Also update the import line at the top of the `if use_signals:` block — remove `render_signal` and `select_signal`, add `select_signals` and `build_briefing`.

- [ ] **Step 4: Update config default**

In `src/core/config.py`, change:

```python
    pulse_signal_detectors: str = "focus,opportunity,open"
```

to:

```python
    pulse_signal_detectors: str = "deadline,commitment_pace,named_day,focus,opportunity,open"
```

- [ ] **Step 5: Run the full pulse route test suite**

```bash
cd /home/shu/projects/open-brain && python -m pytest tests/ -k "pulse" -v 2>&1 | tail -30
```

Fix any failures before committing.

- [ ] **Step 6: Commit**

```bash
cd /home/shu/projects/open-brain && git add src/pulse_signals/__init__.py src/api/routes/pulse.py src/core/config.py && git commit -m "feat(pulse): wire briefing pipeline into start_pulse route"
```

---

## Task 10: Migration — drop `notes` column

**Files:**
- Create: `alembic/versions/0022_drop_pulse_notes.py`
- Modify: `src/core/models.py`

- [ ] **Step 1: Verify latest revision**

```bash
ls /home/shu/projects/open-brain/alembic/versions/ | grep -v __pycache__ | sort | tail -3
```

Confirm `0021_...` is the latest. If a newer one exists, adjust the revision number accordingly.

- [ ] **Step 2: Create migration**

Create `alembic/versions/0022_drop_pulse_notes.py`:

```python
"""drop notes column from daily_pulse

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("daily_pulse", "notes")


def downgrade() -> None:
    op.add_column(
        "daily_pulse",
        sa.Column("notes", sa.Text(), nullable=True),
    )
```

- [ ] **Step 3: Remove `notes` from the ORM model**

In `src/core/models.py`, remove line:

```python
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Also update the class docstring to remove the notes reference.

- [ ] **Step 4: Run the migration on local SQLite test DB**

```bash
cd /home/shu/projects/open-brain && python -m pytest tests/test_pulse_signal_type_migration.py -v 2>&1 | tail -10
```

Also run a quick Alembic check:

```bash
cd /home/shu/projects/open-brain && python -m alembic upgrade head 2>&1 | tail -10
```

- [ ] **Step 5: Run full test suite**

```bash
cd /home/shu/projects/open-brain && make test 2>&1 | tail -20
```

Fix any failures (some tests may reference `notes` and need updating).

- [ ] **Step 6: Commit**

```bash
cd /home/shu/projects/open-brain && git add alembic/versions/0022_drop_pulse_notes.py src/core/models.py && git commit -m "feat(pulse): drop notes column from daily_pulse (migration 0022)"
```

---

## Task 11: Frontend — render bullets, remove notes

**Files:**
- Modify: `web/components/dashboard/morning-pulse.tsx`
- Modify: `web/hooks/use-pulse.ts`
- Modify: `web/lib/types.ts`

- [ ] **Step 1: Write the failing frontend test**

Check existing frontend tests:

```bash
ls /home/shu/projects/open-brain/web/__tests__/components/ | grep pulse
```

Add to the relevant test file (or create `web/__tests__/components/morning-pulse-briefing.test.tsx`):

```tsx
import { render, screen } from "@testing-library/react";
import { MorningPulse } from "@/components/dashboard/morning-pulse";

// Mock usePulse to return a sent pulse with bullet briefing
jest.mock("@/hooks/use-pulse", () => ({
  usePulse: () => ({
    pulse: {
      id: "1",
      pulse_date: "2026-05-21T00:00:00Z",
      status: "sent",
      ai_question: "• Today: Paulius's birthday\n• 3 open tasks — nothing else scheduled",
      ai_question_response: null,
      wake_time: null,
      sleep_quality: null,
      energy_level: null,
      clean_meal: null,
      alcohol: null,
      signal_type: "briefing",
      parsed_data: null,
      created_at: "2026-05-21T04:00:00Z",
      updated_at: "2026-05-21T04:00:00Z",
    },
    loading: false,
    error: null,
    createPulse: jest.fn(),
    submitPulse: jest.fn(),
  }),
}));

describe("MorningPulse briefing rendering", () => {
  it("renders each bullet as a list item", () => {
    render(<MorningPulse />);
    expect(screen.getByText("Today: Paulius's birthday")).toBeInTheDocument();
    expect(screen.getByText("3 open tasks — nothing else scheduled")).toBeInTheDocument();
  });

  it("does not render a notes textarea", () => {
    render(<MorningPulse />);
    expect(screen.queryByPlaceholderText("Anything else on your mind?")).toBeNull();
  });
});
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
cd /home/shu/projects/open-brain/web && npx vitest run __tests__/components/morning-pulse-briefing.test.tsx 2>&1 | tail -15
```

Expected: FAILED (bullets render in a blockquote, not as list items; notes textarea present).

- [ ] **Step 3: Update `web/lib/types.ts`**

Remove `notes: string | null;` from `PulseResponse`.

- [ ] **Step 4: Update `web/hooks/use-pulse.ts`**

In the `PulseForm` `onSubmit` type, remove `notes?: string;`. The `submitPulse` signature stays the same — just remove `notes` from the shape passed in `handleSubmit`.

- [ ] **Step 5: Update `morning-pulse.tsx` — form**

In `PulseForm`:
1. Remove `const [notes, setNotes] = useState("");`
2. Remove `notes: notes || undefined,` from `handleSubmit`
3. Remove the notes `<div>` block (label + Textarea for notes)
4. Replace the `{aiQuestion && <blockquote>...</blockquote>}` section with a bullet list:

```tsx
{aiQuestion && (
  <ul className="space-y-1 mb-2">
    {aiQuestion.split("\n").map((line, i) => (
      <li key={i} className="text-sm text-on-surface-variant">
        {line.startsWith("• ") ? line.slice(2) : line}
      </li>
    ))}
  </ul>
)}
```

5. Remove the answer textarea entirely (the briefing doesn't ask a question to respond to) — keep `ai_question_response` field in the type but remove the UI input.

- [ ] **Step 6: Update `morning-pulse.tsx` — summary**

In `PulseSummary`:
1. Remove the `{pulse.notes && ...}` block
2. Update the Q&A block to render bullets instead of `Q: ... A: ...`:

```tsx
{pulse.ai_question && (
  <ul className="mt-3 space-y-0.5">
    {pulse.ai_question.split("\n").map((line, i) => (
      <li key={i} className="text-xs text-on-surface-variant">
        {line.startsWith("• ") ? line.slice(2) : line}
      </li>
    ))}
  </ul>
)}
```

- [ ] **Step 7: Run frontend tests**

```bash
cd /home/shu/projects/open-brain/web && npx vitest run 2>&1 | tail -20
```

Fix any failures before committing.

- [ ] **Step 8: Commit**

```bash
cd /home/shu/projects/open-brain && git add web/components/dashboard/morning-pulse.tsx web/hooks/use-pulse.ts web/lib/types.ts && git commit -m "feat(web): render pulse as bullet briefing, remove notes field"
```

---

## Task 12: Shift cron -1h

**Files:**
- Modify: `crontab`

- [ ] **Step 1: Update crontab**

In `crontab`, change:

```
# Morning pulse - 05:00 UTC (08:00 Europe/Vilnius summer)
0 5 * * * python -m src.jobs.pulse
```

to:

```
# Morning pulse - 04:00 UTC (07:00 Europe/Vilnius summer)
0 4 * * * python -m src.jobs.pulse
```

- [ ] **Step 2: Verify supercronic accepts it**

```bash
cd /home/shu/projects/open-brain && docker run --rm -v $(pwd)/crontab:/crontab:ro aptible/supercronic -test /crontab 2>&1 | tail -5
```

If Docker isn't available locally, skip and note it for deploy verification.

- [ ] **Step 3: Commit**

```bash
cd /home/shu/projects/open-brain && git add crontab && git commit -m "chore(pulse): shift morning pulse cron to 04:00 UTC (07:00 Vilnius)"
```

---

## Task 13: Final test sweep & cleanup

- [ ] **Step 1: Run full backend test suite**

```bash
cd /home/shu/projects/open-brain && make test 2>&1 | tail -30
```

Fix any remaining failures.

- [ ] **Step 2: Run full frontend test suite**

```bash
cd /home/shu/projects/open-brain/web && npx vitest run 2>&1 | tail -20
```

- [ ] **Step 3: Run lint**

```bash
cd /home/shu/projects/open-brain && make lint 2>&1 | tail -20
```

Fix any lint issues.

- [ ] **Step 4: Verify `render_signal` usage**

Check that `render_signal` is no longer called anywhere in the active code path (it can stay in `render.py` for the legacy fallback, but should not be in the `start_pulse` route):

```bash
grep -rn "render_signal" /home/shu/projects/open-brain/src/ 2>&1
```

- [ ] **Step 5: Final commit if any cleanup was needed**

```bash
cd /home/shu/projects/open-brain && git add -p && git commit -m "chore(pulse): final cleanup after briefing migration"
```

---

## Verification Checklist

- [ ] `POST /v1/pulse/start` returns `ai_question` with `•`-prefixed bullets, `signal_type="briefing"`
- [ ] Deadline detector fires for todos with `due_date == today`, not for future dates
- [ ] Named-day detector fires only on `all_day=True` calendar events
- [ ] Commitment pace detector fires for `pace.overall < 0.85` or `> 1.2`, not for daily cadence
- [ ] Open detector always fires and produces correct template bullet
- [ ] All bullets from above-threshold signals appear in the briefing
- [ ] Frontend renders bullets as `<li>` items, not a blockquote
- [ ] Notes textarea absent from form; notes icon absent from summary
- [ ] `make test` passes
- [ ] `npx vitest run` passes
- [ ] `make lint` passes
- [ ] Crontab updated: `0 4 * * *`
- [ ] Migration 0022 runs cleanly: `notes` column dropped
