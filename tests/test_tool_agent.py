"""Tests for AnthropicClient._messages_create and the tool-use loop."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_messages_create_returns_message_object(set_test_env):
    from src.llm.client import AnthropicClient

    fake_response = MagicMock()
    fake_response.stop_reason = "end_turn"
    fake_response.content = [MagicMock(type="text", text="Hello")]

    with patch("src.llm.client.Anthropic") as MockAnthropic:
        instance = MockAnthropic.return_value
        instance.messages.create.return_value = fake_response

        client = AnthropicClient(api_key="test-key", model="claude-haiku-4-5-20251001")
        result = await client._messages_create(
            messages=[{"role": "user", "content": "hello"}],
            system="You are helpful.",
            tools=[],
            model="claude-sonnet-4-6",
            max_tokens=100,
        )

    assert result.stop_reason == "end_turn"
    assert result.content[0].text == "Hello"


# ── Tool-use loop tests ───────────────────────────────────────────────────────


def _make_mock_client(side_effect=None, return_value=None):
    """Build a mock AnthropicClient with _messages_create patched."""
    mock_client = MagicMock()
    if side_effect is not None:
        mock_client._messages_create = AsyncMock(side_effect=side_effect)
    else:
        mock_client._messages_create = AsyncMock(return_value=return_value)
    return mock_client


@pytest.mark.asyncio
async def test_tool_loop_end_turn_on_first_call(async_session, set_test_env):
    from src.llm.tool_agent import ToolError, run_tool_loop

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "I can help with that."

    fake_response = MagicMock()
    fake_response.stop_reason = "end_turn"
    fake_response.content = [text_block]

    async def fake_dispatch(tool_name, args, session, user_id):
        raise ToolError("should not be called")

    mock_client = _make_mock_client(return_value=fake_response)
    result = await run_tool_loop(
        client=mock_client,
        system_prompt="You are helpful.",
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        model="claude-sonnet-4-6",
        max_tokens=100,
        session=async_session,
        user_id=uuid.UUID(int=0),
        dispatch=fake_dispatch,
        user_message="hello",
        tools_enabled=True,
        intent_tool=None,
        intent_method="none",
    )

    assert result == "I can help with that."


@pytest.mark.asyncio
async def test_tool_loop_dispatches_tool_call(async_session, set_test_env):
    from src.llm.tool_agent import run_tool_loop

    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.id = "tu_123"
    tool_use_block.name = "list_todos"
    tool_use_block.input = {}

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "You have 3 todos."

    resp1 = MagicMock()
    resp1.stop_reason = "tool_use"
    resp1.content = [tool_use_block]

    resp2 = MagicMock()
    resp2.stop_reason = "end_turn"
    resp2.content = [text_block]

    dispatch_calls = []

    async def fake_dispatch(tool_name, args, session, user_id):
        dispatch_calls.append(tool_name)
        return '[{"id": "abc", "description": "Buy milk"}]'

    mock_client = _make_mock_client(side_effect=[resp1, resp2])
    result = await run_tool_loop(
        client=mock_client,
        system_prompt="You are helpful.",
        messages=[{"role": "user", "content": "list my todos"}],
        tools=[],
        model="claude-sonnet-4-6",
        max_tokens=100,
        session=async_session,
        user_id=uuid.UUID(int=0),
        dispatch=fake_dispatch,
        user_message="list my todos",
        tools_enabled=True,
        intent_tool="list_todos",
        intent_method="regex",
    )

    assert result == "You have 3 todos."
    assert dispatch_calls == ["list_todos"]


@pytest.mark.asyncio
async def test_tool_loop_cap(async_session, set_test_env):
    from src.llm.tool_agent import MAX_ITERATIONS, run_tool_loop

    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.id = "tu_loop"
    tool_use_block.name = "list_todos"
    tool_use_block.input = {}

    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.content = [tool_use_block]

    async def fake_dispatch(tool_name, args, session, user_id):
        return "[]"

    mock_client = _make_mock_client(return_value=resp)
    result = await run_tool_loop(
        client=mock_client,
        system_prompt="",
        messages=[{"role": "user", "content": "loop forever"}],
        tools=[],
        model="claude-sonnet-4-6",
        max_tokens=100,
        session=async_session,
        user_id=uuid.UUID(int=0),
        dispatch=fake_dispatch,
        user_message="loop forever",
        tools_enabled=True,
        intent_tool=None,
        intent_method="none",
    )

    assert "one turn" in result.lower()
    assert mock_client._messages_create.call_count == MAX_ITERATIONS
