"""MorningContext builder.

Gathers all data a Phase 1 detector can inspect:
  - local-date, calendar, weather, open todos, yesterday's pulse, recent memories.

Uses direct DB queries (not the API) because the cron and route both live
inside the process. `_get_settings()` is avoided here: `settings` is passed in
explicitly so callers can swap it for tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import DailyPulse, MemoryItem, TodoItem
from src.integrations.calendar import CalendarState, fetch_today_events
from src.integrations.weather import WeatherSnapshot, fetch_weather_snapshot

logger = structlog.get_logger(__name__)

_RECENT_MEMORY_DAYS = 7
_RECENT_MEMORY_LIMIT = 20
_RECENT_MEMORY_TYPES = ("daily_pulse", "todo", "todo_completion")


@dataclass(frozen=True)
class MorningContext:
    today: date
    calendar: CalendarState
    weather: WeatherSnapshot | None
    open_todos: list[dict[str, Any]]
    yesterday_pulse: DailyPulse | None
    recent_memories: list[MemoryItem] = field(default_factory=list)


def _local_today(settings: Any) -> date:
    tz_name = getattr(settings, "pulse_timezone", "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, AttributeError):
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


async def _fetch_open_todos(session: AsyncSession) -> list[dict[str, Any]]:
    stmt = select(TodoItem).where(TodoItem.status == "open").limit(25)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "description": t.description,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "priority": t.priority,
        }
        for t in rows
    ]


async def _fetch_yesterday_pulse(session: AsyncSession, today: date) -> DailyPulse | None:
    yday = today - timedelta(days=1)
    day_start = datetime(yday.year, yday.month, yday.day, tzinfo=UTC)
    day_end = day_start + timedelta(days=1)
    stmt = (
        select(DailyPulse)
        .where(DailyPulse.pulse_date >= day_start, DailyPulse.pulse_date < day_end)
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _fetch_recent_memories(session: AsyncSession) -> list[MemoryItem]:
    cutoff = datetime.now(UTC) - timedelta(days=_RECENT_MEMORY_DAYS)
    stmt = (
        select(MemoryItem)
        .where(
            MemoryItem.type.in_(_RECENT_MEMORY_TYPES),
            MemoryItem.is_superseded.is_(False),
            MemoryItem.created_at >= cutoff,
        )
        .order_by(desc(MemoryItem.created_at))
        .limit(_RECENT_MEMORY_LIMIT)
    )
    return list((await session.execute(stmt)).scalars().all())


async def build_morning_context(
    session: AsyncSession, settings: Any, http: httpx.AsyncClient
) -> MorningContext:
    today = _local_today(settings)

    try:
        calendar = await fetch_today_events(settings)
    except Exception:
        from src.integrations.calendar import _empty_calendar_state

        logger.warning("morning_context_calendar_failed")
        calendar = _empty_calendar_state()

    try:
        weather = await fetch_weather_snapshot(settings, http)
    except Exception:
        logger.warning("morning_context_weather_failed")
        weather = None

    open_todos = await _fetch_open_todos(session)
    yesterday_pulse = await _fetch_yesterday_pulse(session, today)
    recent_memories = await _fetch_recent_memories(session)

    return MorningContext(
        today=today,
        calendar=calendar,
        weather=weather,
        open_todos=open_todos,
        yesterday_pulse=yesterday_pulse,
        recent_memories=recent_memories,
    )
