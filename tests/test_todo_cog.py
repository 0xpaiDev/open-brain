"""Tests for the Todo Discord cog.

Covers parse_natural_date, filter helpers, embed builder, slash commands,
button callbacks, and the on_message prefix listener.
All httpx calls are mocked — no real API is hit.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.integrations.modules.todo_cog import (
    DoneButton,
    DeferButton,
    TodoGroup,
    _build_tabbed_embed,
    _filter_today,
    _filter_week,
    _handle_todo_message,
    _parse_date_bare,
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


# ── _parse_date_bare ──────────────────────────────────────────────────────────


def test_parse_date_bare_tomorrow() -> None:
    today = date(2026, 3, 23)
    assert _parse_date_bare("tomorrow", today) == date(2026, 3, 24)


def test_parse_date_bare_friday() -> None:
    today = date(2026, 3, 23)  # Monday
    assert _parse_date_bare("friday", today) == date(2026, 3, 27)


def test_parse_date_bare_invalid() -> None:
    assert _parse_date_bare("someday", date.today()) is None


def test_parse_date_bare_iso() -> None:
    today = date(2026, 3, 23)
    assert _parse_date_bare("2026-12-25", today) == date(2026, 12, 25)


# ── _filter_today ─────────────────────────────────────────────────────────────


def _make_todo(
    todo_id: str = "aaa",
    description: str = "test",
    due_date: str | None = None,
    priority: str = "normal",
    status: str = "open",
) -> dict:
    return {
        "id": todo_id,
        "description": description,
        "priority": priority,
        "status": status,
        "due_date": due_date,
        "created_at": "2026-03-20T07:00:00Z",
        "updated_at": "2026-03-20T07:00:00Z",
        "discord_message_id": None,
        "discord_channel_id": None,
    }


def test_filter_today_includes_no_due_date() -> None:
    today = date(2026, 3, 23)
    todos = [_make_todo("1", "no due")]
    assert _filter_today(todos, today) == todos


def test_filter_today_includes_due_today() -> None:
    today = date(2026, 3, 23)
    todos = [_make_todo("1", "due today", due_date="2026-03-23T00:00:00Z")]
    assert _filter_today(todos, today) == todos


def test_filter_today_includes_overdue() -> None:
    today = date(2026, 3, 23)
    todos = [_make_todo("1", "overdue", due_date="2026-03-20T00:00:00Z")]
    assert _filter_today(todos, today) == todos


def test_filter_today_excludes_future() -> None:
    today = date(2026, 3, 23)
    todos = [_make_todo("1", "future", due_date="2026-03-30T00:00:00Z")]
    assert _filter_today(todos, today) == []


def test_filter_today_mixed() -> None:
    today = date(2026, 3, 23)  # Monday
    todos = [
        _make_todo("1", "no due"),
        _make_todo("2", "today", due_date="2026-03-23T00:00:00Z"),
        _make_todo("3", "past", due_date="2026-03-20T00:00:00Z"),
        _make_todo("4", "future", due_date="2026-03-30T00:00:00Z"),
    ]
    result = _filter_today(todos, today)
    ids = [t["id"] for t in result]
    assert ids == ["1", "2", "3"]


# ── _filter_week ──────────────────────────────────────────────────────────────


def test_filter_week_includes_no_due_date() -> None:
    today = date(2026, 3, 23)  # Monday
    todos = [_make_todo("1", "no due")]
    assert _filter_week(todos, today) == todos


def test_filter_week_includes_this_week() -> None:
    today = date(2026, 3, 23)  # Monday; week ends Sunday 2026-03-29
    todos = [_make_todo("1", "friday", due_date="2026-03-27T00:00:00Z")]
    assert _filter_week(todos, today) == todos


def test_filter_week_includes_end_of_week() -> None:
    today = date(2026, 3, 23)  # Monday
    todos = [_make_todo("1", "sunday", due_date="2026-03-29T00:00:00Z")]
    assert _filter_week(todos, today) == todos


def test_filter_week_excludes_next_week() -> None:
    today = date(2026, 3, 23)  # Monday; next week starts 2026-03-30
    todos = [_make_todo("1", "next monday", due_date="2026-03-30T00:00:00Z")]
    assert _filter_week(todos, today) == []


def test_filter_week_includes_overdue() -> None:
    today = date(2026, 3, 23)  # Monday
    todos = [_make_todo("1", "overdue", due_date="2026-03-10T00:00:00Z")]
    assert _filter_week(todos, today) == todos


# ── _build_tabbed_embed ───────────────────────────────────────────────────────


def test_build_tabbed_embed_today_title() -> None:
    today = date(2026, 3, 23)
    todos = [_make_todo("1", "Task A")]
    embed = _build_tabbed_embed(todos, "today", 0, 1, today)
    assert embed.title == "Today"


def test_build_tabbed_embed_week_title() -> None:
    today = date(2026, 3, 23)
    embed = _build_tabbed_embed([], "week", 0, 0, today)
    assert embed.title == "This Week"


def test_build_tabbed_embed_all_title() -> None:
    today = date(2026, 3, 23)
    embed = _build_tabbed_embed([], "all", 0, 0, today)
    assert embed.title == "All Todos"


def test_build_tabbed_embed_empty_today() -> None:
    today = date(2026, 3, 23)
    embed = _build_tabbed_embed([], "today", 0, 0, today)
    assert "Nothing due today" in embed.description


def test_build_tabbed_embed_empty_week() -> None:
    today = date(2026, 3, 23)
    embed = _build_tabbed_embed([], "week", 0, 0, today)
    assert "Clear week ahead" in embed.description


def test_build_tabbed_embed_empty_all() -> None:
    today = date(2026, 3, 23)
    embed = _build_tabbed_embed([], "all", 0, 0, today)
    assert "No active todos" in embed.description


def test_build_tabbed_embed_shows_field_per_todo() -> None:
    today = date(2026, 3, 23)
    todos = [_make_todo("1", "Task A"), _make_todo("2", "Task B")]
    embed = _build_tabbed_embed(todos, "today", 0, 2, today)
    assert len(embed.fields) == 2


def test_build_tabbed_embed_field_names_include_index() -> None:
    today = date(2026, 3, 23)
    todos = [_make_todo("1", "Task A")]
    embed = _build_tabbed_embed(todos, "today", 0, 1, today)
    assert "[1]" in embed.fields[0].name


def test_build_tabbed_embed_overdue_shows_warning() -> None:
    today = date(2026, 3, 23)
    todos = [_make_todo("1", "Overdue task", due_date="2026-03-20T00:00:00Z")]
    embed = _build_tabbed_embed(todos, "today", 0, 1, today)
    assert "⚠️" in embed.fields[0].value


def test_build_tabbed_embed_not_overdue_no_warning() -> None:
    today = date(2026, 3, 23)
    todos = [_make_todo("1", "Today task", due_date="2026-03-23T00:00:00Z")]
    embed = _build_tabbed_embed(todos, "today", 0, 1, today)
    assert "⚠️" not in embed.fields[0].value


def test_build_tabbed_embed_pagination_footer() -> None:
    today = date(2026, 3, 23)
    # 6 total todos, page 0 shows 5
    todos = [_make_todo(str(i), f"Task {i}") for i in range(5)]
    embed = _build_tabbed_embed(todos, "all", 0, 6, today)
    assert "Page 1/2" in embed.footer.text


def test_build_tabbed_embed_single_page_no_page_number() -> None:
    today = date(2026, 3, 23)
    todos = [_make_todo("1", "Task A")]
    embed = _build_tabbed_embed(todos, "today", 0, 1, today)
    assert "Page" not in embed.footer.text


def test_build_tabbed_embed_footer_has_expiry_note() -> None:
    today = date(2026, 3, 23)
    todos = [_make_todo("1", "Task A")]
    embed = _build_tabbed_embed(todos, "today", 0, 1, today)
    assert "15 min" in embed.footer.text


def test_build_tabbed_embed_page_2_shows_correct_todos() -> None:
    today = date(2026, 3, 23)
    todos = [_make_todo(str(i), f"Task {i}") for i in range(7)]
    # page 1 should show todos at index 5-6 (0-based)
    embed = _build_tabbed_embed(todos, "all", 1, 7, today)
    assert len(embed.fields) == 2  # only 2 remaining
    assert "[6]" in embed.fields[0].name


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


def _make_settings(
    allowed_ids: list[int] | None = None,
    todo_channel_id: int = 0,
) -> MagicMock:
    api_key_mock = MagicMock()
    api_key_mock.get_secret_value.return_value = "test-key"
    return MagicMock(
        discord_allowed_user_ids=allowed_ids or [42],
        api_key=api_key_mock,
        open_brain_api_url="http://localhost:8000",
        discord_todo_channel_id=todo_channel_id,
    )


def _make_interaction(user_id: int = 42) -> MagicMock:
    interaction = MagicMock()
    interaction.user.id = user_id
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _make_message(content: str, channel_id: int = 100, author_id: int = 42) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.channel.id = channel_id
    msg.author.id = author_id
    msg.add_reaction = AsyncMock()
    msg.reply = AsyncMock()
    return msg


def _make_todo_list_response(todos: list[dict]) -> MagicMock:
    return _mock_response(200, {"todos": todos, "total": len(todos)})


# ── TodoGroup.add_todo ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_todo_add_calls_api(monkeypatch) -> None:
    """add_todo calls POST /v1/todos with correct payload."""
    todo_body = _make_todo("aaaaaaaa-0000-0000-0000-000000000001", "test todo")
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
    todo_body = _make_todo("aaaaaaaa-0000-0000-0000-000000000002", "dated",
                           due_date="2026-03-24T00:00:00Z")
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
    todo_body = _make_todo("aaaaaaaa-0000-0000-0000-000000000001", "done now", status="done")
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
    """DoneButton.callback PATCHes the API and edits the original message with fresh embed."""
    todo_id = "aaaaaaaa-0000-0000-0000-000000000001"
    todo_body = _make_todo(todo_id, "done", status="done")
    # patch returns done todo; get returns empty list (todo is now gone)
    http = _make_http(
        patch_response=_mock_response(200, todo_body),
        get_response=_make_todo_list_response([]),
    )
    button = DoneButton(1, todo_id, http, "today", date(2026, 3, 23), row=1)
    interaction = _make_interaction(user_id=42)
    monkeypatch.setattr(
        "src.integrations.modules.todo_cog._get_settings",
        lambda: _make_settings(),
    )

    await button.callback(interaction)

    http.patch.assert_awaited_once()
    interaction.response.edit_message.assert_awaited_once()
    # embed and view should be passed (not content only)
    call_kwargs = interaction.response.edit_message.call_args.kwargs
    assert "embed" in call_kwargs
    assert "view" in call_kwargs


@pytest.mark.asyncio
async def test_done_button_api_error_sends_ephemeral(monkeypatch) -> None:
    """DoneButton sends ephemeral error message on API failure."""
    todo_id = "aaaaaaaa-0000-0000-0000-000000000001"
    http = _make_http(patch_response=_mock_response(500, {"detail": "error"}))
    button = DoneButton(1, todo_id, http, "today", date(2026, 3, 23), row=1)
    interaction = _make_interaction(user_id=42)
    monkeypatch.setattr(
        "src.integrations.modules.todo_cog._get_settings",
        lambda: _make_settings(),
    )

    await button.callback(interaction)

    interaction.response.edit_message.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once()
    assert interaction.response.send_message.call_args.kwargs.get("ephemeral") is True


# ── on_message prefix listener ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prefix_add(monkeypatch) -> None:
    """'+ task text' calls POST /v1/todos and reacts ✅."""
    todo_body = _make_todo("aaa", "fix DNS")
    http = _make_http(post_response=_mock_response(201, todo_body))
    settings = _make_settings()
    message = _make_message("+ fix DNS")

    monkeypatch.setattr("src.integrations.modules.todo_cog._get_settings", lambda: settings)

    await _handle_todo_message(message, http, settings)

    http.post.assert_awaited_once()
    call_kwargs = http.post.call_args.kwargs
    assert call_kwargs["json"]["description"] == "fix DNS"
    message.add_reaction.assert_awaited_once_with("✅")
    message.reply.assert_awaited_once()
    reply_text = message.reply.call_args.args[0]
    assert "✓ Added" in reply_text


@pytest.mark.asyncio
async def test_prefix_add_with_date(monkeypatch) -> None:
    """'+ task @friday' extracts the date and creates todo with due_date."""
    todo_body = _make_todo("aaa", "fix DNS", due_date="2026-03-27T00:00:00Z")
    http = _make_http(post_response=_mock_response(201, todo_body))
    settings = _make_settings()
    message = _make_message("+ fix DNS @friday")

    with patch("src.integrations.modules.todo_cog.date") as mock_date:
        mock_date.today.return_value = date(2026, 3, 23)  # Monday
        await _handle_todo_message(message, http, settings)

    http.post.assert_awaited_once()
    call_kwargs = http.post.call_args.kwargs
    assert "2026-03-27" in call_kwargs["json"]["due_date"]
    assert call_kwargs["json"]["description"] == "fix DNS"


@pytest.mark.asyncio
async def test_prefix_done_single(monkeypatch) -> None:
    """'done 1' marks the first today-todo as done."""
    todo1 = _make_todo("id-1", "First task")
    todo2 = _make_todo("id-2", "Second task")
    http = _make_http(
        patch_response=_mock_response(200, {**todo1, "status": "done"}),
        get_response=_make_todo_list_response([todo1, todo2]),
    )
    settings = _make_settings()
    message = _make_message("done 1")

    with patch("src.integrations.modules.todo_cog.date") as mock_date:
        mock_date.today.return_value = date(2026, 3, 23)
        await _handle_todo_message(message, http, settings)

    http.patch.assert_awaited_once()
    patch_url = http.patch.call_args.args[0]
    assert "id-1" in patch_url
    message.add_reaction.assert_awaited_once_with("✅")
    reply_text = message.reply.call_args.args[0]
    assert "First task" in reply_text


@pytest.mark.asyncio
async def test_prefix_done_multiple(monkeypatch) -> None:
    """'done 1,3' marks todos at indices 1 and 3 done."""
    todos = [
        _make_todo("id-1", "Task 1"),
        _make_todo("id-2", "Task 2"),
        _make_todo("id-3", "Task 3"),
    ]
    http = _make_http(
        patch_response=_mock_response(200, {**todos[0], "status": "done"}),
        get_response=_make_todo_list_response(todos),
    )
    settings = _make_settings()
    message = _make_message("done 1,3")

    with patch("src.integrations.modules.todo_cog.date") as mock_date:
        mock_date.today.return_value = date(2026, 3, 23)
        await _handle_todo_message(message, http, settings)

    assert http.patch.await_count == 2
    patched_urls = [call.args[0] for call in http.patch.await_args_list]
    assert any("id-1" in url for url in patched_urls)
    assert any("id-3" in url for url in patched_urls)


@pytest.mark.asyncio
async def test_prefix_done_all(monkeypatch) -> None:
    """'done all' marks all of today's todos done."""
    todos = [
        _make_todo("id-1", "Task 1"),
        _make_todo("id-2", "Task 2"),
    ]
    http = _make_http(
        patch_response=_mock_response(200, {**todos[0], "status": "done"}),
        get_response=_make_todo_list_response(todos),
    )
    settings = _make_settings()
    message = _make_message("done all")

    with patch("src.integrations.modules.todo_cog.date") as mock_date:
        mock_date.today.return_value = date(2026, 3, 23)
        await _handle_todo_message(message, http, settings)

    assert http.patch.await_count == 2
    message.add_reaction.assert_awaited_once_with("✅")


