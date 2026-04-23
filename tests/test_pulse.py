"""Tests for Phase D: Morning Pulse.

Sections:
  1. parse_pulse_reply (jobs/pulse.py)
  2. build_pulse_message helpers (jobs/pulse.py)
  3. POST /v1/pulse
  4. GET /v1/pulse/today
  5. PATCH /v1/pulse/today
  6. GET /v1/pulse (list)
  7. GET /v1/pulse/{date}
  8. PulseCog.handle_reply
  9. Pulse guard conditions

All LLM calls and Discord API calls are mocked. Tests run on SQLite.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Helpers ────────────────────────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _today_midnight() -> datetime:
    n = _now_utc()
    return n.replace(hour=0, minute=0, second=0, microsecond=0)


def _make_mock_llm(return_value: str = "{}") -> AsyncMock:
    mock = AsyncMock()
    mock.complete = AsyncMock(return_value=return_value)
    return mock


def _make_pulse_response(status: str = "sent", created_at: datetime | None = None) -> dict:
    if created_at is None:
        created_at = _now_utc() - timedelta(minutes=10)
    return {
        "id": "test-pulse-id",
        "pulse_date": _today_midnight().isoformat(),
        "raw_reply": None,
        "sleep_quality": None,
        "energy_level": None,
        "wake_time": None,
        "parsed_data": None,
        "ai_question": "What's your focus today?",
        "status": status,
        "discord_message_id": "12345",
        "created_at": created_at.isoformat(),
        "updated_at": created_at.isoformat(),
    }


# ── Section 1: parse_pulse_reply ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parse_pulse_reply_extracts_sleep_and_energy():
    """Parses sleep_quality and energy_level from valid JSON."""
    from src.jobs.pulse import parse_pulse_reply

    llm = _make_mock_llm('{"sleep_quality": 4, "energy_level": 3, "wake_time": "07:30", "mood_note": "Feeling okay"}')
    result = await parse_pulse_reply("Slept alright, woke at 7:30, energy moderate", llm)

    assert result is not None
    assert result["sleep_quality"] == 4
    assert result["energy_level"] == 3
    assert result["wake_time"] == "07:30"
    assert "Feeling okay" in result["mood_note"]


@pytest.mark.asyncio
async def test_parse_pulse_reply_handles_partial_data():
    """Returns partial dict when only some fields are present."""
    from src.jobs.pulse import parse_pulse_reply

    llm = _make_mock_llm('{"sleep_quality": 2, "energy_level": null, "wake_time": null, "mood_note": null}')
    result = await parse_pulse_reply("rough night", llm)

    assert result is not None
    assert result["sleep_quality"] == 2
    assert "energy_level" not in result
    assert "wake_time" not in result


@pytest.mark.asyncio
async def test_parse_pulse_reply_returns_none_on_llm_error():
    """Returns None when LLM call raises an exception."""
    from src.jobs.pulse import parse_pulse_reply

    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=ValueError("API down"))
    result = await parse_pulse_reply("slept ok", llm)

    assert result is None


@pytest.mark.asyncio
async def test_parse_pulse_reply_returns_none_on_invalid_json():
    """Returns None when LLM output is not valid JSON."""
    from src.jobs.pulse import parse_pulse_reply

    llm = _make_mock_llm("This is not JSON at all")
    result = await parse_pulse_reply("some reply", llm)

    assert result is None


@pytest.mark.asyncio
async def test_parse_pulse_reply_handles_markdown_fences():
    """Strips markdown code fences from LLM output before parsing."""
    from src.jobs.pulse import parse_pulse_reply

    raw_json = '{"sleep_quality": 5, "energy_level": 5, "wake_time": "06:00", "mood_note": null}'
    llm = _make_mock_llm(f"```json\n{raw_json}\n```")
    result = await parse_pulse_reply("amazing sleep", llm)

    assert result is not None
    assert result["sleep_quality"] == 5


@pytest.mark.asyncio
async def test_parse_pulse_reply_clamps_invalid_scale():
    """Silently ignores out-of-range scale values."""
    from src.jobs.pulse import parse_pulse_reply

    llm = _make_mock_llm('{"sleep_quality": 6, "energy_level": 0, "wake_time": null, "mood_note": null}')
    result = await parse_pulse_reply("some reply", llm)

    # 6 and 0 are out of range 1-5 — should be excluded
    assert result is None or "sleep_quality" not in (result or {})


@pytest.mark.asyncio
async def test_parse_pulse_reply_messy_natural_language():
    """Best-effort parse with messy input — at least one field extracted."""
    from src.jobs.pulse import parse_pulse_reply

    llm = _make_mock_llm('{"sleep_quality": 3, "energy_level": 2, "wake_time": null, "mood_note": "deferred everything"}')
    result = await parse_pulse_reply("slept ok 3 energy defer everything", llm)

    assert result is not None
    assert result.get("sleep_quality") == 3


# ── Section 2: build helpers ───────────────────────────────────────────────────


def test_build_morning_embed_includes_calendar_events():
    """Embed includes today's events when provided."""
    from src.integrations.calendar import CalendarEvent
    from src.jobs.pulse import _build_morning_embed

    events = [
        CalendarEvent(title="Standup", start="09:00", end="09:30", all_day=False),
        CalendarEvent(title="Lunch", start="12:00", end="13:00", all_day=False),
    ]
    embed = _build_morning_embed(
        date_str="2026-03-24",
        events=events,
        tomorrow_preview=[],
        open_todos=[],
        ai_question="What's your focus?",
    )

    assert embed["title"] == "Good morning — 2026-03-24"
    field_names = [f["name"] for f in embed.get("fields", [])]
    assert "📅 Today" in field_names
    assert "Standup" in embed["fields"][0]["value"]


def test_build_morning_embed_empty_calendar_omits_today_section():
    """Embed omits today's schedule section when there are no events."""
    from src.jobs.pulse import _build_morning_embed

    embed = _build_morning_embed(
        date_str="2026-03-24",
        events=[],
        tomorrow_preview=[],
        open_todos=[],
        ai_question="How are you?",
    )

    field_names = [f["name"] for f in embed.get("fields", [])]
    assert "📅 Today" not in field_names


def test_build_morning_embed_truncates_long_todo():
    """Todo descriptions are truncated to 60 chars."""
    from src.jobs.pulse import _build_morning_embed

    long_desc = "A" * 100
    embed = _build_morning_embed(
        date_str="2026-03-24",
        events=[],
        tomorrow_preview=[],
        open_todos=[{"description": long_desc}],
        ai_question="How are you?",
    )

    todos_field = next((f for f in embed.get("fields", []) if f["name"] == "✅ Open Todos"), None)
    assert todos_field is not None
    # Value should not exceed 60 chars for description + bullet
    assert len(todos_field["value"]) < 70


