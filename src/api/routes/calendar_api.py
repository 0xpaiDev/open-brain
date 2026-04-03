"""Calendar API endpoint.

GET /v1/calendar/today — fetch today's Google Calendar events with a 5-minute
in-memory TTL cache.  Returns a ``status`` field so the frontend can distinguish
"no events today" from "calendar not connected".
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel

from src.api.middleware.rate_limit import calendar_limit, limiter
from src.core.config import get_settings
from src.integrations.calendar import (
    CalendarEvent,
    CalendarTomorrowEvent,
    fetch_today_events,
    is_calendar_available,
)

logger = structlog.get_logger(__name__)

router = APIRouter()

# ── 5-minute TTL cache ────────────────────────────────────────────────────────

_CACHE_TTL = timedelta(minutes=5)
_cache: dict[str, Any] = {}  # keys: "data" (response dict), "fetched_at" (datetime)


def _invalidate_cache() -> None:
    """Clear the calendar cache (useful for testing)."""
    _cache.clear()


# ── Response model ────────────────────────────────────────────────────────────


class CalendarTodayResponse(BaseModel):
    """Response for GET /v1/calendar/today."""

    status: str  # "ok" | "unavailable"
    date: str
    fetched_at: str
    events: list[CalendarEvent]
    tomorrow_preview: list[CalendarTomorrowEvent]


# ── Route ─────────────────────────────────────────────────────────────────────


@router.get("/v1/calendar/today", response_model=CalendarTodayResponse)
@limiter.limit(calendar_limit)
async def get_calendar_today(request: Request) -> CalendarTodayResponse:
    """Fetch today's calendar events.

    Returns status="ok" when Google Calendar credentials are configured and
    events were fetched (even if the list is empty).  Returns
    status="unavailable" when credentials are missing or Google libs are not
    installed.

    Responses are cached in-memory for 5 minutes to avoid hammering the
    Google Calendar API on every page load.

    Raises:
        401: Missing or invalid X-API-Key (handled by middleware).
    """
    settings = get_settings()

    if not is_calendar_available(settings):
        logger.info("calendar_today_unavailable")
        now = datetime.now(UTC)
        return CalendarTodayResponse(
            status="unavailable",
            date=now.date().isoformat(),
            fetched_at=now.isoformat().replace("+00:00", "Z"),
            events=[],
            tomorrow_preview=[],
        )

    # Check cache
    cached_at = _cache.get("fetched_at")
    if cached_at is not None and datetime.now(UTC) - cached_at < _CACHE_TTL:
        logger.debug("calendar_today_cache_hit")
        return _cache["data"]

    # Fetch fresh data
    try:
        state = await fetch_today_events(settings)
    except Exception:
        logger.exception("calendar_fetch_error")
        now = datetime.now(UTC)
        return CalendarTodayResponse(
            status="unavailable",
            date=now.date().isoformat(),
            fetched_at=now.isoformat().replace("+00:00", "Z"),
            events=[],
            tomorrow_preview=[],
        )

    response = CalendarTodayResponse(
        status="ok",
        date=state.date,
        fetched_at=state.fetched_at,
        events=state.events,
        tomorrow_preview=state.tomorrow_preview,
    )

    _cache["data"] = response
    _cache["fetched_at"] = datetime.now(UTC)
    logger.info("calendar_today_fetched", event_count=len(state.events))

    return response