@pytest.mark.asyncio
async def test_prefix_defer(monkeypatch) -> None:
    """'defer 2 tomorrow low energy' defers the correct todo with reason."""
    todo1 = _make_todo("id-1", "Task 1")
    todo2 = _make_todo("id-2", "Task 2")
    http = _make_http(
        patch_response=_mock_response(200, {**todo2, "due_date": "2026-03-24T00:00:00Z"}),
        get_response=_make_todo_list_response([todo1, todo2]),
    )
    settings = _make_settings()
    message = _make_message("defer 2 tomorrow low energy")

    with patch("src.integrations.modules.todo_cog.date") as mock_date:
        mock_date.today.return_value = date(2026, 3, 23)
        await _handle_todo_message(message, http, settings)

    http.patch.assert_awaited_once()
    patch_url = http.patch.call_args.args[0]
    assert "id-2" in patch_url
    patch_body = http.patch.call_args.kwargs["json"]
    assert "2026-03-24" in patch_body["due_date"]
    assert patch_body.get("reason") == "low energy"
    message.add_reaction.assert_awaited_once_with("✅")
    reply_text = message.reply.call_args.args[0]
    assert "Task 2" in reply_text
    assert "low energy" in reply_text


@pytest.mark.asyncio
async def test_prefix_parse_failure(monkeypatch) -> None:
    """Unrecognised input replies with help hint and makes no API call."""
    http = _make_http()
    settings = _make_settings()
    message = _make_message("what is going on")

    await _handle_todo_message(message, http, settings)

    http.post.assert_not_awaited()
    http.patch.assert_not_awaited()
    message.reply.assert_awaited_once()
    hint = message.reply.call_args.args[0]
    assert "+ task text" in hint or "Didn't catch" in hint