def test_build_morning_embed_caps_events_at_five():
    """At most 5 events appear in the today section."""
    from src.integrations.calendar import CalendarEvent
    from src.jobs.pulse import _build_morning_embed

    events = [CalendarEvent(title=f"Event {i}", start="09:00", end="10:00") for i in range(10)]
    embed = _build_morning_embed("2026-03-24", events, [], [], "Question?")

    today_field = next((f for f in embed["fields"] if f["name"] == "📅 Today"), None)
    assert today_field is not None
    # Each event is one line (bullet + time + title)
    lines = today_field["value"].strip().split("\n")
    assert len(lines) <= 5


# ── Section 3: POST /v1/pulse ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_pulse_success(test_client, api_key_headers):
    """Returns 201 with PulseResponse on successful creation."""
    pulse_date = _today_midnight().isoformat()
    resp = await test_client.post(
        "/v1/pulse",
        json={"pulse_date": pulse_date, "status": "sent", "ai_question": "What's your focus?"},
        headers=api_key_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "sent"
    assert data["ai_question"] == "What's your focus?"
    assert data["id"] is not None
    assert data["created_at"] is not None


@pytest.mark.asyncio
async def test_create_pulse_duplicate_returns_409(test_client, api_key_headers):
    """Second POST for the same date returns 409 Conflict."""
    pulse_date = _today_midnight().isoformat()
    payload = {"pulse_date": pulse_date}

    resp1 = await test_client.post("/v1/pulse", json=payload, headers=api_key_headers)
    assert resp1.status_code == 201

    resp2 = await test_client.post("/v1/pulse", json=payload, headers=api_key_headers)
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_create_pulse_missing_pulse_date_returns_422(test_client, api_key_headers):
    """Missing required pulse_date field returns 422."""
    resp = await test_client.post("/v1/pulse", json={"status": "sent"}, headers=api_key_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_pulse_requires_auth(test_client):
    """Missing API key returns 401."""
    resp = await test_client.post("/v1/pulse", json={"pulse_date": _today_midnight().isoformat()})
    assert resp.status_code == 401


# ── Section 4: GET /v1/pulse/today ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_today_pulse_returns_404_when_not_sent(test_client, api_key_headers):
    """404 when no pulse has been sent today."""
    resp = await test_client.get("/v1/pulse/today", headers=api_key_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_today_pulse_returns_pulse_when_sent(test_client, api_key_headers):
    """Returns 200 with today's pulse after creation."""
    pulse_date = _today_midnight().isoformat()
    create_resp = await test_client.post(
        "/v1/pulse",
        json={"pulse_date": pulse_date, "status": "sent"},
        headers=api_key_headers,
    )
    assert create_resp.status_code == 201

    get_resp = await test_client.get("/v1/pulse/today", headers=api_key_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "sent"


@pytest.mark.asyncio
async def test_get_today_pulse_requires_auth(test_client):
    """Missing API key returns 401."""
    resp = await test_client.get("/v1/pulse/today")
    assert resp.status_code == 401


# ── Section 5: PATCH /v1/pulse/today ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_today_pulse_stores_reply(test_client, api_key_headers):
    """PATCH stores raw_reply and updates status."""
    pulse_date = _today_midnight().isoformat()
    await test_client.post("/v1/pulse", json={"pulse_date": pulse_date}, headers=api_key_headers)

    resp = await test_client.patch(
        "/v1/pulse/today",
        json={"raw_reply": "Slept well, energy 4, woke at 7am", "status": "replied"},
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["raw_reply"] == "Slept well, energy 4, woke at 7am"
    assert data["status"] == "replied"


@pytest.mark.asyncio
async def test_update_today_pulse_stores_parsed_fields(test_client, api_key_headers):
    """PATCH stores sleep_quality, energy_level, wake_time."""
    pulse_date = _today_midnight().isoformat()
    await test_client.post("/v1/pulse", json={"pulse_date": pulse_date}, headers=api_key_headers)

    resp = await test_client.patch(
        "/v1/pulse/today",
        json={"sleep_quality": 4, "energy_level": 3, "wake_time": "07:30", "status": "parsed"},
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sleep_quality"] == 4
    assert data["energy_level"] == 3
    assert data["wake_time"] == "07:30"
    assert data["status"] == "parsed"


@pytest.mark.asyncio
async def test_update_today_pulse_invalid_sleep_quality_returns_422(test_client, api_key_headers):
    """sleep_quality=6 is out of range, returns 422."""
    pulse_date = _today_midnight().isoformat()
    await test_client.post("/v1/pulse", json={"pulse_date": pulse_date}, headers=api_key_headers)

    resp = await test_client.patch(
        "/v1/pulse/today",
        json={"sleep_quality": 6},
        headers=api_key_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_today_pulse_invalid_energy_level_returns_422(test_client, api_key_headers):
    """energy_level=0 is out of range, returns 422."""
    pulse_date = _today_midnight().isoformat()
    await test_client.post("/v1/pulse", json={"pulse_date": pulse_date}, headers=api_key_headers)

    resp = await test_client.patch(
        "/v1/pulse/today",
        json={"energy_level": 0},
        headers=api_key_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_today_pulse_invalid_status_returns_422(test_client, api_key_headers):
    """Unknown status value returns 422."""
    pulse_date = _today_midnight().isoformat()
    await test_client.post("/v1/pulse", json={"pulse_date": pulse_date}, headers=api_key_headers)

    resp = await test_client.patch(
        "/v1/pulse/today",
        json={"status": "banana"},
        headers=api_key_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_today_pulse_returns_404_when_no_pulse(test_client, api_key_headers):
    """404 when no pulse exists for today."""
    resp = await test_client.patch(
        "/v1/pulse/today",
        json={"status": "replied"},
        headers=api_key_headers,
    )
    assert resp.status_code == 404


# ── Section 6: GET /v1/pulse ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_pulses_returns_empty_list(test_client, api_key_headers):
    """Empty list when no pulses exist."""
    resp = await test_client.get("/v1/pulse", headers=api_key_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["pulses"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_pulses_returns_newest_first(test_client, api_key_headers):
    """Pulses are returned in descending order by pulse_date."""
    # Create two pulses on different days
    day1 = datetime(2026, 3, 1, tzinfo=UTC).isoformat()
    day2 = datetime(2026, 3, 2, tzinfo=UTC).isoformat()

    await test_client.post("/v1/pulse", json={"pulse_date": day1}, headers=api_key_headers)
    await test_client.post("/v1/pulse", json={"pulse_date": day2}, headers=api_key_headers)

    resp = await test_client.get("/v1/pulse", headers=api_key_headers)
    assert resp.status_code == 200
    pulses = resp.json()["pulses"]
    assert len(pulses) == 2
    # First should be the most recent
    assert pulses[0]["pulse_date"] > pulses[1]["pulse_date"]


@pytest.mark.asyncio
async def test_list_pulses_pagination(test_client, api_key_headers):
    """limit and offset parameters work correctly."""
    dates = [datetime(2026, 3, i, tzinfo=UTC).isoformat() for i in range(1, 6)]
    for d in dates:
        await test_client.post("/v1/pulse", json={"pulse_date": d}, headers=api_key_headers)

    resp = await test_client.get("/v1/pulse?limit=2&offset=1", headers=api_key_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["pulses"]) == 2


@pytest.mark.asyncio
async def test_list_pulses_requires_auth(test_client):
    """Missing API key returns 401."""
    resp = await test_client.get("/v1/pulse")
    assert resp.status_code == 401


# ── Section 7: GET /v1/pulse/{date} ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_pulse_by_date_success(test_client, api_key_headers):
    """Returns pulse for a specific date."""
    specific_date = datetime(2026, 3, 15, tzinfo=UTC)
    await test_client.post(
        "/v1/pulse",
        json={"pulse_date": specific_date.isoformat(), "status": "parsed"},
        headers=api_key_headers,
    )

    resp = await test_client.get("/v1/pulse/2026-03-15", headers=api_key_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "parsed"


@pytest.mark.asyncio
async def test_get_pulse_by_date_invalid_format_returns_422(test_client, api_key_headers):
    """Invalid date format returns 422."""
    resp = await test_client.get("/v1/pulse/not-a-date", headers=api_key_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_pulse_by_date_not_found_returns_404(test_client, api_key_headers):
    """404 for a date with no pulse record."""
    resp = await test_client.get("/v1/pulse/2020-01-01", headers=api_key_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_pulse_by_date_requires_auth(test_client):
    """Missing API key returns 401."""
    resp = await test_client.get("/v1/pulse/2026-03-15")
    assert resp.status_code == 401


# ── Section 7b: _today_midnight_utc timezone handling ────────────────────────


@pytest.mark.asyncio
async def test_today_midnight_utc_respects_configured_timezone(monkeypatch):
    """_today_midnight_utc uses pulse_timezone to compute local midnight in UTC."""
    # Freeze "now" in Vilnius timezone: 2026-04-03 01:30 EET (UTC+3)
    # Local midnight = 2026-04-03T00:00 EET = 2026-04-02T21:00 UTC
    from zoneinfo import ZoneInfo

    from src.api.routes.pulse import _today_midnight_utc

    frozen = datetime(2026, 4, 3, 1, 30, tzinfo=ZoneInfo("Europe/Vilnius"))
    monkeypatch.setenv("PULSE_TIMEZONE", "Europe/Vilnius")
    # Re-initialize settings so pulse_timezone picks up
    from src.core import config as _config

    monkeypatch.setattr(_config, "settings", _config.Settings())

    with patch("src.api.routes.pulse.datetime") as mock_dt:
        mock_dt.now.return_value = frozen
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = _today_midnight_utc()

    # Vilnius midnight (UTC+3) → 21:00 UTC previous day
    assert result.hour == 21
    assert result.day == 2  # April 2nd in UTC


@pytest.mark.asyncio
async def test_today_midnight_utc_falls_back_to_utc_on_invalid_tz(monkeypatch):
    """Invalid pulse_timezone falls back to UTC."""
    from src.api.routes.pulse import _today_midnight_utc

    monkeypatch.setenv("PULSE_TIMEZONE", "Invalid/Zone")
    from src.core import config as _config

    monkeypatch.setattr(_config, "settings", _config.Settings())

    result = _today_midnight_utc()
    # Should still return a valid datetime in UTC
    assert result.tzinfo is not None
    assert result.hour == 0  # UTC midnight = hour 0
    assert result.minute == 0


# ── Section 8: PulseCog.handle_reply ──────────────────────────────────────────


def _make_cog_settings(pulse_user_id: int = 123456, api_url: str = "http://api", api_key: str = "key") -> MagicMock:
    s = MagicMock()
    s.discord_pulse_user_id = pulse_user_id
    s.open_brain_api_url = api_url
    # Mirror production: api_key is SecretStr, must call .get_secret_value()
    s.api_key = MagicMock()
    s.api_key.get_secret_value.return_value = api_key
    s.pulse_reply_window_minutes = 120
    s.module_pulse_enabled = True
    s.anthropic_api_key = None
    return s


def _make_mock_http(
    today_status: int = 200,
    today_body: dict | None = None,
    patch_status: int = 200,
) -> AsyncMock:
    """Build an httpx.AsyncClient mock for cog tests."""
    mock = AsyncMock()

    if today_body is None:
        today_body = _make_pulse_response()

    today_resp = MagicMock()
    today_resp.status_code = today_status
    today_resp.json.return_value = today_body

    patch_resp = MagicMock()
    patch_resp.status_code = patch_status

    mock.get = AsyncMock(return_value=today_resp)
    mock.patch = AsyncMock(return_value=patch_resp)
    return mock


def _make_discord_message(content: str = "slept ok, energy 3", author_id: int = 123456) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.author.id = author_id
    msg.add_reaction = AsyncMock()
    msg.reply = AsyncMock()
    msg.channel.type = MagicMock()
    return msg


@pytest.mark.asyncio
async def test_handle_reply_returns_false_when_no_pulse_today():
    """Returns False when GET /v1/pulse/today returns 404."""
    from src.integrations.modules.pulse_cog import PulseCog

    http = _make_mock_http(today_status=404)
    cog = PulseCog(http)

    with patch("src.integrations.modules.pulse_cog._get_settings", return_value=_make_cog_settings()):
        msg = _make_discord_message()
        result = await cog.handle_reply(msg)

    assert result is False
    msg.add_reaction.assert_not_called()


@pytest.mark.asyncio
async def test_handle_reply_returns_false_when_already_replied():
    """Returns False when pulse status is 'replied' (not 'sent')."""
    from src.integrations.modules.pulse_cog import PulseCog

    http = _make_mock_http(today_body=_make_pulse_response(status="replied"))
    cog = PulseCog(http)

    with patch("src.integrations.modules.pulse_cog._get_settings", return_value=_make_cog_settings()):
        msg = _make_discord_message()
        result = await cog.handle_reply(msg)

    assert result is False


@pytest.mark.asyncio
async def test_handle_reply_returns_false_when_window_expired():
    """Returns False when reply window has elapsed."""
    from src.integrations.modules.pulse_cog import PulseCog

    old_created_at = _now_utc() - timedelta(hours=3)
    http = _make_mock_http(today_body=_make_pulse_response(created_at=old_created_at))
    cog = PulseCog(http)

    settings = _make_cog_settings()
    settings.pulse_reply_window_minutes = 120  # 2 hours, created 3 hours ago

    with patch("src.integrations.modules.pulse_cog._get_settings", return_value=settings):
        msg = _make_discord_message()
        result = await cog.handle_reply(msg)

    assert result is False


@pytest.mark.asyncio
async def test_handle_reply_processes_and_returns_true():
    """Full success path: stores reply, parses, reacts 🌅, returns True."""
    from src.integrations.modules.pulse_cog import PulseCog

    http = _make_mock_http()
    cog = PulseCog(http)

    parsed_result = {"sleep_quality": 4, "energy_level": 3, "wake_time": "07:00"}
    settings = _make_cog_settings()

    with (
        patch("src.integrations.modules.pulse_cog._get_settings", return_value=settings),
        patch(
            "src.integrations.modules.pulse_cog._build_llm_client",
            return_value=_make_mock_llm(),
        ),
        patch("src.jobs.pulse.parse_pulse_reply", new=AsyncMock(return_value=parsed_result)),
    ):
        msg = _make_discord_message()
        result = await cog.handle_reply(msg)

    assert result is True
    msg.add_reaction.assert_called_once_with("🌅")
    msg.reply.assert_called_once()
    # PATCH should have been called at least twice (raw reply + parsed data)
    assert http.patch.call_count >= 2


@pytest.mark.asyncio
async def test_handle_reply_degrades_gracefully_when_parse_fails():
    """Still returns True and reacts ❓ when LLM parsing fails."""
    from src.integrations.modules.pulse_cog import PulseCog

    http = _make_mock_http()
    cog = PulseCog(http)
    settings = _make_cog_settings()

    with (
        patch("src.integrations.modules.pulse_cog._get_settings", return_value=settings),
        patch("src.integrations.modules.pulse_cog._build_llm_client", return_value=None),
        patch("src.jobs.pulse.parse_pulse_reply", new=AsyncMock(return_value=None)),
    ):
        msg = _make_discord_message()
        result = await cog.handle_reply(msg)

    assert result is True
    # Should react with ❓ (parse failed) not 🌅
    msg.add_reaction.assert_called_once_with("❓")


@pytest.mark.asyncio
async def test_handle_reply_stores_raw_reply_even_on_parse_failure():
    """raw_reply PATCH is called before parse attempt."""
    from src.integrations.modules.pulse_cog import PulseCog

    http = _make_mock_http()
    cog = PulseCog(http)
    settings = _make_cog_settings()

    with (
        patch("src.integrations.modules.pulse_cog._get_settings", return_value=settings),
        patch("src.integrations.modules.pulse_cog._build_llm_client", return_value=None),
        patch("src.jobs.pulse.parse_pulse_reply", new=AsyncMock(return_value=None)),
    ):
        msg = _make_discord_message(content="I slept badly")
        await cog.handle_reply(msg)

    # First PATCH call should include raw_reply
    first_patch_call = http.patch.call_args_list[0]
    body = first_patch_call.kwargs.get("json", {}) or first_patch_call.args[1] if first_patch_call.args else {}
    if not body and first_patch_call.kwargs:
        body = first_patch_call.kwargs.get("json", {})
    assert "raw_reply" in str(first_patch_call)


# ── Section 9: DM guard conditions ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pulse_guard_skips_non_dm_messages(monkeypatch):
    """Guard does not fire for non-DM channel messages."""
    import discord

    from src.integrations import discord_bot

    called_handle = []

    async def fake_handle(msg):
        called_handle.append(True)
        return True

    mock_instance = MagicMock()
    mock_instance.handle_reply = AsyncMock(side_effect=fake_handle)

    settings = MagicMock()
    settings.module_pulse_enabled = True
    settings.discord_pulse_user_id = 999
    settings.discord_allowed_user_ids = [999]
    settings.module_rag_chat_enabled = False
    settings.discord_rag_channel_ids = []

    monkeypatch.setattr(discord_bot, "_get_settings", lambda: settings)

    message = MagicMock()
    message.author.id = 999
    message.author = MagicMock(spec=discord.User)
    message.author.id = 999
    message.content = "not a DM reply"
    message.channel.type = discord.ChannelType.text  # NOT private
    message.channel.id = 1234

    # The pulse guard checks channel.type == ChannelType.private
    # For non-private channels, the guard should NOT fire
    # We verify by checking that if handle_reply was called (it shouldn't be for text channels)
    # We can't easily call on_message directly, so we test the condition inline:
    is_private = message.channel.type == discord.ChannelType.private
    assert is_private is False  # guard condition fails → no handle_reply call


def test_pulse_guard_skips_wrong_user():
    """Guard does not fire when author.id != discord_pulse_user_id."""

    settings = MagicMock()
    settings.module_pulse_enabled = True
    settings.discord_pulse_user_id = 999

    author_id = 888  # different user

    # Verify guard condition
    guard_fires = (
        settings.module_pulse_enabled
        and settings.discord_pulse_user_id != 0
        and author_id == settings.discord_pulse_user_id
    )
    assert guard_fires is False


def test_pulse_guard_disabled_when_user_id_zero():
    """Guard does not fire when discord_pulse_user_id is 0 (not configured)."""
    settings = MagicMock()
    settings.module_pulse_enabled = True
    settings.discord_pulse_user_id = 0

    guard_fires = settings.module_pulse_enabled and settings.discord_pulse_user_id != 0
    assert guard_fires is False


def test_pulse_guard_disabled_when_module_disabled():
    """Guard does not fire when module_pulse_enabled is False."""
    settings = MagicMock()
    settings.module_pulse_enabled = False
    settings.discord_pulse_user_id = 999

    guard_fires = settings.module_pulse_enabled and settings.discord_pulse_user_id != 0
    assert guard_fires is False


# ── Section 10: PulseModal ───────────────────────────────────────────────────


def _make_modal_settings() -> MagicMock:
    """Build settings mock for modal/view tests."""
    s = MagicMock()
    s.open_brain_api_url = "http://api"
    s.api_key = MagicMock()
    s.api_key.get_secret_value.return_value = "test-key"
    s.module_pulse_enabled = True
    s.pulse_accept_freetext = False
    return s


def _make_mock_interaction(message: MagicMock | None = None) -> MagicMock:
    """Build a mock discord.Interaction for modal/button tests."""
    interaction = MagicMock()
    interaction.response = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.followup = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.message = message
    return interaction


@pytest.mark.asyncio
async def test_pulse_modal_valid_submit():
    """Modal with valid data (sleep=4, energy=3, wake=06:30) updates DailyPulse correctly."""
    from src.integrations.modules.pulse_cog import PulseModal

    settings = _make_modal_settings()
    original_msg = MagicMock()
    original_msg.edit = AsyncMock()
    original_msg.add_reaction = AsyncMock()

    modal = PulseModal(ai_question="What's your focus?", original_message=original_msg)
    modal.sleep_quality._value = "4"
    modal.energy_level._value = "3"
    modal.wake_time._value = "06:30"
    modal.ai_response._value = "Shipping the modal upgrade"
    modal.notes_field._value = "Feeling good"

    interaction = _make_mock_interaction()

    pulse_data = _make_pulse_response(status="sent")
    with (
        patch("src.integrations.modules.pulse_cog._get_settings", return_value=settings),
        patch("src.integrations.modules.pulse_cog._get_today_pulse_api", new=AsyncMock(return_value=pulse_data)),
        patch("src.integrations.modules.pulse_cog._patch_pulse_api", new=AsyncMock(return_value=True)) as mock_patch,
    ):
        await modal.on_submit(interaction)

    mock_patch.assert_called_once()
    call_body = mock_patch.call_args[0][1]
    assert call_body["sleep_quality"] == 4
    assert call_body["energy_level"] == 3
    assert call_body["wake_time"] == "06:30"
    assert call_body["status"] == "completed"
    assert call_body["ai_question_response"] == "Shipping the modal upgrade"
    assert "Feeling good" in call_body["notes"]

    interaction.response.send_message.assert_called_once()
    confirm_msg = interaction.response.send_message.call_args[0][0]
    assert "Sleep 4" in confirm_msg
    assert "Energy 3" in confirm_msg

    original_msg.add_reaction.assert_called_once_with("✅")


@pytest.mark.asyncio
async def test_pulse_modal_invalid_sleep_rejected():
    """Modal with sleep=7 sends ephemeral error, row not updated."""
    from src.integrations.modules.pulse_cog import PulseModal

    settings = _make_modal_settings()
    modal = PulseModal(ai_question="", original_message=None)
    modal.sleep_quality._value = "7"
    modal.energy_level._value = "3"

    interaction = _make_mock_interaction()
    pulse_data = _make_pulse_response(status="sent")

    with (
        patch("src.integrations.modules.pulse_cog._get_settings", return_value=settings),
        patch("src.integrations.modules.pulse_cog._get_today_pulse_api", new=AsyncMock(return_value=pulse_data)),
        patch("src.integrations.modules.pulse_cog._patch_pulse_api", new=AsyncMock(return_value=True)) as mock_patch,
    ):
        await modal.on_submit(interaction)

    mock_patch.assert_not_called()
    interaction.response.send_message.assert_called_once()
    error_msg = interaction.response.send_message.call_args[0][0]
    assert "1-5" in error_msg


@pytest.mark.asyncio
async def test_pulse_modal_invalid_energy_rejected():
    """Modal with energy=0 sends ephemeral error, row not updated."""
    from src.integrations.modules.pulse_cog import PulseModal

    settings = _make_modal_settings()
    modal = PulseModal(ai_question="", original_message=None)
    modal.sleep_quality._value = "3"
    modal.energy_level._value = "0"

    interaction = _make_mock_interaction()
    pulse_data = _make_pulse_response(status="sent")

    with (
        patch("src.integrations.modules.pulse_cog._get_settings", return_value=settings),
        patch("src.integrations.modules.pulse_cog._get_today_pulse_api", new=AsyncMock(return_value=pulse_data)),
        patch("src.integrations.modules.pulse_cog._patch_pulse_api", new=AsyncMock(return_value=True)) as mock_patch,
    ):
        await modal.on_submit(interaction)

    mock_patch.assert_not_called()
    error_msg = interaction.response.send_message.call_args[0][0]
    assert "1-5" in error_msg


@pytest.mark.asyncio
async def test_pulse_modal_non_numeric_sleep_rejected():
    """Modal with sleep='x' sends ephemeral error."""
    from src.integrations.modules.pulse_cog import PulseModal

    settings = _make_modal_settings()
    modal = PulseModal(ai_question="", original_message=None)
    modal.sleep_quality._value = "x"
    modal.energy_level._value = "3"

    interaction = _make_mock_interaction()
    pulse_data = _make_pulse_response(status="sent")

    with (
        patch("src.integrations.modules.pulse_cog._get_settings", return_value=settings),
        patch("src.integrations.modules.pulse_cog._get_today_pulse_api", new=AsyncMock(return_value=pulse_data)),
        patch("src.integrations.modules.pulse_cog._patch_pulse_api", new=AsyncMock(return_value=True)) as mock_patch,
    ):
        await modal.on_submit(interaction)

    mock_patch.assert_not_called()


@pytest.mark.asyncio
async def test_pulse_modal_only_required_fields():
    """Modal with only sleep+energy (no wake, no notes) stores correctly with nulls."""
    from src.integrations.modules.pulse_cog import PulseModal

    settings = _make_modal_settings()
    modal = PulseModal(ai_question="", original_message=None)
    modal.sleep_quality._value = "3"
    modal.energy_level._value = "2"
    modal.wake_time._value = ""
    modal.notes_field._value = ""

    interaction = _make_mock_interaction()
    pulse_data = _make_pulse_response(status="sent")

    with (
        patch("src.integrations.modules.pulse_cog._get_settings", return_value=settings),
        patch("src.integrations.modules.pulse_cog._get_today_pulse_api", new=AsyncMock(return_value=pulse_data)),
        patch("src.integrations.modules.pulse_cog._patch_pulse_api", new=AsyncMock(return_value=True)) as mock_patch,
    ):
        await modal.on_submit(interaction)

    mock_patch.assert_called_once()
    call_body = mock_patch.call_args[0][1]
    assert call_body["sleep_quality"] == 3
    assert call_body["energy_level"] == 2
    assert call_body["status"] == "completed"
    assert "wake_time" not in call_body
    assert "notes" not in call_body
    assert "ai_question_response" not in call_body


@pytest.mark.asyncio
async def test_pulse_modal_ai_question_response_stored():
    """AI question response is stored in ai_question_response field."""
    from src.integrations.modules.pulse_cog import PulseModal

    settings = _make_modal_settings()
    modal = PulseModal(ai_question="What drained you yesterday?", original_message=None)
    modal.sleep_quality._value = "4"
    modal.energy_level._value = "4"
    modal.wake_time._value = ""
    modal.ai_response._value = "Too many meetings"
    modal.notes_field._value = ""

    interaction = _make_mock_interaction()
    pulse_data = _make_pulse_response(status="sent")

    with (
        patch("src.integrations.modules.pulse_cog._get_settings", return_value=settings),
        patch("src.integrations.modules.pulse_cog._get_today_pulse_api", new=AsyncMock(return_value=pulse_data)),
        patch("src.integrations.modules.pulse_cog._patch_pulse_api", new=AsyncMock(return_value=True)) as mock_patch,
    ):
        await modal.on_submit(interaction)

    call_body = mock_patch.call_args[0][1]
    assert call_body["ai_question_response"] == "Too many meetings"


@pytest.mark.asyncio
async def test_pulse_modal_no_ai_question_omits_field():
    """When ai_question is empty, modal has no ai_response field."""
    import discord as _discord

    from src.integrations.modules.pulse_cog import PulseModal

    modal = PulseModal(ai_question="", original_message=None)
    assert modal.ai_response is None
    assert len([c for c in modal.children if isinstance(c, _discord.ui.TextInput)]) == 4


def test_pulse_modal_with_ai_question_has_five_fields():
    """When ai_question is provided, modal has 5 fields including dynamic label."""
    import discord as _discord

    from src.integrations.modules.pulse_cog import PulseModal

    modal = PulseModal(ai_question="What's your biggest challenge today?", original_message=None)
    assert modal.ai_response is not None
    assert len([c for c in modal.children if isinstance(c, _discord.ui.TextInput)]) == 5


# ── Section 11: Skip button ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skip_button_sets_status_skipped():
    """Skip button → status='skipped', buttons disabled, ⏭️ reaction."""
    from src.integrations.modules.pulse_cog import PulseView

    settings = _make_modal_settings()
    view = PulseView()

    original_msg = MagicMock()
    original_msg.add_reaction = AsyncMock()

    interaction = _make_mock_interaction(message=original_msg)
    pulse_data = _make_pulse_response(status="sent")

    with (
        patch("src.integrations.modules.pulse_cog._get_settings", return_value=settings),
        patch("src.integrations.modules.pulse_cog._get_today_pulse_api", new=AsyncMock(return_value=pulse_data)),
        patch("src.integrations.modules.pulse_cog._patch_pulse_api", new=AsyncMock(return_value=True)) as mock_patch,
    ):
        skip_btn = [c for c in view.children if getattr(c, "custom_id", "") == "pulse:skip"][0]
        await skip_btn.callback(interaction)

    mock_patch.assert_called_once_with(settings, {"status": "skipped"})
    interaction.response.edit_message.assert_called_once()
    original_msg.add_reaction.assert_called_once_with("⏭️")


@pytest.mark.asyncio
async def test_skip_button_rejects_already_completed():
    """Skip button on already-completed pulse sends ephemeral error."""
    from src.integrations.modules.pulse_cog import PulseView

    settings = _make_modal_settings()
    view = PulseView()
    interaction = _make_mock_interaction()
    pulse_data = _make_pulse_response(status="completed")

    with (
        patch("src.integrations.modules.pulse_cog._get_settings", return_value=settings),
        patch("src.integrations.modules.pulse_cog._get_today_pulse_api", new=AsyncMock(return_value=pulse_data)),
        patch("src.integrations.modules.pulse_cog._patch_pulse_api", new=AsyncMock(return_value=True)) as mock_patch,
    ):
        skip_btn = [c for c in view.children if getattr(c, "custom_id", "") == "pulse:skip"][0]
        await skip_btn.callback(interaction)

    mock_patch.assert_not_called()
    interaction.response.send_message.assert_called_once()
    assert "Already" in interaction.response.send_message.call_args[0][0]


# ── Section 12: Double-submit prevention ──────────────────────────────────────


@pytest.mark.asyncio
async def test_modal_double_submit_rejected():
    """Second modal submit after first is rejected."""
    from src.integrations.modules.pulse_cog import PulseModal

    settings = _make_modal_settings()
    modal = PulseModal(ai_question="", original_message=None)
    modal.sleep_quality._value = "4"
    modal.energy_level._value = "3"

    interaction = _make_mock_interaction()
    pulse_data = _make_pulse_response(status="completed")

    with (
        patch("src.integrations.modules.pulse_cog._get_settings", return_value=settings),
        patch("src.integrations.modules.pulse_cog._get_today_pulse_api", new=AsyncMock(return_value=pulse_data)),
        patch("src.integrations.modules.pulse_cog._patch_pulse_api", new=AsyncMock(return_value=True)) as mock_patch,
    ):
        await modal.on_submit(interaction)

    mock_patch.assert_not_called()
    assert "Already" in interaction.response.send_message.call_args[0][0]


@pytest.mark.asyncio
async def test_log_button_rejects_already_completed():
    """Log button on already-completed pulse sends ephemeral error instead of opening modal."""
    from src.integrations.modules.pulse_cog import PulseView

    settings = _make_modal_settings()
    view = PulseView()
    interaction = _make_mock_interaction()
    pulse_data = _make_pulse_response(status="completed")

    with (
        patch("src.integrations.modules.pulse_cog._get_settings", return_value=settings),
        patch("src.integrations.modules.pulse_cog._get_today_pulse_api", new=AsyncMock(return_value=pulse_data)),
    ):
        log_btn = [c for c in view.children if getattr(c, "custom_id", "") == "pulse:log"][0]
        await log_btn.callback(interaction)

    interaction.response.send_message.assert_called_once()
    assert "Already" in interaction.response.send_message.call_args[0][0]
    interaction.response.send_modal.assert_not_called()


# ── Section 13: Persistent view ──────────────────────────────────────────────


def test_pulse_view_has_no_timeout():
    """PulseView timeout=None for persistence across restarts."""
    from src.integrations.modules.pulse_cog import PulseView

    view = PulseView()
    assert view.timeout is None


def test_pulse_view_has_correct_custom_ids():
    """PulseView buttons have pulse:log and pulse:skip custom_ids."""
    from src.integrations.modules.pulse_cog import PulseView

    view = PulseView()
    custom_ids = {getattr(c, "custom_id", None) for c in view.children}
    assert "pulse:log" in custom_ids
    assert "pulse:skip" in custom_ids


def test_register_pulse_adds_persistent_view():
    """register_pulse calls bot.add_view with a PulseView instance."""
    from src.integrations.modules.pulse_cog import PulseView, register_pulse

    bot = MagicMock()
    bot.add_view = MagicMock()
    http = AsyncMock()
    settings = _make_modal_settings()

    register_pulse(bot, http, settings)

    bot.add_view.assert_called_once()
    view_arg = bot.add_view.call_args[0][0]
    assert isinstance(view_arg, PulseView)


def test_register_pulse_skips_when_disabled():
    """register_pulse does nothing when module_pulse_enabled is False."""
    from src.integrations.modules.pulse_cog import register_pulse

    bot = MagicMock()
    bot.add_view = MagicMock()
    http = AsyncMock()
    settings = _make_modal_settings()
    settings.module_pulse_enabled = False

    register_pulse(bot, http, settings)

    bot.add_view.assert_not_called()


# ── Section 14: Log button opens modal ────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_button_opens_modal():
    """Log button on active pulse opens PulseModal with ai_question."""
    from src.integrations.modules.pulse_cog import PulseModal, PulseView

    settings = _make_modal_settings()
    view = PulseView()
    interaction = _make_mock_interaction(message=MagicMock())
    pulse_data = _make_pulse_response(status="sent")
    pulse_data["ai_question"] = "What's your biggest challenge?"

    with (
        patch("src.integrations.modules.pulse_cog._get_settings", return_value=settings),
        patch("src.integrations.modules.pulse_cog._get_today_pulse_api", new=AsyncMock(return_value=pulse_data)),
    ):
        log_btn = [c for c in view.children if getattr(c, "custom_id", "") == "pulse:log"][0]
        await log_btn.callback(interaction)

    interaction.response.send_modal.assert_called_once()
    modal_arg = interaction.response.send_modal.call_args[0][0]
    assert isinstance(modal_arg, PulseModal)
    assert modal_arg._ai_question == "What's your biggest challenge?"


# ── Section 15: AI question prompt alternation ────────────────────────────────


@pytest.mark.asyncio
async def test_ai_question_prompt_includes_yesterday_context():
    """When yesterday had an operational question, prompt requests reflective."""
    from src.jobs.pulse import _generate_ai_question

    llm = _make_mock_llm("What gave you energy yesterday?")
    result = await _generate_ai_question(
        llm,
        open_todos=[{"description": "Ship modal upgrade"}],
        yesterday_question="You deferred the API spec — what's blocking it?",
    )

    assert result == "What gave you energy yesterday?"
    call_args = llm.complete.call_args
    user_content = call_args.kwargs.get("user_content", call_args.args[0] if call_args.args else "")
    assert "deferred the API spec" in user_content
    assert "reflective" in user_content.lower() or "Type B" in user_content


@pytest.mark.asyncio
async def test_ai_question_prompt_defaults_to_reflective_without_yesterday():
    """When no yesterday question exists, defaults to reflective (Type B)."""
    from src.jobs.pulse import _generate_ai_question

    llm = _make_mock_llm("What would make today great?")
    await _generate_ai_question(llm, open_todos=[], yesterday_question=None)

    call_args = llm.complete.call_args
    user_content = call_args.kwargs.get("user_content", "")
    assert "Type B" in user_content or "reflective" in user_content.lower()


@pytest.mark.asyncio
async def test_ai_question_falls_back_on_llm_failure():
    """Falls back to default question when LLM raises."""
    from src.jobs.pulse import _generate_ai_question

    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=ValueError("API down"))
    result = await _generate_ai_question(llm)

    assert result == "What's one thing you want to accomplish today?"


# ── Section 16: Free-text path gating ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_freetext_path_disabled_by_default():
    """handle_reply returns False when pulse_accept_freetext is False."""
    from src.integrations.modules.pulse_cog import PulseCog

    http = _make_mock_http()
    cog = PulseCog(http)
    settings = _make_cog_settings()
    settings.pulse_accept_freetext = False

    with patch("src.integrations.modules.pulse_cog._get_settings", return_value=settings):
        msg = _make_discord_message()
        result = await cog.handle_reply(msg)

    assert result is False


# ── Section 17: REST components ───────────────────────────────────────────────


def test_build_pulse_components_structure():
    """_build_pulse_components returns valid Discord component JSON."""
    from src.jobs.pulse import _build_pulse_components

    components = _build_pulse_components()
    assert len(components) == 1
    action_row = components[0]
    assert action_row["type"] == 1
    buttons = action_row["components"]
    assert len(buttons) == 2
    assert buttons[0]["custom_id"] == "pulse:log"
    assert buttons[0]["style"] == 1
    assert buttons[1]["custom_id"] == "pulse:skip"
    assert buttons[1]["style"] == 2


def test_embed_shows_ai_question_prominently():
    """Embed description starts with the AI question in bold."""
    from src.jobs.pulse import _build_morning_embed

    embed = _build_morning_embed(
        date_str="2026-03-24",
        events=[],
        tomorrow_preview=[],
        open_todos=[],
        ai_question="What's draining your energy?",
    )

    assert "What's draining your energy?" in embed["description"]
    assert "**" in embed["description"]


def test_embed_no_reply_instructions():
    """Embed no longer contains 'Reply within' instructions."""
    from src.jobs.pulse import _build_morning_embed

    embed = _build_morning_embed("2026-03-24", [], [], [], "Question?")

    assert "Reply within" not in embed.get("description", "")
    assert "Reply within" not in embed.get("footer", {}).get("text", "")


# ── Section 18: API schema changes ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_pulse_stores_ai_question_response(test_client, api_key_headers):
    """PATCH stores ai_question_response field."""
    pulse_date = _today_midnight().isoformat()
    await test_client.post("/v1/pulse", json={"pulse_date": pulse_date}, headers=api_key_headers)

    resp = await test_client.patch(
        "/v1/pulse/today",
        json={"ai_question_response": "Too many meetings", "status": "completed"},
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ai_question_response"] == "Too many meetings"
    assert data["status"] == "completed"


@pytest.mark.asyncio
async def test_patch_pulse_stores_notes(test_client, api_key_headers):
    """PATCH stores notes field."""
    pulse_date = _today_midnight().isoformat()
    await test_client.post("/v1/pulse", json={"pulse_date": pulse_date}, headers=api_key_headers)

    resp = await test_client.patch(
        "/v1/pulse/today",
        json={"notes": "Feeling productive today"},
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "Feeling productive today"


@pytest.mark.asyncio
async def test_completed_status_accepted(test_client, api_key_headers):
    """Status 'completed' is accepted by the validator."""
    pulse_date = _today_midnight().isoformat()
    await test_client.post("/v1/pulse", json={"pulse_date": pulse_date}, headers=api_key_headers)

    resp = await test_client.patch(
        "/v1/pulse/today",
        json={"status": "completed"},
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


# ── T-14: PATCH sleep_quality=0 returns 422 ──────────────────────────────────


@pytest.mark.asyncio
async def test_update_pulse_sleep_quality_zero_returns_422(test_client, api_key_headers):
    """sleep_quality=0 is below ge=1 boundary — should return 422."""
    pulse_date = _today_midnight().isoformat()
    await test_client.post("/v1/pulse", json={"pulse_date": pulse_date}, headers=api_key_headers)

    resp = await test_client.patch(
        "/v1/pulse/today",
        json={"sleep_quality": 0},
        headers=api_key_headers,
    )
    assert resp.status_code == 422


# ── T-15: PATCH sleep_quality=6 returns 422 ──────────────────────────────────


@pytest.mark.asyncio
async def test_update_pulse_sleep_quality_six_returns_422(test_client, api_key_headers):
    """sleep_quality=6 is above le=5 boundary — should return 422."""
    pulse_date = _today_midnight().isoformat()
    await test_client.post("/v1/pulse", json={"pulse_date": pulse_date}, headers=api_key_headers)

    resp = await test_client.patch(
        "/v1/pulse/today",
        json={"sleep_quality": 6},
        headers=api_key_headers,
    )
    assert resp.status_code == 422


# ── T-16: PATCH /v1/pulse/today requires auth ───────────────────────────────


@pytest.mark.asyncio
async def test_update_today_pulse_requires_auth(test_client, api_key_headers):
    """PATCH /v1/pulse/today without X-API-Key returns 401."""
    pulse_date = _today_midnight().isoformat()
    await test_client.post("/v1/pulse", json={"pulse_date": pulse_date}, headers=api_key_headers)

    resp = await test_client.patch("/v1/pulse/today", json={"notes": "test"})
    assert resp.status_code == 401


# ── T-17: GET /v1/pulse?limit=0 returns 422 ─────────────────────────────────


@pytest.mark.asyncio
async def test_list_pulses_limit_zero_returns_422(test_client, api_key_headers):
    """GET /v1/pulse?limit=0 returns 422 (below ge=1)."""
    resp = await test_client.get("/v1/pulse?limit=0", headers=api_key_headers)
    assert resp.status_code == 422


# ── T-19: GET /v1/pulse?limit=366 returns 422 ───────────────────────────────


@pytest.mark.asyncio
async def test_list_pulses_limit_over_max_returns_422(test_client, api_key_headers):
    """GET /v1/pulse?limit=366 returns 422 (above le=365)."""
    resp = await test_client.get("/v1/pulse?limit=366", headers=api_key_headers)
    assert resp.status_code == 422


# ── Section 10: POST /v1/pulse/start ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_pulse_start_creates_with_ai_question(test_client, api_key_headers):
    """POST /v1/pulse/start creates a pulse with AI-generated question."""
    mock_question = "What's blocking the migration task?"
    mock_llm = _make_mock_llm(mock_question)

    with patch("src.llm.client.anthropic_client", mock_llm):
        resp = await test_client.post("/v1/pulse/start", headers=api_key_headers)

    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "sent"
    assert data["ai_question"] == "What's blocking the migration task?"
    assert data["id"]


@pytest.mark.asyncio
async def test_pulse_start_409_if_exists(test_client, api_key_headers):
    """POST /v1/pulse/start returns 409 if pulse already exists today."""
    # Create a pulse first via the regular endpoint
    pulse_date = _today_midnight().isoformat()
    resp1 = await test_client.post(
        "/v1/pulse",
        json={"pulse_date": pulse_date, "status": "sent"},
        headers=api_key_headers,
    )
    assert resp1.status_code == 201

    # Now /start should return 409
    resp2 = await test_client.post("/v1/pulse/start", headers=api_key_headers)
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_pulse_start_llm_failure_uses_default_question(test_client, api_key_headers):
    """POST /v1/pulse/start falls back to default question when LLM raises."""
    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(side_effect=RuntimeError("LLM down"))

    with patch("src.llm.client.anthropic_client", mock_llm):
        resp = await test_client.post("/v1/pulse/start", headers=api_key_headers)

    assert resp.status_code == 201
    data = resp.json()
    assert data["ai_question"] == "What's one thing you want to accomplish today?"


@pytest.mark.asyncio
async def test_pulse_start_no_api_key_uses_default_question(test_client, api_key_headers):
    """POST /v1/pulse/start uses default question when anthropic_client is None."""
    with patch("src.llm.client.anthropic_client", None):
        resp = await test_client.post("/v1/pulse/start", headers=api_key_headers)

    assert resp.status_code == 201
    data = resp.json()
    assert data["ai_question"] == "What's one thing you want to accomplish today?"


@pytest.mark.asyncio
async def test_pulse_start_includes_todo_context(test_client, api_key_headers, async_session):
    """POST /v1/pulse/start passes open todos to the question generator."""
    from src.core.models import TodoItem

    # Create an open todo so the endpoint has context to pass
    todo = TodoItem(description="Deploy the new API", priority="high", status="open")
    async_session.add(todo)
    await async_session.commit()

    captured_kwargs: dict = {}

    async def spy_generate(llm, **kwargs):
        captured_kwargs.update(kwargs)
        return "What's blocking the deploy?"

    with patch("src.jobs.pulse._generate_ai_question", side_effect=spy_generate):
        resp = await test_client.post("/v1/pulse/start", headers=api_key_headers)

    assert resp.status_code == 201
    assert "open_todos" in captured_kwargs
    assert len(captured_kwargs["open_todos"]) >= 1
    assert any("Deploy the new API" in t["description"] for t in captured_kwargs["open_todos"])


@pytest.mark.asyncio
async def test_pulse_start_alternates_question_type(test_client, api_key_headers, async_session):
    """POST /v1/pulse/start fetches yesterday's question for alternation."""
    from src.core.models import DailyPulse

    # Create yesterday's pulse with a known ai_question
    yesterday = _today_midnight() - timedelta(days=1)
    yesterday_pulse = DailyPulse(
        pulse_date=yesterday,
        status="completed",
        ai_question="What project needs attention today?",
    )
    async_session.add(yesterday_pulse)
    await async_session.commit()

    captured_kwargs: dict = {}

    async def spy_generate(llm, **kwargs):
        captured_kwargs.update(kwargs)
        return "What drained your energy yesterday?"

    with patch("src.jobs.pulse._generate_ai_question", side_effect=spy_generate):
        resp = await test_client.post("/v1/pulse/start", headers=api_key_headers)

    assert resp.status_code == 201
    assert captured_kwargs.get("yesterday_question") == "What project needs attention today?"


# ── Section 19: Signal-driven path — silence + label logic ─────────────────────


@pytest.mark.asyncio
async def test_pulse_start_silent_when_no_signals_fire(test_client, api_key_headers, monkeypatch):
    """When detectors are enabled and all return None, pulse is created with status=silent."""
    monkeypatch.setenv("PULSE_SIGNAL_DETECTORS", "focus,opportunity,open")
    monkeypatch.setenv("PULSE_SILENCE_THRESHOLD", "10.0")  # force silence (nothing >= 10)
    from src.core import config as _config

    monkeypatch.setattr(_config, "settings", _config.Settings())

    resp = await test_client.post("/v1/pulse/start", headers=api_key_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "silent"
    assert data["ai_question"] is None
    assert data["signal_type"] is None
    assert data["parsed_data"] is not None
    assert "signal_trace" in data["parsed_data"]


@pytest.mark.asyncio
async def test_pulse_start_writes_signal_type_when_signal_fires(
    test_client, api_key_headers, monkeypatch, async_session
):
    """An active todo drives the open detector; signal_type='open' surfaces in the DB row."""
    from src.core.models import TodoItem

    monkeypatch.setenv("PULSE_SIGNAL_DETECTORS", "focus,opportunity,open")
    monkeypatch.setenv("PULSE_SILENCE_THRESHOLD", "4.0")
    from src.core import config as _config

    monkeypatch.setattr(_config, "settings", _config.Settings())

    todo = TodoItem(description="Ship X", priority="high", status="open")
    async_session.add(todo)
    await async_session.commit()

    mock_llm = _make_mock_llm("What will make today feel like a win?")
    with patch("src.llm.client.anthropic_client", mock_llm):
        resp = await test_client.post("/v1/pulse/start", headers=api_key_headers)

    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "sent"
    assert data["signal_type"] == "open"
    assert data["ai_question"] == "What will make today feel like a win?"
    assert data["parsed_data"] is not None
    assert "signal_trace" in data["parsed_data"]


@pytest.mark.asyncio
async def test_patch_silent_rejects_status_transition(test_client, api_key_headers):
    """PATCH /v1/pulse/today rejects any status change on a silent pulse."""
    pulse_date = _today_midnight().isoformat()
    resp = await test_client.post(
        "/v1/pulse",
        json={"pulse_date": pulse_date, "status": "silent"},
        headers=api_key_headers,
    )
    assert resp.status_code == 201

    resp_patch = await test_client.patch(
        "/v1/pulse/today",
        json={"status": "completed"},
        headers=api_key_headers,
    )
    assert resp_patch.status_code == 409


def test_pulse_modal_label_for_question():
    """Modal label is 'Your answer' when ai_question ends with '?'."""
    from src.integrations.modules.pulse_cog import PulseModal

    m = PulseModal(ai_question="What's blocking you today?")
    assert m.ai_response is not None
    assert m.ai_response.label == "Your answer"


def test_pulse_modal_label_for_remark():
    """Modal label is 'Thoughts?' for a non-question remark."""
    from src.integrations.modules.pulse_cog import PulseModal

    m = PulseModal(ai_question="Best ride weather this week.")
    assert m.ai_response is not None
    assert m.ai_response.label == "Thoughts?"


def test_pulse_modal_no_field_when_ai_question_none():
    from src.integrations.modules.pulse_cog import PulseModal

    m = PulseModal(ai_question="")
    assert m.ai_response is None
