"""Tests for GET /v1/calendar/today endpoint."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from src.integrations.calendar import CalendarEvent, CalendarState, CalendarTomorrowEvent


@pytest.fixture(autouse=True)
def _clear_calendar_cache():
    """Reset the calendar TTL cache between tests."""
    from src.api.routes.calendar_api import _invalidate_cache

    _invalidate_cache()
    yield
    _invalidate_cache()


def _make_calendar_state(events: int = 1, tomorrow: int = 0) -> CalendarState:
    """Build a CalendarState with N dummy events."""
    return CalendarState(
        fetched_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        date=datetime.now(UTC).date().isoformat(),
        events=[
            CalendarEvent(
                title=f"Event {i}",
                start=f"2026-04-02T{9 + i:02d}:00:00+03:00",
                end=f"2026-04-02T{10 + i:02d}:00:00+03:00",
            )
            for i in range(events)
        ],
        tomorrow_preview=[
            CalendarTomorrowEvent(title=f"Tomorrow {i}", start="2026-04-03T10:00:00+03:00")
            for i in range(tomorrow)
        ],
    )


# ── Status: unavailable ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calendar_today_unavailable(test_client, api_key_headers) -> None:
    """When calendar is not available, returns status=unavailable with empty events."""
    with patch("src.api.routes.calendar_api.is_calendar_available", return_value=False):
        resp = await test_client.get("/v1/calendar/today", headers=api_key_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unavailable"
    assert body["events"] == []
    assert body["tomorrow_preview"] == []
    assert "date" in body
    assert "fetched_at" in body


# ── Status: ok ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calendar_today_ok_with_events(test_client, api_key_headers) -> None:
    """When calendar is available, returns status=ok with events."""
    state = _make_calendar_state(events=2, tomorrow=1)
    with (
        patch("src.api.routes.calendar_api.is_calendar_available", return_value=True),
        patch("src.api.routes.calendar_api.fetch_today_events", return_value=state),
    ):
        resp = await test_client.get("/v1/calendar/today", headers=api_key_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert len(body["events"]) == 2
    assert len(body["tomorrow_preview"]) == 1
    assert body["events"][0]["title"] == "Event 0"


@pytest.mark.asyncio
async def test_calendar_today_ok_empty(test_client, api_key_headers) -> None:
    """When calendar is available but no events, returns status=ok with empty list."""
    state = _make_calendar_state(events=0)
    with (
        patch("src.api.routes.calendar_api.is_calendar_available", return_value=True),
        patch("src.api.routes.calendar_api.fetch_today_events", return_value=state),
    ):
        resp = await test_client.get("/v1/calendar/today", headers=api_key_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["events"] == []


# ── TTL cache ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calendar_today_cache_hit(test_client, api_key_headers) -> None:
    """Second request within TTL returns cached data without calling fetch again."""
    state = _make_calendar_state(events=1)
    with (
        patch("src.api.routes.calendar_api.is_calendar_available", return_value=True),
        patch("src.api.routes.calendar_api.fetch_today_events", return_value=state) as mock_fetch,
    ):
        resp1 = await test_client.get("/v1/calendar/today", headers=api_key_headers)
        resp2 = await test_client.get("/v1/calendar/today", headers=api_key_headers)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    # fetch_today_events should only be called once (second request uses cache)
    assert mock_fetch.call_count == 1


# ── Auth ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calendar_today_cache_expired_triggers_refetch(
    test_client, api_key_headers
) -> None:
    """After TTL expires, endpoint re-fetches instead of returning stale data."""
    state1 = _make_calendar_state(events=1)
    state2 = _make_calendar_state(events=3)

    with (
        patch("src.api.routes.calendar_api.is_calendar_available", return_value=True),
        patch("src.api.routes.calendar_api.fetch_today_events", side_effect=[state1, state2]) as mock_fetch,
    ):
        # First call populates cache
        resp1 = await test_client.get("/v1/calendar/today", headers=api_key_headers)
        assert resp1.status_code == 200
        assert len(resp1.json()["events"]) == 1
        assert mock_fetch.call_count == 1

        # Expire the cache by backdating the timestamp
        from datetime import timedelta
        from src.api.routes import calendar_api

        calendar_api._cache["fetched_at"] = datetime.now(UTC) - timedelta(minutes=6)

        # Second call should re-fetch fresh data
        resp2 = await test_client.get("/v1/calendar/today", headers=api_key_headers)
        assert resp2.status_code == 200
        assert len(resp2.json()["events"]) == 3
        assert mock_fetch.call_count == 2


# ── Auth ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calendar_today_requires_auth(test_client) -> None:
    """Request without API key returns 401."""
    resp = await test_client.get("/v1/calendar/today")
    assert resp.status_code == 401