@pytest.mark.asyncio
async def test_prefix_empty_plus(monkeypatch) -> None:
    """'+ ' with no text replies with hint, no API call."""
    http = _make_http()
    settings = _make_settings()
    message = _make_message("+")

    await _handle_todo_message(message, http, settings)

    http.post.assert_not_awaited()
    message.reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_prefix_done_out_of_range(monkeypatch) -> None:
    """'done 5' when only 2 todos exist replies with no-match message."""
    todos = [_make_todo("id-1", "Task 1"), _make_todo("id-2", "Task 2")]
    http = _make_http(get_response=_make_todo_list_response(todos))
    settings = _make_settings()
    message = _make_message("done 5")

    with patch("src.integrations.modules.todo_cog.date") as mock_date:
        mock_date.today.return_value = date(2026, 3, 23)
        await _handle_todo_message(message, http, settings)

    http.patch.assert_not_awaited()
    message.reply.assert_awaited_once()
    reply_text = message.reply.call_args.args[0]
    assert "No matching" in reply_text or "matching" in reply_text.lower()


@pytest.mark.asyncio
async def test_prefix_defer_bad_date(monkeypatch) -> None:
    """'defer 1 someday' with unparseable date replies with date error hint."""
    todos = [_make_todo("id-1", "Task 1")]
    http = _make_http(get_response=_make_todo_list_response(todos))
    settings = _make_settings()
    message = _make_message("defer 1 someday")

    with patch("src.integrations.modules.todo_cog.date") as mock_date:
        mock_date.today.return_value = date(2026, 3, 23)
        await _handle_todo_message(message, http, settings)

    http.patch.assert_not_awaited()
    message.reply.assert_awaited_once()
    reply_text = message.reply.call_args.args[0]
    assert "parse" in reply_text.lower() or "date" in reply_text.lower()
