"""Tests for build_morning_context."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.core.models import DailyPulse, MemoryItem, RawMemory, TodoItem
from src.pulse_signals.context import MorningContext, build_morning_context


def _settings() -> MagicMock:
    s = MagicMock()
    s.pulse_timezone = "UTC"
    s.pulse_weather_enabled = True
    s.pulse_weather_latitude = 54.8985
    s.pulse_weather_longitude = 23.9036
    return s


@pytest.mark.asyncio
async def test_build_morning_context_happy_path(async_session):
    # Open todo
    todo = TodoItem(description="Ship API", priority="high", status="open")
    async_session.add(todo)

    # Yesterday's pulse
    yesterday = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    yp = DailyPulse(pulse_date=yesterday, status="completed", ai_question="Q?")
    async_session.add(yp)

    # Recent memory
    raw = RawMemory(source="test", raw_text="hello")
    async_session.add(raw)
    await async_session.flush()
    mi = MemoryItem(raw_id=raw.id, type="daily_pulse", content="recent pulse content")
    async_session.add(mi)
    await async_session.commit()

    async def fake_weather(settings, http):
        from src.integrations.weather import WeatherSnapshot

        return WeatherSnapshot(
            today_min_temp=10.0,
            today_max_temp=18.0,
            today_precip_mm=0.0,
            today_wind_kmh=10.0,
            next_7_days=[],
        )

    async def fake_cal(settings):
        from src.integrations.calendar import CalendarState

        return CalendarState(
            fetched_at="2026-04-23T05:00:00Z",
            date="2026-04-23",
            events=[],
            tomorrow_preview=[],
        )

    with patch("src.pulse_signals.context.fetch_weather_snapshot", new=fake_weather), patch(
        "src.pulse_signals.context.fetch_today_events", new=fake_cal
    ):
        async with httpx.AsyncClient() as http:
            ctx = await build_morning_context(async_session, _settings(), http)

    assert isinstance(ctx, MorningContext)
    assert ctx.today is not None
    assert len(ctx.open_todos) == 1
    assert ctx.open_todos[0]["description"] == "Ship API"
    assert ctx.yesterday_pulse is not None
    assert ctx.yesterday_pulse.ai_question == "Q?"
    assert ctx.weather is not None
    assert len(ctx.recent_memories) >= 1


@pytest.mark.asyncio
async def test_build_morning_context_weather_fail(async_session):
    async def fake_weather(settings, http):
        return None

    async def fake_cal(settings):
        from src.integrations.calendar import CalendarState

        return CalendarState(
            fetched_at="2026-04-23T05:00:00Z",
            date="2026-04-23",
            events=[],
            tomorrow_preview=[],
        )

    with patch("src.pulse_signals.context.fetch_weather_snapshot", new=fake_weather), patch(
        "src.pulse_signals.context.fetch_today_events", new=fake_cal
    ):
        async with httpx.AsyncClient() as http:
            ctx = await build_morning_context(async_session, _settings(), http)

    assert ctx.weather is None
    assert ctx.open_todos == []
    assert ctx.yesterday_pulse is None


@pytest.mark.asyncio
async def test_build_morning_context_recent_memories_filters_type_and_date(async_session):
    # Add an old memory (should be excluded) and a non-matching-type memory
    raw = RawMemory(source="test", raw_text="hi")
    async_session.add(raw)
    await async_session.flush()

    # matching
    async_session.add(MemoryItem(raw_id=raw.id, type="daily_pulse", content="kept"))
    async_session.add(MemoryItem(raw_id=raw.id, type="todo", content="kept too"))
    # excluded by type
    async_session.add(MemoryItem(raw_id=raw.id, type="memory", content="excluded"))
    await async_session.commit()

    async def fake_weather(settings, http):
        return None

    async def fake_cal(settings):
        from src.integrations.calendar import CalendarState

        return CalendarState(fetched_at="x", date="2026-04-23", events=[], tomorrow_preview=[])

    with patch("src.pulse_signals.context.fetch_weather_snapshot", new=fake_weather), patch(
        "src.pulse_signals.context.fetch_today_events", new=fake_cal
    ):
        async with httpx.AsyncClient() as http:
            ctx = await build_morning_context(async_session, _settings(), http)

    types = {m.type for m in ctx.recent_memories}
    assert "memory" not in types
    assert {"daily_pulse", "todo"} & types
