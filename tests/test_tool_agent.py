"""Tests for AnthropicClient._messages_create and the tool-use loop."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


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
