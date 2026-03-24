"""Tests for src/integrations/calendar.py.

All tests run on SQLite (no Google libs required for most paths).
Google API calls are always mocked.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_settings(credentials_path: str = "/fake/credentials.json", token_path: str = "/fake/token.json"):
    s = MagicMock()
    s.google_calendar_credentials_path = credentials_path
    s.google_calendar_token_path = token_path
    return s


# ── _is_within_reply_window (pure function from pulse_cog, tested here) ────────


def test_is_within_reply_window_true():
    """Message within window returns True."""
    from src.integrations.modules.pulse_cog import _is_within_reply_window

    created_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    assert _is_within_reply_window(created_at, window_minutes=120) is True


def test_is_within_reply_window_false_expired():
    """Message outside window returns False."""
    from src.integrations.modules.pulse_cog import _is_within_reply_window

    created_at = datetime.now(timezone.utc) - timedelta(minutes=180)
    assert _is_within_reply_window(created_at, window_minutes=120) is False


def test_is_within_reply_window_boundary():
    """Message at exact boundary (window_minutes ago) is outside window."""
    from src.integrations.modules.pulse_cog import _is_within_reply_window

    created_at = datetime.now(timezone.utc) - timedelta(minutes=120, seconds=1)
    assert _is_within_reply_window(created_at, window_minutes=120) is False


def test_is_within_reply_window_just_inside():
    """Message 1 second before the boundary is inside window."""
    from src.integrations.modules.pulse_cog import _is_within_reply_window

    created_at = datetime.now(timezone.utc) - timedelta(minutes=119, seconds=59)
    assert _is_within_reply_window(created_at, window_minutes=120) is True


# ── fetch_today_events — fallback paths ────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_google_not_available():
    """Returns empty CalendarState when google libs are not installed."""
    from src.integrations import calendar as cal_module

    with patch.object(cal_module, "_GOOGLE_AVAILABLE", False):
        settings = _make_settings()
        state = await cal_module.fetch_today_events(settings)

    assert state.events == []
    assert state.tomorrow_preview == []


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_credentials_not_configured():
    """Returns empty CalendarState when credential paths are empty strings."""
    from src.integrations.calendar import fetch_today_events

    settings = _make_settings(credentials_path="", token_path="")
    state = await fetch_today_events(settings)

    assert state.events == []
    assert state.tomorrow_preview == []


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_token_missing(tmp_path):
    """Returns empty CalendarState when token file does not exist."""
    from src.integrations import calendar as cal_module

    missing_token = str(tmp_path / "nonexistent_token.json")
    settings = _make_settings(token_path=missing_token)

    # Credentials path can be anything — _load_credentials exits early on missing token
    with patch.object(cal_module, "_GOOGLE_AVAILABLE", True):
        state = await cal_module.fetch_today_events(settings)

    assert state.events == []
    assert state.tomorrow_preview == []


@pytest.mark.asyncio
async def test_fetch_returns_empty_on_api_error():
    """Returns empty CalendarState when _CalendarClient.fetch_today raises."""
    from src.integrations import calendar as cal_module

    mock_client = MagicMock()
    mock_client.fetch_today.side_effect = RuntimeError("API exploded")

    with patch.object(cal_module, "_GOOGLE_AVAILABLE", True), patch.object(
        cal_module, "_CalendarClient", return_value=mock_client
    ):
        settings = _make_settings()
        state = await cal_module.fetch_today_events(settings)

    assert state.events == []
    assert state.tomorrow_preview == []


@pytest.mark.asyncio
async def test_fetch_returns_events_on_success():
    """Returns populated CalendarState when client returns events."""
    from src.integrations import calendar as cal_module
    from src.integrations.calendar import CalendarEvent, CalendarState, CalendarTomorrowEvent

    today_str = datetime.now().date().isoformat()
    mock_state = CalendarState(
        fetched_at=datetime.now(timezone.utc).isoformat(),
        date=today_str,
        events=[
            CalendarEvent(title="Standup", start="09:00", end="09:30", all_day=False),
            CalendarEvent(title="Lunch", start="12:00", end="13:00", all_day=False),
        ],
        tomorrow_preview=[
            CalendarTomorrowEvent(title="Team sync", start="10:00", all_day=False),
        ],
    )

    mock_client = MagicMock()
    mock_client.fetch_today.return_value = mock_state

    with patch.object(cal_module, "_GOOGLE_AVAILABLE", True), patch.object(
        cal_module, "_CalendarClient", return_value=mock_client
    ):
        settings = _make_settings()
        state = await cal_module.fetch_today_events(settings)

    assert len(state.events) == 2
    assert state.events[0].title == "Standup"
    assert len(state.tomorrow_preview) == 1
    assert state.tomorrow_preview[0].title == "Team sync"


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_only_credentials_path_set():
    """Missing token_path alone triggers early return."""
    from src.integrations.calendar import fetch_today_events

    settings = _make_settings(credentials_path="/real/creds.json", token_path="")
    state = await fetch_today_events(settings)

    assert state.events == []


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_only_token_path_set():
    """Missing credentials_path alone triggers early return."""
    from src.integrations.calendar import fetch_today_events

    settings = _make_settings(credentials_path="", token_path="/real/token.json")
    state = await fetch_today_events(settings)

    assert state.events == []
