"""Tests for the ob chat command (cli/ob.py).

Tests mirror the pattern in test_cli.py: synchronous CliRunner for the
command-level tests, direct patching of inner helpers for behaviour tests.

The chat loop reads from stdin via input() — we patch builtins.input to
simulate user sessions. HTTP and LLM calls are mocked via unittest.mock.

Naming convention: test_chat_<scenario>
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from cli.ob import _fetch_ob_context, _post_to_ob, app

runner = CliRunner()


# ── ob chat — command-level (CliRunner, mocks _chat_async) ───────────────────


def test_chat_unknown_model_exits_nonzero():
    """ob chat --model unknown exits 1 with error message before touching API."""
    result = runner.invoke(app, ["chat", "--model", "unknown-model"])
    assert result.exit_code == 1
    assert "unknown" in result.output.lower() or "unknown" in (result.stderr or "")


def test_chat_valid_model_calls_async():
    """ob chat --model claude exits 0 when _chat_async returns normally."""
    with patch("cli.ob._chat_async", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = None
        result = runner.invoke(app, ["chat", "--model", "claude"])

    assert result.exit_code == 0
    mock_fn.assert_called_once_with("claude", None, False)


def test_chat_default_model_is_claude():
    """ob chat without --model defaults to 'claude'."""
    with patch("cli.ob._chat_async", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = None
        runner.invoke(app, ["chat"])

    args = mock_fn.call_args.args
    assert args[0] == "claude"


def test_chat_topic_passed_through():
    """ob chat --topic 'python async' passes topic to _chat_async."""
    with patch("cli.ob._chat_async", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = None
        runner.invoke(app, ["chat", "--topic", "python async"])

    args = mock_fn.call_args.args
    assert args[1] == "python async"


def test_chat_no_ingest_flag_passed_through():
    """ob chat --no-ingest passes no_ingest=True to _chat_async."""
    with patch("cli.ob._chat_async", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = None
        runner.invoke(app, ["chat", "--no-ingest"])

    args = mock_fn.call_args.args
    assert args[2] is True


def test_chat_help():
    """ob chat --help exits 0 and mentions supported models."""
    result = runner.invoke(app, ["chat", "--help"])
    assert result.exit_code == 0
    assert "claude" in result.output


# ── _fetch_ob_context — unit tests ───────────────────────────────────────────


def test_fetch_ob_context_returns_context_on_200():
    """_fetch_ob_context returns context string from API response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"context": "Relevant memory: Python is great."}

    with patch("cli.ob.httpx.get", return_value=mock_resp):
        result = _fetch_ob_context("python")

    assert result == "Relevant memory: Python is great."


def test_fetch_ob_context_returns_empty_on_non_200():
    """_fetch_ob_context returns '' (not raises) on non-200 response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500

    with patch("cli.ob.httpx.get", return_value=mock_resp):
        result = _fetch_ob_context("python")

    assert result == ""


def test_fetch_ob_context_returns_empty_on_connection_error():
    """_fetch_ob_context returns '' when API is unreachable (graceful degradation)."""
    import httpx

    with patch("cli.ob.httpx.get", side_effect=httpx.ConnectError("refused")):
        result = _fetch_ob_context("python")

    assert result == ""


def test_fetch_ob_context_returns_empty_on_timeout():
    """_fetch_ob_context returns '' on timeout (chat must not crash)."""
    import httpx

    with patch("cli.ob.httpx.get", side_effect=httpx.TimeoutException("t/o")):
        result = _fetch_ob_context("python")

    assert result == ""


def test_fetch_ob_context_returns_empty_on_401():
    """_fetch_ob_context returns '' on auth failure (non-200 path)."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401

    with patch("cli.ob.httpx.get", return_value=mock_resp):
        result = _fetch_ob_context("python")

    assert result == ""


# ── _post_to_ob — unit tests ─────────────────────────────────────────────────


def test_post_to_ob_sends_correct_body():
    """_post_to_ob POSTs the correct text and source."""
    mock_resp = MagicMock()
    mock_resp.status_code = 202

    with patch("cli.ob.httpx.post", return_value=mock_resp) as mock_post:
        _post_to_ob("some text", "ob-chat")

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["text"] == "some text"
    assert kwargs["json"]["source"] == "ob-chat"


def test_post_to_ob_silently_ignores_error():
    """_post_to_ob does not raise on API error (fire-and-forget)."""
    import httpx

    with patch("cli.ob.httpx.post", side_effect=httpx.ConnectError("refused")):
        _post_to_ob("some text", "ob-chat")  # must not raise


def test_post_to_ob_silently_ignores_timeout():
    """_post_to_ob does not raise on timeout."""
    import httpx

    with patch("cli.ob.httpx.post", side_effect=httpx.TimeoutException("t/o")):
        _post_to_ob("some text", "ob-chat")  # must not raise


# ── _chat_async — behaviour tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chat_search_called_on_each_turn():
    """_fetch_ob_context is called once per user message turn."""
    from cli.ob import _chat_async

    inputs = iter(["hello", "world", "exit"])
    with (
        patch("builtins.input", side_effect=lambda _="": next(inputs)),
        patch("cli.ob._fetch_ob_context", return_value="context") as mock_ctx,
        patch("cli.ob._call_llm_for_chat", new_callable=AsyncMock, return_value="reply"),
        patch("cli.ob._post_to_ob"),
    ):
        await _chat_async("claude", None, no_ingest=True)

    # 2 real messages: "hello", "world" ("exit" ends loop, no context fetch)
    assert mock_ctx.call_count == 2
    mock_ctx.assert_any_call("hello")
    mock_ctx.assert_any_call("world")


