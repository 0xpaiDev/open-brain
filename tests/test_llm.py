"""Tests for LLM clients (Anthropic and Voyage AI)."""

from unittest.mock import MagicMock, patch

import pytest

from src.llm.client import (
    AnthropicClient,
    EmbeddingFailed,
    ExtractionFailed,
    VoyageEmbeddingClient,
)
from src.llm.prompts import (
    EXTRACTION_RETRY_PROMPT_1,
    EXTRACTION_RETRY_PROMPT_2,
    EXTRACTION_SYSTEM_PROMPT,
    build_extraction_user_message,
    get_extraction_prompt,
)

# ── AnthropicClient tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_anthropic_client_complete_returns_string():
    """AnthropicClient.complete() returns a string response from Claude."""
    with patch("src.llm.client.Anthropic") as mock_anthropic_class:
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client

        # Mock the SDK response
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="test response")]
        mock_client.messages.create.return_value = mock_response

        client = AnthropicClient(api_key="test-key", model="claude-test")
        result = await client.complete(
            system_prompt="test system",
            user_content="test user",
        )

        assert isinstance(result, str)
        assert result == "test response"


@pytest.mark.asyncio
async def test_anthropic_client_raises_extraction_failed_on_sdk_error():
    """ExtractionFailed is raised when the Anthropic SDK fails."""
    with patch("src.llm.client.Anthropic") as mock_anthropic_class:
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client

        # Simulate an SDK error
        mock_client.messages.create.side_effect = RuntimeError("Anthropic API Error")

        client = AnthropicClient(api_key="test-key", model="claude-test")

        with pytest.raises(ExtractionFailed):
            await client.complete(
                system_prompt="test",
                user_content="test",
            )


@pytest.mark.asyncio
async def test_anthropic_client_raises_extraction_failed_on_unexpected_error():
    """ExtractionFailed is raised for unexpected errors."""
    with patch("src.llm.client.Anthropic") as mock_anthropic_class:
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client
        mock_client.messages.create.side_effect = RuntimeError("Network error")

        client = AnthropicClient(api_key="test-key", model="claude-test")

        with pytest.raises(ExtractionFailed):
            await client.complete(
                system_prompt="test",
                user_content="test",
            )


# ── VoyageEmbeddingClient tests ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_voyage_client_embed_returns_1024_floats():
    """VoyageEmbeddingClient.embed() returns a list of 1024 floats."""
    with patch("src.llm.client.VoyageClient") as mock_voyage_class:
        mock_client = MagicMock()
        mock_voyage_class.return_value = mock_client

        # Mock the embed response
        mock_result = MagicMock()
        mock_result.embeddings = [[0.1] * 1024]
        mock_client.embed.return_value = mock_result

        client = VoyageEmbeddingClient(api_key="test-key", model="voyage-3")
        result = await client.embed("test text")

        assert isinstance(result, list)
        assert len(result) == 1024
        assert all(isinstance(x, float) for x in result)


@pytest.mark.asyncio
async def test_voyage_client_raises_embedding_failed_on_error():
    """EmbeddingFailed is raised when Voyage SDK fails."""
    with patch("src.llm.client.VoyageClient") as mock_voyage_class:
        mock_client = MagicMock()
        mock_voyage_class.return_value = mock_client
        mock_client.embed.side_effect = RuntimeError("API Error")

        client = VoyageEmbeddingClient(api_key="test-key", model="voyage-3")

        with pytest.raises(EmbeddingFailed):
            await client.embed("test text")


@pytest.mark.asyncio
async def test_voyage_client_retries_on_failure():
    """VoyageEmbeddingClient retries up to 3 times before failing."""
    with patch("src.llm.client.VoyageClient") as mock_voyage_class:
        mock_client = MagicMock()
        mock_voyage_class.return_value = mock_client

        # Fail 3 times, then raise EmbeddingFailed
        mock_client.embed.side_effect = RuntimeError("Transient error")

        client = VoyageEmbeddingClient(api_key="test-key", model="voyage-3")

        with pytest.raises(EmbeddingFailed):
            await client.embed("test text")

        # Verify the SDK was called 3 times (initial + 2 retries)
        assert mock_client.embed.call_count == 3


# ── Prompt tests ──────────────────────────────────────────────────────────


def test_build_extraction_user_message_wraps_in_delimiters():
    """build_extraction_user_message wraps text in <user_input> tags."""
    text = "This is a test"
    result = build_extraction_user_message(text)

    assert result == "<user_input>This is a test</user_input>"


def test_build_extraction_user_message_preserves_special_chars():
    """Special characters in user input are preserved."""
    text = 'He said "hello" and <script>alert("xss")</script>'
    result = build_extraction_user_message(text)

    assert text in result  # Text is preserved inside the delimiters
    assert result.startswith("<user_input>")
    assert result.endswith("</user_input>")


def test_get_extraction_prompt_returns_attempt_0():
    """get_extraction_prompt(0) returns the main extraction prompt."""
    result = get_extraction_prompt(0)

    assert result == EXTRACTION_SYSTEM_PROMPT
    assert "JSON" in result
    assert "entities" in result


def test_get_extraction_prompt_returns_attempt_1():
    """get_extraction_prompt(1) returns the stricter retry prompt."""
    result = get_extraction_prompt(1)

    assert result == EXTRACTION_RETRY_PROMPT_1
    assert "VALID JSON ONLY" in result


def test_get_extraction_prompt_returns_attempt_2():
    """get_extraction_prompt(2) returns the minimal fallback prompt."""
    result = get_extraction_prompt(2)

    assert result == EXTRACTION_RETRY_PROMPT_2
    assert "ONLY this JSON" in result


def test_get_extraction_prompt_different_per_attempt():
    """Different attempts return different prompts."""
    prompt_0 = get_extraction_prompt(0)
    prompt_1 = get_extraction_prompt(1)
    prompt_2 = get_extraction_prompt(2)

    assert prompt_0 != prompt_1
    assert prompt_1 != prompt_2
    assert prompt_0 != prompt_2


def test_get_extraction_prompt_raises_on_invalid_attempt():
    """get_extraction_prompt raises ValueError for invalid attempt numbers."""
    with pytest.raises(ValueError):
        get_extraction_prompt(3)

    with pytest.raises(ValueError):
        get_extraction_prompt(-1)


def test_all_extraction_prompts_are_non_empty():
    """All extraction prompt constants are non-empty strings."""
    assert isinstance(EXTRACTION_SYSTEM_PROMPT, str)
    assert len(EXTRACTION_SYSTEM_PROMPT) > 0

    assert isinstance(EXTRACTION_RETRY_PROMPT_1, str)
    assert len(EXTRACTION_RETRY_PROMPT_1) > 0

    assert isinstance(EXTRACTION_RETRY_PROMPT_2, str)
    assert len(EXTRACTION_RETRY_PROMPT_2) > 0
