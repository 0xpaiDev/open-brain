"""Unit tests for Phase 1 pulse signal detectors.

Each detector is a pure function over a MorningContext fixture.
No DB, no network.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.integrations.calendar import CalendarEvent, CalendarState
from src.integrations.weather import DayForecast, WeatherSnapshot
from src.pulse_signals.context import MorningContext
from src.pulse_signals.detectors import focus as focus_detector
from src.pulse_signals.detectors import open as open_detector
from src.pulse_signals.detectors import opportunity as opportunity_detector

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _empty_calendar_state() -> CalendarState:
    return CalendarState(
        fetched_at="2026-04-23T05:00:00Z",
        date="2026-04-23",
        events=[],
        tomorrow_preview=[],
    )


def _event(title: str, start: str = "2026-04-23T14:00:00+00:00") -> CalendarEvent:
    return CalendarEvent(
        title=title,
        start=start,
        end="2026-04-23T15:00:00+00:00",
        location=None,
        calendar="primary",
        all_day=False,
    )


def _ctx(
    *,
    calendar: CalendarState | None = None,
    weather: WeatherSnapshot | None = None,
    open_todos: list | None = None,
    yesterday_pulse=None,
    recent_memories: list | None = None,
    today: date | None = None,
) -> MorningContext:
    return MorningContext(
        today=today or date(2026, 4, 23),
        calendar=calendar or _empty_calendar_state(),
        weather=weather,
        open_todos=open_todos or [],
        yesterday_pulse=yesterday_pulse,
        recent_memories=recent_memories or [],
    )


# ── focus detector ────────────────────────────────────────────────────────────


class TestFocusDetector:
    def test_fires_on_keyword_match(self):
        ctx = _ctx(
            calendar=CalendarState(
                fetched_at="2026-04-23T05:00:00Z",
                date="2026-04-23",
                events=[_event("1:1 with Tom")],
                tomorrow_preview=[],
            ),
        )
        signal = focus_detector.detect(ctx, keywords=["1:1", "demo", "review"])
        assert signal is not None
        assert signal.signal_type == "focus"
        assert signal.urgency >= 7.0
        assert signal.payload["event_title"] == "1:1 with Tom"
        assert signal.payload["reason"].startswith("keyword:")

    def test_no_fire_on_empty_calendar(self):
        signal = focus_detector.detect(_ctx(), keywords=["1:1"])
        assert signal is None

    def test_no_fire_on_non_matching_title(self):
        ctx = _ctx(
            calendar=CalendarState(
                fetched_at="2026-04-23T05:00:00Z",
                date="2026-04-23",
                events=[_event("Routine standup")],
                tomorrow_preview=[],
            ),
        )
        signal = focus_detector.detect(ctx, keywords=["1:1", "demo"])
        assert signal is None

    def test_case_insensitive_match(self):
        ctx = _ctx(
            calendar=CalendarState(
                fetched_at="2026-04-23T05:00:00Z",
                date="2026-04-23",
                events=[_event("Launch review @ HQ")],
                tomorrow_preview=[],
            ),
        )
        signal = focus_detector.detect(ctx, keywords=["LAUNCH"])
        assert signal is not None
        assert signal.payload["event_title"] == "Launch review @ HQ"

    def test_multiple_matches_urgency_boost(self):
        ctx_single = _ctx(
            calendar=CalendarState(
                fetched_at="2026-04-23T05:00:00Z",
                date="2026-04-23",
                events=[_event("1:1 with Tom")],
                tomorrow_preview=[],
            ),
        )
        ctx_multi = _ctx(
            calendar=CalendarState(
                fetched_at="2026-04-23T05:00:00Z",
                date="2026-04-23",
                events=[_event("1:1 with Tom"), _event("Demo to customer", "2026-04-23T16:00:00+00:00")],
                tomorrow_preview=[],
            ),
        )
        s1 = focus_detector.detect(ctx_single, keywords=["1:1", "demo"])
        s2 = focus_detector.detect(ctx_multi, keywords=["1:1", "demo"])
        assert s1 is not None and s2 is not None
        assert s2.urgency > s1.urgency
        assert s2.urgency <= 9.0

    def test_empty_keywords_never_fires(self):
        ctx = _ctx(
            calendar=CalendarState(
                fetched_at="2026-04-23T05:00:00Z",
                date="2026-04-23",
                events=[_event("1:1 with Tom")],
                tomorrow_preview=[],
            ),
        )
        assert focus_detector.detect(ctx, keywords=[]) is None


# ── opportunity detector ──────────────────────────────────────────────────────


def _snapshot(today_precip: float, next_days_precip: list[float]) -> WeatherSnapshot:
    return WeatherSnapshot(
        today_min_temp=10.0,
        today_max_temp=18.0,
        today_precip_mm=today_precip,
        today_wind_kmh=12.0,
        next_7_days=[
            DayForecast(
                forecast_date=date(2026, 4, 24 + i),
                min_temp=9.0,
                max_temp=16.0,
                precip_mm=p,
                wind_kmh=10.0,
            )
            for i, p in enumerate(next_days_precip)
        ],
    )


class TestOpportunityDetector:
    def test_fires_on_dry_today_wet_next_days(self):
        ctx = _ctx(weather=_snapshot(today_precip=0.1, next_days_precip=[3.0, 2.5, 4.0, 0.0, 0.0, 0.0, 0.0]))
        signal = opportunity_detector.detect(ctx)
        assert signal is not None
        assert signal.signal_type == "opportunity"
        assert signal.urgency >= 5.0
        assert signal.payload["today_precip_mm"] == pytest.approx(0.1)
        assert signal.payload["worst_next_3_precip_mm"] == pytest.approx(4.0)

    def test_no_fire_when_weather_none(self):
        assert opportunity_detector.detect(_ctx(weather=None)) is None

    def test_no_fire_when_today_wet(self):
        ctx = _ctx(weather=_snapshot(today_precip=5.0, next_days_precip=[3.0, 3.0, 3.0]))
        assert opportunity_detector.detect(ctx) is None

    def test_no_fire_when_next_days_also_dry(self):
        ctx = _ctx(weather=_snapshot(today_precip=0.0, next_days_precip=[0.1, 0.2, 0.0]))
        assert opportunity_detector.detect(ctx) is None

    def test_no_fire_when_next_days_empty(self):
        ctx = _ctx(weather=_snapshot(today_precip=0.0, next_days_precip=[]))
        assert opportunity_detector.detect(ctx) is None


# ── open detector ─────────────────────────────────────────────────────────────


class TestOpenDetector:
    def test_fires_when_todos_present(self):
        ctx = _ctx(
            open_todos=[
                {"description": "Ship feature X", "due_date": None},
                {"description": "Email client", "due_date": None},
            ],
        )
        signal = open_detector.detect(ctx)
        assert signal is not None
        assert signal.signal_type == "open"
        assert signal.urgency == pytest.approx(5.0)
        assert len(signal.payload["top_todos"]) == 2

    def test_fires_when_calendar_has_event_even_without_todos(self):
        ctx = _ctx(
            calendar=CalendarState(
                fetched_at="2026-04-23T05:00:00Z",
                date="2026-04-23",
                events=[_event("random meeting")],
                tomorrow_preview=[],
            ),
        )
        signal = open_detector.detect(ctx)
        assert signal is not None
        assert signal.payload["event_count"] == 1

    def test_no_fire_on_empty_context(self):
        assert open_detector.detect(_ctx()) is None

    def test_payload_caps_top_todos_at_three(self):
        todos = [{"description": f"todo {i}", "due_date": None} for i in range(10)]
        ctx = _ctx(open_todos=todos)
        signal = open_detector.detect(ctx)
        assert signal is not None
        assert len(signal.payload["top_todos"]) == 3

    def test_passes_yesterday_question(self):
        from src.core.models import DailyPulse

        yesterday = DailyPulse(
            pulse_date=datetime(2026, 4, 22, tzinfo=UTC),
            status="completed",
            ai_question="What drained you yesterday?",
        )
        ctx = _ctx(
            open_todos=[{"description": "X", "due_date": None}],
            yesterday_pulse=yesterday,
        )
        signal = open_detector.detect(ctx)
        assert signal is not None
        assert signal.payload["yesterday_question"] == "What drained you yesterday?"