@pytest.mark.asyncio
async def test_chat_injects_context_into_system_prompt():
    """System prompt passed to LLM contains the context from open-brain."""
    from cli.ob import _chat_async

    inputs = iter(["tell me about python", "exit"])
    captured_system: list[str] = []

    async def capture_llm(model: str, system: str, messages: list) -> str:
        captured_system.append(system)
        return "reply"

    with (
        patch("builtins.input", side_effect=lambda _="": next(inputs)),
        patch("cli.ob._fetch_ob_context", return_value="## Memory\nPython is great."),
        patch("cli.ob._call_llm_for_chat", side_effect=capture_llm),
        patch("cli.ob._post_to_ob"),
    ):
        await _chat_async("claude", None, no_ingest=True)

    assert len(captured_system) == 1
    assert "Python is great." in captured_system[0]


@pytest.mark.asyncio
async def test_chat_no_context_available_still_works():
    """When open-brain returns empty context, chat continues without error."""
    from cli.ob import _chat_async

    inputs = iter(["hello", "exit"])
    with (
        patch("builtins.input", side_effect=lambda _="": next(inputs)),
        patch("cli.ob._fetch_ob_context", return_value=""),
        patch("cli.ob._call_llm_for_chat", new_callable=AsyncMock, return_value="reply"),
        patch("cli.ob._post_to_ob"),
    ):
        await _chat_async("claude", None, no_ingest=True)
    # No exception → graceful degradation confirmed


@pytest.mark.asyncio
async def test_chat_auto_ingest_on_exit():
    """_post_to_ob is called at session end when no_ingest=False."""
    from cli.ob import _chat_async

    inputs = iter(["interesting fact about python", "exit"])
    with (
        patch("builtins.input", side_effect=lambda _="": next(inputs)),
        patch("cli.ob._fetch_ob_context", return_value=""),
        patch("cli.ob._call_llm_for_chat", new_callable=AsyncMock, return_value="reply"),
        patch("cli.ob._post_to_ob") as mock_post,
    ):
        await _chat_async("claude", None, no_ingest=False)

    mock_post.assert_called_once()
    text_arg = mock_post.call_args.args[0]
    assert "interesting fact" in text_arg
    # source is passed as keyword argument
    source_arg = mock_post.call_args.kwargs.get("source") or mock_post.call_args.args[1]
    assert source_arg == "ob-chat"


@pytest.mark.asyncio
async def test_chat_no_ingest_flag_skips_post():
    """_post_to_ob is NOT called when no_ingest=True."""
    from cli.ob import _chat_async

    inputs = iter(["some message", "exit"])
    with (
        patch("builtins.input", side_effect=lambda _="": next(inputs)),
        patch("cli.ob._fetch_ob_context", return_value=""),
        patch("cli.ob._call_llm_for_chat", new_callable=AsyncMock, return_value="reply"),
        patch("cli.ob._post_to_ob") as mock_post,
    ):
        await _chat_async("claude", None, no_ingest=True)

    mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_chat_llm_error_continues_session():
    """When LLM raises an exception, the error is printed and the session continues."""
    from cli.ob import _chat_async

    call_count = 0

    async def flaky_llm(model: str, system: str, messages: list) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("LLM failure")
        return "recovered reply"

    inputs = iter(["first message", "second message", "exit"])
    with (
        patch("builtins.input", side_effect=lambda _="": next(inputs)),
        patch("cli.ob._fetch_ob_context", return_value=""),
        patch("cli.ob._call_llm_for_chat", side_effect=flaky_llm),
        patch("cli.ob._post_to_ob"),
    ):
        await _chat_async("claude", None, no_ingest=True)
    # No unhandled exception; session survived the first LLM error


@pytest.mark.asyncio
async def test_chat_empty_user_input_skips_llm():
    """Empty input (just Enter) does not trigger an LLM call."""
    from cli.ob import _chat_async

    inputs = iter(["", "  ", "hello", "exit"])
    with (
        patch("builtins.input", side_effect=lambda _="": next(inputs)),
        patch("cli.ob._fetch_ob_context", return_value=""),
        patch(
            "cli.ob._call_llm_for_chat", new_callable=AsyncMock, return_value="reply"
        ) as mock_llm,
        patch("cli.ob._post_to_ob"),
    ):
        await _chat_async("claude", None, no_ingest=True)

    # Only "hello" triggers an LLM call; empty lines are skipped
    assert mock_llm.call_count == 1


@pytest.mark.asyncio
async def test_chat_topic_seeds_context():
    """When --topic is provided, _fetch_ob_context is called with the topic before first turn."""
    from cli.ob import _chat_async

    inputs = iter(["exit"])
    with (
        patch("builtins.input", side_effect=lambda _="": next(inputs)),
        patch("cli.ob._fetch_ob_context", return_value="seed context") as mock_ctx,
        patch("cli.ob._call_llm_for_chat", new_callable=AsyncMock, return_value="reply"),
        patch("cli.ob._post_to_ob"),
    ):
        await _chat_async("claude", "python async", no_ingest=True)

    mock_ctx.assert_called_with("python async")
