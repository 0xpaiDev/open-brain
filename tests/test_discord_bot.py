"""Tests for the Discord bot integration.

Tests cover the pure business-logic helpers (ingest_memory, search_memories,
get_api_health) and the bot's on_message handler. Discord objects are mocked
so no real Discord connection is required. httpx.AsyncClient is always mocked
— we never hit the real API in tests.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.integrations.discord_bot import (
    get_api_health,
    ingest_memory,
    search_memories,
    trigger_digest,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────


def _mock_response(status: int, body: dict | list) -> MagicMock:
    """Build a fake httpx.Response."""
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


def _make_http(post_response: MagicMock | None = None, get_response: MagicMock | None = None) -> AsyncMock:
    """Create a mock httpx.AsyncClient."""
    http = AsyncMock(spec=httpx.AsyncClient)
    if post_response is not None:
        http.post.return_value = post_response
    if get_response is not None:
        http.get.return_value = get_response
    return http


# ── ingest_memory ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_memory_returns_raw_id_and_status() -> None:
    """Successful ingest returns (raw_id, status) tuple from the API response."""
    raw_id = "aaaaaaaa-0000-0000-0000-000000000001"
    http = _make_http(post_response=_mock_response(202, {"raw_id": raw_id, "status": "queued"}))

    result_id, result_status = await ingest_memory(
        http, "some memory", "123", "456", "test-key", "http://localhost:8000"
    )

    assert result_id == raw_id
    assert result_status == "queued"
    http.post.assert_awaited_once()
    call_kwargs = http.post.call_args
    assert call_kwargs[1]["json"]["source"] == "discord"
    assert call_kwargs[1]["json"]["text"] == "some memory"
    assert call_kwargs[1]["json"]["metadata"]["author_id"] == "123"
    assert call_kwargs[1]["headers"]["X-API-Key"] == "test-key"


@pytest.mark.asyncio
async def test_ingest_memory_returns_duplicate_status() -> None:
    """Duplicate content returns status='duplicate' in the tuple."""
    raw_id = "aaaaaaaa-0000-0000-0000-000000000002"
    http = _make_http(post_response=_mock_response(202, {"raw_id": raw_id, "status": "duplicate"}))

    result_id, result_status = await ingest_memory(
        http, "some memory", "123", "456", "test-key", "http://localhost:8000"
    )

    assert result_id == raw_id
    assert result_status == "duplicate"


@pytest.mark.asyncio
async def test_ingest_memory_raises_on_4xx() -> None:
    """HTTP 4xx from API propagates as HTTPStatusError."""
    http = _make_http(post_response=_mock_response(422, {"detail": "bad input"}))

    with pytest.raises(httpx.HTTPStatusError):
        await ingest_memory(http, "bad", "1", "2", "key", "http://localhost:8000")


@pytest.mark.asyncio
async def test_ingest_memory_raises_on_401() -> None:
    """Wrong API key returns 401, propagates as HTTPStatusError."""
    http = _make_http(post_response=_mock_response(401, {"detail": "Unauthorized"}))

    with pytest.raises(httpx.HTTPStatusError):
        await ingest_memory(http, "text", "1", "2", "wrong-key", "http://localhost:8000")


# ── search_memories ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_memories_returns_results() -> None:
    """Search returns the list from the API response."""
    items = [
        {"id": "aaa", "content": "memory one", "score": 0.9},
        {"id": "bbb", "content": "memory two", "score": 0.7},
    ]
    http = _make_http(get_response=_mock_response(200, items))

    results = await search_memories(http, "memory", 5, "key", "http://localhost:8000")

    assert results == items
    call_kwargs = http.get.call_args
    assert call_kwargs[1]["params"]["q"] == "memory"
    assert call_kwargs[1]["params"]["limit"] == 5


@pytest.mark.asyncio
async def test_search_memories_returns_empty_list() -> None:
    """Empty results are returned as an empty list without error."""
    http = _make_http(get_response=_mock_response(200, []))

    results = await search_memories(http, "nothing", 5, "key", "http://localhost:8000")

    assert results == []


@pytest.mark.asyncio
async def test_search_memories_raises_on_500() -> None:
    """Server error propagates as HTTPStatusError."""
    http = _make_http(get_response=_mock_response(500, {"detail": "Internal Error"}))

    with pytest.raises(httpx.HTTPStatusError):
        await search_memories(http, "q", 5, "key", "http://localhost:8000")


# ── get_api_health ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_api_health_returns_true_on_200() -> None:
    """Returns True when /ready responds 200."""
    http = _make_http(get_response=_mock_response(200, {"status": "ok"}))

    result = await get_api_health(http, "http://localhost:8000")

    assert result is True


@pytest.mark.asyncio
async def test_get_api_health_returns_false_on_503() -> None:
    """Returns False when /ready responds 503 (DB not ready)."""
    http = _make_http(get_response=_mock_response(503, {"status": "not ready"}))

    result = await get_api_health(http, "http://localhost:8000")

    assert result is False


@pytest.mark.asyncio
async def test_get_api_health_returns_false_on_connection_error() -> None:
    """Returns False when the API is unreachable."""
    http = AsyncMock(spec=httpx.AsyncClient)
    http.get.side_effect = httpx.ConnectError("connection refused")

    result = await get_api_health(http, "http://localhost:8000")

    assert result is False


# ── on_message handler (bot behaviour) ────────────────────────────────────────


def _make_discord_message(
    author_id: int,
    content: str,
    is_bot: bool = False,
    channel_id: int = 999,
) -> MagicMock:
    """Build a minimal discord.Message mock."""
    message = MagicMock()
    message.content = content
    message.author.id = author_id
    message.author.__eq__ = lambda self, other: is_bot  # True only when author == bot.user
    message.channel.id = channel_id
    message.add_reaction = AsyncMock()
    return message


def _make_settings(allowed_ids: list[int] = None, api_key: str = "test-key") -> MagicMock:
    """Build a minimal settings mock for on_message handler tests."""
    api_key_mock = MagicMock()
    api_key_mock.get_secret_value.return_value = api_key
    return MagicMock(
        discord_allowed_user_ids=allowed_ids or [42],
        api_key=api_key_mock,
        open_brain_api_url="http://localhost:8000",
        discord_todo_channel_id=0,
        module_todo_enabled=False,
    )


@pytest.mark.asyncio
async def test_on_message_allowed_user_ingests_memory(monkeypatch) -> None:
    """Allowed user message → ingest_memory called → 🧠 reaction added."""
    http = _make_http(post_response=_mock_response(202, {"raw_id": "aaa", "status": "queued"}))

    from src.integrations import discord_bot

    monkeypatch.setattr(discord_bot, "_get_settings", lambda: _make_settings())

    bot = discord_bot.OpenBrainBot(http)
    # bot.user is None (not connected) — message.author is a MagicMock, so != None
    message = _make_discord_message(author_id=42, content="remember this thought")
    await bot.on_message(message)

    http.post.assert_awaited_once()
    message.add_reaction.assert_awaited_once_with("🧠")


@pytest.mark.asyncio
async def test_on_message_duplicate_reacts_with_recycle(monkeypatch) -> None:
    """Duplicate message (same content within 24h) → ♻️ reaction instead of 🧠."""
    http = _make_http(post_response=_mock_response(202, {"raw_id": "bbb", "status": "duplicate"}))

    from src.integrations import discord_bot

    monkeypatch.setattr(discord_bot, "_get_settings", lambda: _make_settings())

    bot = discord_bot.OpenBrainBot(http)
    message = _make_discord_message(author_id=42, content="already sent this")
    await bot.on_message(message)

    http.post.assert_awaited_once()
    message.add_reaction.assert_awaited_once_with("♻️")


@pytest.mark.asyncio
async def test_on_message_unauthorized_user_ignored(monkeypatch) -> None:
    """Message from an unknown user ID is silently ignored — no ingest call."""
    http = _make_http()

    from src.integrations import discord_bot

    monkeypatch.setattr(discord_bot, "_get_settings", lambda: _make_settings(allowed_ids=[42]))

    bot = discord_bot.OpenBrainBot(http)
    message = _make_discord_message(author_id=9999, content="not allowed")
    await bot.on_message(message)

    http.post.assert_not_awaited()
    message.add_reaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_bot_own_message_ignored(monkeypatch) -> None:
    """Bot must not react to its own messages (prevents loops).

    When the bot is not connected, self.user is None. Setting message.author = None
    makes the equality check (message.author == self.user) → (None == None) → True,
    causing early return before any ingest attempt.
    """
    http = _make_http()

    from src.integrations import discord_bot

    monkeypatch.setattr(discord_bot, "_get_settings", lambda: _make_settings())

    bot = discord_bot.OpenBrainBot(http)
    # self.user is None — make message.author also None so equality holds
    message = MagicMock()
    message.author = None
    message.add_reaction = AsyncMock()

    await bot.on_message(message)

    http.post.assert_not_awaited()
    message.add_reaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_empty_content_ignored(monkeypatch) -> None:
    """Messages with no text content (e.g. image-only) are silently skipped."""
    http = _make_http()

    from src.integrations import discord_bot

    monkeypatch.setattr(discord_bot, "_get_settings", lambda: _make_settings())

    bot = discord_bot.OpenBrainBot(http)
    message = _make_discord_message(author_id=42, content="   ")
    await bot.on_message(message)

    http.post.assert_not_awaited()
    message.add_reaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_api_error_reacts_with_x(monkeypatch) -> None:
    """When the API returns an error, the bot reacts with ❌ instead of 🧠."""
    http = _make_http(post_response=_mock_response(500, {"detail": "server error"}))

    from src.integrations import discord_bot

    monkeypatch.setattr(discord_bot, "_get_settings", lambda: _make_settings())

    bot = discord_bot.OpenBrainBot(http)
    message = _make_discord_message(author_id=42, content="some memory")
    await bot.on_message(message)

    message.add_reaction.assert_awaited_once_with("❌")


# ── trigger_digest ─────────────────────────────────────────────────────────────


_SYNTHESIS_RESPONSE = {
    "synthesis_id": "abc12345-0000-0000-0000-000000000000",
    "memory_count": 5,
    "date_from": "2026-03-08",
    "date_to": "2026-03-15",
    "skipped": False,
    "message": "Synthesis complete",
}


@pytest.mark.asyncio
async def test_trigger_digest_returns_response() -> None:
    """Successful call returns the synthesis response dict."""
    http = _make_http(post_response=_mock_response(200, _SYNTHESIS_RESPONSE))

    result = await trigger_digest(http, days=7, api_key="test-key", api_base_url="http://localhost:8000")

    assert result["memory_count"] == 5
    assert result["skipped"] is False
    assert result["synthesis_id"] == "abc12345-0000-0000-0000-000000000000"


@pytest.mark.asyncio
async def test_trigger_digest_raises_on_non_200() -> None:
    """Non-2xx response raises httpx.HTTPStatusError."""
    http = _make_http(post_response=_mock_response(500, {"detail": "server error"}))

    with pytest.raises(httpx.HTTPStatusError):
        await trigger_digest(http, days=7, api_key="test-key", api_base_url="http://localhost:8000")


@pytest.mark.asyncio
async def test_trigger_digest_handles_skipped() -> None:
    """Skipped synthesis (no memories in window) returns skipped=True."""
    skipped_response = {**_SYNTHESIS_RESPONSE, "skipped": True, "synthesis_id": None, "memory_count": 0}
    http = _make_http(post_response=_mock_response(200, skipped_response))

    result = await trigger_digest(http, days=7, api_key="test-key", api_base_url="http://localhost:8000")

    assert result["skipped"] is True
    assert result["synthesis_id"] is None


@pytest.mark.asyncio
async def test_trigger_digest_sends_correct_days_param() -> None:
    """The days parameter is forwarded correctly in the JSON body."""
    http = _make_http(post_response=_mock_response(200, _SYNTHESIS_RESPONSE))

    await trigger_digest(http, days=14, api_key="test-key", api_base_url="http://localhost:8000")

    http.post.assert_awaited_once()
    call_kwargs = http.post.call_args.kwargs
    assert call_kwargs["json"]["days"] == 14
