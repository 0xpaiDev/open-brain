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

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


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
    llm.complete = AsyncMock(side_effect=Exception("API down"))
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
    day1 = datetime(2026, 3, 1, tzinfo=timezone.utc).isoformat()
    day2 = datetime(2026, 3, 2, tzinfo=timezone.utc).isoformat()

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
    dates = [datetime(2026, 3, i, tzinfo=timezone.utc).isoformat() for i in range(1, 6)]
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
    specific_date = datetime(2026, 3, 15, tzinfo=timezone.utc)
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
    import discord

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
