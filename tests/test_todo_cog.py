"""Tests for the Todo Discord cog.

Covers parse_natural_date edge cases, slash command httpx calls, and
button callbacks. All httpx calls are mocked — no real API is hit.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.integrations.modules.todo_cog import (
    DoneButton,
    TodoGroup,
    parse_natural_date,
)


# ── parse_natural_date ────────────────────────────────────────────────────────


def test_parse_natural_date_tomorrow() -> None:
    today = date(2026, 3, 23)  # Monday
    assert parse_natural_date("@tomorrow", today) == date(2026, 3, 24)


def test_parse_natural_date_tomorrow_case_insensitive() -> None:
    today = date(2026, 3, 23)
    assert parse_natural_date("@Tomorrow", today) == date(2026, 3, 24)


def test_parse_natural_date_next_week() -> None:
    today = date(2026, 3, 23)  # Monday
    # next-week from Monday → Monday of the following week = 2026-03-30
    assert parse_natural_date("@next-week", today) == date(2026, 3, 30)


def test_parse_natural_date_next_week_from_mid_week() -> None:
    today = date(2026, 3, 25)  # Wednesday
    # next-week → next Monday = 2026-03-30
    assert parse_natural_date("@next-week", today) == date(2026, 3, 30)


def test_parse_natural_date_monday_from_monday_gives_next_monday() -> None:
    today = date(2026, 3, 23)  # Monday
    # @monday when today is Monday → next Monday (not today)
    assert parse_natural_date("@monday", today) == date(2026, 3, 30)


def test_parse_natural_date_friday_from_monday() -> None:
    today = date(2026, 3, 23)  # Monday
    assert parse_natural_date("@friday", today) == date(2026, 3, 27)


def test_parse_natural_date_sunday_from_monday() -> None:
    today = date(2026, 3, 23)  # Monday
    assert parse_natural_date("@sunday", today) == date(2026, 3, 29)


def test_parse_natural_date_iso() -> None:
    assert parse_natural_date("@2026-12-25", date.today()) == date(2026, 12, 25)


def test_parse_natural_date_invalid_token() -> None:
    assert parse_natural_date("@foo", date.today()) is None


def test_parse_natural_date_invalid_iso() -> None:
    assert parse_natural_date("@2026-99-99", date.today()) is None


def test_parse_natural_date_missing_prefix() -> None:
    assert parse_natural_date("tomorrow", date.today()) is None


def test_parse_natural_date_empty_string() -> None:
    assert parse_natural_date("", date.today()) is None


# ── Helpers ────────────────────────────────────────────────────────────────────


def _mock_response(status: int, body: dict | list) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = body
    resp.raise_for_status = MagicMock(
        side_effect=None
        if status < 400
        else httpx.HTTPStatusError(
            message=f"HTTP {status}",
            request=MagicMock(),
            response=resp,
        )
    )
    return resp


def _make_http(
    post_response: MagicMock | None = None,
    patch_response: MagicMock | None = None,
    get_response: MagicMock | None = None,
) -> AsyncMock:
    http = AsyncMock(spec=httpx.AsyncClient)
    if post_response is not None:
        http.post.return_value = post_response
    if patch_response is not None:
        http.patch.return_value = patch_response
    if get_response is not None:
        http.get.return_value = get_response
    return http


def _make_settings(allowed_ids: list[int] | None = None) -> MagicMock:
    return MagicMock(
        discord_allowed_user_ids=allowed_ids or [42],
        api_key="test-key",
        open_brain_api_url="http://localhost:8000",
    )


def _make_interaction(user_id: int = 42) -> MagicMock:
    interaction = MagicMock()
    interaction.user.id = user_id
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


# ── TodoGroup.add_todo ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_todo_add_calls_api(monkeypatch) -> None:
    """add_todo calls POST /v1/todos with correct payload."""
    todo_body = {
        "id": "aaaaaaaa-0000-0000-0000-000000000001",
        "description": "test todo",
        "priority": "normal",
        "status": "open",
        "due_date": None,
        "discord_message_id": None,
        "discord_channel_id": None,
        "created_at": "2026-03-23T07:00:00Z",
        "updated_at": "2026-03-23T07:00:00Z",
    }
    http = _make_http(post_response=_mock_response(201, todo_body))
    group = TodoGroup(http)

    interaction = _make_interaction(user_id=42)
    monkeypatch.setattr(
        "src.integrations.modules.todo_cog._get_settings",
        lambda: _make_settings(),
    )

    await group.add_todo.callback(group, interaction, text="test todo")

    http.post.assert_awaited_once()
    call_kwargs = http.post.call_args.kwargs
    assert call_kwargs["json"]["description"] == "test todo"
    assert call_kwargs["json"]["priority"] == "normal"


@pytest.mark.asyncio
async def test_todo_add_with_date(monkeypatch) -> None:
    """add_todo with @tomorrow includes due_date in the API call."""
    todo_body = {
        "id": "aaaaaaaa-0000-0000-0000-000000000002",
        "description": "dated",
        "priority": "normal",
        "status": "open",
        "due_date": "2026-03-24T00:00:00Z",
        "discord_message_id": None,
        "discord_channel_id": None,
        "created_at": "2026-03-23T07:00:00Z",
        "updated_at": "2026-03-23T07:00:00Z",
    }
    http = _make_http(post_response=_mock_response(201, todo_body))
    group = TodoGroup(http)
    interaction = _make_interaction()
    monkeypatch.setattr(
        "src.integrations.modules.todo_cog._get_settings",
        lambda: _make_settings(),
    )

    with patch("src.integrations.modules.todo_cog.date") as mock_date:
        mock_date.today.return_value = date(2026, 3, 23)
        await group.add_todo.callback(group, interaction, text="dated", due="@tomorrow")

    http.post.assert_awaited_once()
    call_kwargs = http.post.call_args.kwargs
    assert "2026-03-24" in call_kwargs["json"]["due_date"]


@pytest.mark.asyncio
async def test_todo_add_invalid_date(monkeypatch) -> None:
    """add_todo with unparseable date sends ephemeral error, no API call."""
    http = _make_http()
    group = TodoGroup(http)
    interaction = _make_interaction()
    monkeypatch.setattr(
        "src.integrations.modules.todo_cog._get_settings",
        lambda: _make_settings(),
    )

    await group.add_todo.callback(group, interaction, text="test", due="@invalid")

    http.post.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once()
    args = interaction.response.send_message.call_args
    assert "ephemeral" in args.kwargs and args.kwargs["ephemeral"] is True


# ── TodoGroup.done_todo ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_todo_done_calls_patch(monkeypatch) -> None:
    """done_todo calls PATCH /v1/todos/{id} with status=done."""
    todo_body = {
        "id": "aaaaaaaa-0000-0000-0000-000000000001",
        "description": "done now",
        "priority": "normal",
        "status": "done",
        "due_date": None,
        "discord_message_id": None,
        "discord_channel_id": None,
        "created_at": "2026-03-23T07:00:00Z",
        "updated_at": "2026-03-23T07:00:00Z",
    }
    http = _make_http(patch_response=_mock_response(200, todo_body))
    group = TodoGroup(http)
    interaction = _make_interaction()
    monkeypatch.setattr(
        "src.integrations.modules.todo_cog._get_settings",
        lambda: _make_settings(),
    )

    await group.done_todo.callback(group, interaction, todo_id="aaaaaaaa-0000-0000-0000-000000000001")

    http.patch.assert_awaited_once()
    call_kwargs = http.patch.call_args.kwargs
    assert call_kwargs["json"]["status"] == "done"


# ── Authorization ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_todo_add_unauthorized(monkeypatch) -> None:
    """add_todo from a non-whitelisted user sends ephemeral 'Not authorised.'"""
    http = _make_http()
    group = TodoGroup(http)
    interaction = _make_interaction(user_id=9999)
    monkeypatch.setattr(
        "src.integrations.modules.todo_cog._get_settings",
        lambda: _make_settings(allowed_ids=[42]),
    )

    await group.add_todo.callback(group, interaction, text="nope")

    http.post.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once_with("Not authorised.", ephemeral=True)


@pytest.mark.asyncio
async def test_todo_done_unauthorized(monkeypatch) -> None:
    """done_todo from a non-whitelisted user sends ephemeral 'Not authorised.'"""
    http = _make_http()
    group = TodoGroup(http)
    interaction = _make_interaction(user_id=9999)
    monkeypatch.setattr(
        "src.integrations.modules.todo_cog._get_settings",
        lambda: _make_settings(allowed_ids=[42]),
    )

    await group.done_todo.callback(group, interaction, todo_id="some-id")

    http.patch.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once_with("Not authorised.", ephemeral=True)


# ── DoneButton ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_done_button_calls_patch_and_edits_message(monkeypatch) -> None:
    """DoneButton.callback PATCHes the API and edits the original message."""
    todo_id = "aaaaaaaa-0000-0000-0000-000000000001"
    todo_body = {
        "id": todo_id,
        "description": "done",
        "priority": "normal",
        "status": "done",
        "due_date": None,
        "discord_message_id": None,
        "discord_channel_id": None,
        "created_at": "2026-03-23T07:00:00Z",
        "updated_at": "2026-03-23T07:00:00Z",
    }
    http = _make_http(patch_response=_mock_response(200, todo_body))
    button = DoneButton(todo_id, http)
    interaction = _make_interaction(user_id=42)
    monkeypatch.setattr(
        "src.integrations.modules.todo_cog._get_settings",
        lambda: _make_settings(),
    )

    await button.callback(interaction)

    http.patch.assert_awaited_once()
    interaction.response.edit_message.assert_awaited_once()
    call_kwargs = interaction.response.edit_message.call_args.kwargs
    assert call_kwargs.get("view") is None  # buttons removed


@pytest.mark.asyncio
async def test_done_button_api_error_sends_ephemeral(monkeypatch) -> None:
    """DoneButton sends ephemeral error message on API failure."""
    todo_id = "aaaaaaaa-0000-0000-0000-000000000001"
    http = _make_http(patch_response=_mock_response(500, {"detail": "error"}))
    button = DoneButton(todo_id, http)
    interaction = _make_interaction(user_id=42)
    monkeypatch.setattr(
        "src.integrations.modules.todo_cog._get_settings",
        lambda: _make_settings(),
    )

    await button.callback(interaction)

    interaction.response.edit_message.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once()
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True
