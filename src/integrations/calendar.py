"""Google Calendar integration for Open Brain.

Fetches today's and tomorrow's events from Google Calendar API.
All Google dependencies are optional — the module loads without them and returns
an empty CalendarState if they are not installed or credentials are missing.

Usage:
    from src.integrations.calendar import fetch_today_events, CalendarState
    state = await fetch_today_events(settings)  # never raises
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from pydantic import BaseModel

logger = structlog.get_logger(__name__)

# ── Optional Google dependency guard ──────────────────────────────────────────

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build  # type: ignore[import-untyped]

    _GOOGLE_AVAILABLE = True
except ImportError:
    _GOOGLE_AVAILABLE = False

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


# ── Pydantic models ────────────────────────────────────────────────────────────


class CalendarEvent(BaseModel):
    """A timed or all-day event on today's calendar."""

    title: str
    start: str  # ISO format string
    end: str
    location: str | None = None
    calendar: str | None = None
    all_day: bool = False


class CalendarTomorrowEvent(BaseModel):
    """Minimal preview of a tomorrow event."""

    title: str
    start: str
    all_day: bool = False


class CalendarState(BaseModel):
    """Container returned by fetch_today_events."""

    fetched_at: str
    date: str
    events: list[CalendarEvent]
    tomorrow_preview: list[CalendarTomorrowEvent] = []


# ── Internal sync client (runs inside asyncio.to_thread) ──────────────────────


class _CalendarClient:
    """Synchronous Google Calendar client. Always run via asyncio.to_thread."""

    def __init__(self, credentials_path: str, token_path: str) -> None:
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._service: Any = None

        credentials = self._load_credentials()
        if credentials is None:
            return  # self._service stays None

        try:
            self._service = build("calendar", "v3", credentials=credentials)
        except Exception:
            logger.exception("calendar_service_build_failed")
            self._service = None

    def _load_credentials(self) -> Any | None:
        """Load credentials from token.json; refresh if expired. No interactive flow."""
        import os

        if not os.path.exists(self._token_path):
            logger.warning("calendar_token_missing", path=self._token_path)
            return None

        try:
            creds = Credentials.from_authorized_user_file(self._token_path, SCOPES)  # type: ignore[name-defined]
        except Exception:
            logger.exception("calendar_token_load_failed", path=self._token_path)
            return None

        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())  # type: ignore[name-defined]
                # Persist refreshed token
                with open(self._token_path, "w") as f:
                    f.write(creds.to_json())
            except Exception:
                logger.exception("calendar_token_refresh_failed")
                return None

        if not creds.valid:
            logger.warning("calendar_credentials_invalid")
            return None

        return creds

    def fetch_today(self) -> CalendarState:
        """Fetch today's events and tomorrow's preview. Returns empty state on failure."""
        if self._service is None:
            return _empty_calendar_state()

        try:
            today = datetime.now().date()
            tomorrow = today + timedelta(days=1)

            today_events = self._fetch_events_for_date(today.isoformat(), max_results=250)
            tomorrow_preview = self._fetch_events_for_date(tomorrow.isoformat(), max_results=5)

            return CalendarState(
                fetched_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                date=today.isoformat(),
                events=today_events,
                tomorrow_preview=tomorrow_preview,
            )
        except Exception:
            logger.exception("calendar_fetch_today_failed")
            return _empty_calendar_state()

    def _fetch_events_for_date(self, date_str: str, max_results: int = 250) -> list:
        """Fetch events from all calendars for a specific date."""
        if self._service is None:
            return []

        time_min = f"{date_str}T00:00:00Z"
        time_max = f"{date_str}T23:59:59Z"
        events: list[Any] = []

        try:
            calendars_result = self._service.calendarList().list().execute()
            calendar_ids = [cal["id"] for cal in calendars_result.get("items", [])]
        except Exception:
            logger.warning("calendar_list_failed_using_primary")
            calendar_ids = ["primary"]

        is_tomorrow_preview = max_results == 5

        for calendar_id in calendar_ids:
            try:
                result = (
                    self._service.events()
                    .list(
                        calendarId=calendar_id,
                        timeMin=time_min,
                        timeMax=time_max,
                        singleEvents=True,
                        orderBy="startTime",
                        maxResults=max_results,
                    )
                    .execute()
                )

                for item in result.get("items", []):
                    if "date" in item.get("start", {}):
                        start = item["start"]["date"]
                        end = item["end"]["date"]
                        all_day = True
                    else:
                        start = item.get("start", {}).get("dateTime", "")
                        end = item.get("end", {}).get("dateTime", "")
                        all_day = False

                    title = item.get("summary", "(No title)")
                    location = item.get("location")

                    if is_tomorrow_preview:
                        events.append(CalendarTomorrowEvent(title=title, start=start, all_day=all_day))
                    else:
                        events.append(
                            CalendarEvent(
                                title=title,
                                start=start,
                                end=end,
                                location=location,
                                calendar=calendar_id,
                                all_day=all_day,
                            )
                        )
            except Exception:
                logger.warning("calendar_fetch_events_failed", calendar_id=calendar_id)
                continue

        return events


# ── Public helpers ─────────────────────────────────────────────────────────────


def _empty_calendar_state() -> CalendarState:
    """Return a CalendarState with no events."""
    return CalendarState(
        fetched_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        date=datetime.now().date().isoformat(),
        events=[],
        tomorrow_preview=[],
    )


def is_calendar_available(settings: Any) -> bool:
    """Check whether Google Calendar integration is usable.

    Returns True when the Google client libraries are installed AND credential
    paths are configured.  Does NOT verify that the credentials are valid —
    that can only be confirmed by actually calling the API.
    """
    if not _GOOGLE_AVAILABLE:
        return False
    if not getattr(settings, "google_calendar_credentials_path", ""):
        return False
    if not getattr(settings, "google_calendar_token_path", ""):
        return False
    return True


async def fetch_today_events(settings: Any) -> CalendarState:
    """Fetch today's calendar events. Never raises; returns empty state on any error.

    Args:
        settings: Open Brain settings object with google_calendar_credentials_path
                  and google_calendar_token_path fields.

    Returns:
        CalendarState with today's events (possibly empty).
    """
    if not _GOOGLE_AVAILABLE:
        logger.warning("calendar_google_libs_not_installed")
        return _empty_calendar_state()

    if not getattr(settings, "google_calendar_credentials_path", "") or not getattr(
        settings, "google_calendar_token_path", ""
    ):
        logger.warning("calendar_credentials_not_configured")
        return _empty_calendar_state()

    try:
        client = _CalendarClient(
            settings.google_calendar_credentials_path,
            settings.google_calendar_token_path,
        )
        return await asyncio.to_thread(client.fetch_today)
    except Exception:
        logger.exception("calendar_fetch_failed")
        return _empty_calendar_state()
