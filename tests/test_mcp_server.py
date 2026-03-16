"""Tests for the Open Brain MCP server (src/mcp_server.py).

Tests call the pure _do_* helper functions directly, mocking httpx so no
real HTTP calls are made. The MCP decorator layer (tool registration,
JSON-RPC framing) is not exercised here — those are fastmcp internals.

Naming convention: test_<tool>_<scenario>
"""

from unittest.mock import MagicMock, patch

import httpx

from src.mcp_server import _do_get_context, _do_ingest_memory, _do_search_memory

# ── Helpers ───────────────────────────────────────────────────────────────────


def _mock_resp(status_code: int, body: dict) -> MagicMock:
    """Build a minimal httpx.Response mock."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = body
    return resp


# ── search_memory ─────────────────────────────────────────────────────────────


def test_search_memory_returns_formatted_results():
    """Happy path: non-empty results formatted as numbered list."""
    body = {
        "results": [
            {
                "type": "memory",
                "created_at": "2026-03-15T00:00:00Z",
                "combined_score": 0.85,
                "content": "Python is a great programming language.",
                "summary": None,
            }
        ],
        "query": "python",
    }
    with patch("src.mcp_server._get", return_value=_mock_resp(200, body)) as mock_get:
        result = _do_search_memory("python", 10)

    mock_get.assert_called_once_with("/v1/search", {"q": "python", "limit": 10})
    assert "[1]" in result
    assert "MEMORY" in result
    assert "0.850" in result
    assert "Python is a great" in result


def test_search_memory_empty_results():
    """Query matches nothing → readable 'no results' message, not a crash."""
    body = {"results": [], "query": "xyzzy"}
    with patch("src.mcp_server._get", return_value=_mock_resp(200, body)):
        result = _do_search_memory("xyzzy", 10)

    assert result == "No results found."


def test_search_memory_api_error_500():
    """API returns 500 → error message with status code, not unhandled exception."""
    with patch("src.mcp_server._get", return_value=_mock_resp(500, {})):
        result = _do_search_memory("python", 10)

    assert "Error" in result
    assert "500" in result


def test_search_memory_api_401():
    """API returns 401 → auth error message."""
    with patch("src.mcp_server._get", return_value=_mock_resp(401, {})):
        result = _do_search_memory("python", 10)

    assert "authentication" in result.lower() or "401" in result


def test_search_memory_limit_clamped_low():
    """limit=0 is clamped to 1 — no crash, no 422."""
    body = {"results": [], "query": "test"}
    with patch("src.mcp_server._get", return_value=_mock_resp(200, body)) as mock_get:
        _do_search_memory("test", 0)

    _, kwargs = mock_get.call_args
    sent_params = mock_get.call_args.args[1]
    assert sent_params["limit"] >= 1


def test_search_memory_limit_clamped_high():
    """limit=999 is clamped to 100 — stays within API bounds."""
    body = {"results": [], "query": "test"}
    with patch("src.mcp_server._get", return_value=_mock_resp(200, body)) as mock_get:
        _do_search_memory("test", 999)

    sent_params = mock_get.call_args.args[1]
    assert sent_params["limit"] <= 100


def test_search_memory_empty_query():
    """Empty string query → error message without making an API call."""
    with patch("src.mcp_server._get") as mock_get:
        result = _do_search_memory("", 10)

    mock_get.assert_not_called()
    assert "Error" in result


def test_search_memory_whitespace_only_query():
    """Whitespace-only query → same error path as empty string."""
    with patch("src.mcp_server._get") as mock_get:
        result = _do_search_memory("   ", 10)

    mock_get.assert_not_called()
    assert "Error" in result


def test_search_memory_connect_error():
    """Connection refused → user-friendly error, not unhandled ConnectError."""
    with patch("src.mcp_server._get", side_effect=httpx.ConnectError("refused")):
        result = _do_search_memory("python", 10)

    assert "connect" in result.lower() or "Error" in result


def test_search_memory_timeout():
    """Request timeout → user-friendly error, not unhandled TimeoutException."""
    with patch("src.mcp_server._get", side_effect=httpx.TimeoutException("timeout")):
        result = _do_search_memory("python", 10)

    assert "timed out" in result.lower() or "Error" in result


def test_search_memory_multiple_results_ordered():
    """Multiple results appear in order with correct indices."""
    body = {
        "results": [
            {
                "type": "memory",
                "created_at": "2026-03-01T00:00:00Z",
                "combined_score": 0.9,
                "content": "First result",
            },
            {
                "type": "decision",
                "created_at": "2026-02-01T00:00:00Z",
                "combined_score": 0.7,
                "content": "Second result",
            },
        ],
        "query": "test",
    }
    with patch("src.mcp_server._get", return_value=_mock_resp(200, body)):
        result = _do_search_memory("test", 10)

    assert "[1]" in result
    assert "[2]" in result
    assert "First result" in result
    assert "DECISION" in result


# ── get_context ───────────────────────────────────────────────────────────────


def test_get_context_returns_context_block():
    """Happy path: context block with footer showing token usage."""
    body = {
        "context": "## Memory Context\n\n[1] Python is great.",
        "tokens_used": 42,
        "tokens_budget": 8192,
        "items_included": 1,
        "items_truncated": 0,
        "query": "python",
    }
    with patch("src.mcp_server._get", return_value=_mock_resp(200, body)) as mock_get:
        result = _do_get_context("python", 10)

    mock_get.assert_called_once_with("/v1/search/context", {"q": "python", "limit": 10})
    assert "Python is great" in result
    assert "42/8192" in result
    assert "1 items" in result


def test_get_context_no_matches():
    """Empty context → readable no-results message, not crash."""
    body = {
        "context": "",
        "tokens_used": 0,
        "tokens_budget": 8192,
        "items_included": 0,
        "items_truncated": 0,
        "query": "xyzzy",
    }
    with patch("src.mcp_server._get", return_value=_mock_resp(200, body)):
        result = _do_get_context("xyzzy", 10)

    assert "No relevant memories" in result


def test_get_context_api_unreachable():
    """Connection error → user-friendly error string (MCP must not crash)."""
    with patch("src.mcp_server._get", side_effect=httpx.ConnectError("refused")):
        result = _do_get_context("python", 10)

    assert "Error" in result
    # Must be a string — no exception propagated
    assert isinstance(result, str)


def test_get_context_api_401():
    """Auth failure → auth error message."""
    with patch("src.mcp_server._get", return_value=_mock_resp(401, {})):
        result = _do_get_context("python", 10)

    assert "authentication" in result.lower() or "401" in result


def test_get_context_api_500():
    """Server error → error message with status code."""
    with patch("src.mcp_server._get", return_value=_mock_resp(500, {})):
        result = _do_get_context("python", 10)

    assert "Error" in result
    assert "500" in result


def test_get_context_empty_query():
    """Empty query → error without API call."""
    with patch("src.mcp_server._get") as mock_get:
        result = _do_get_context("", 10)

    mock_get.assert_not_called()
    assert "Error" in result


def test_get_context_timeout():
    """Timeout → user-friendly error."""
    with patch("src.mcp_server._get", side_effect=httpx.TimeoutException("t/o")):
        result = _do_get_context("python", 10)

    assert "timed out" in result.lower() or "Error" in result


# ── ingest_memory ─────────────────────────────────────────────────────────────


def test_ingest_memory_success():
    """Happy path: returns raw_id and 'queued' confirmation."""
    body = {"raw_id": "aaaa-1111", "status": "queued"}
    with patch("src.mcp_server._post", return_value=_mock_resp(202, body)) as mock_post:
        result = _do_ingest_memory("interesting insight about python", "mcp")

    mock_post.assert_called_once_with(
        "/v1/memory", {"text": "interesting insight about python", "source": "mcp"}
    )
    assert "aaaa-1111" in result
    assert "Queued" in result or "queued" in result


def test_ingest_memory_duplicate():
    """Duplicate content within 24h → 'Duplicate' message, not an error."""
    body = {"raw_id": "bbbb-2222", "status": "duplicate"}
    with patch("src.mcp_server._post", return_value=_mock_resp(202, body)):
        result = _do_ingest_memory("same content again", "mcp")

    assert "Duplicate" in result or "duplicate" in result
    assert "bbbb-2222" in result


def test_ingest_memory_empty_text():
    """Empty text → error message without making an API call."""
    with patch("src.mcp_server._post") as mock_post:
        result = _do_ingest_memory("", "mcp")

    mock_post.assert_not_called()
    assert "Error" in result


def test_ingest_memory_whitespace_text():
    """Whitespace-only text → same as empty."""
    with patch("src.mcp_server._post") as mock_post:
        result = _do_ingest_memory("   \n\t  ", "mcp")

    mock_post.assert_not_called()
    assert "Error" in result


def test_ingest_memory_api_422():
    """API returns 422 (invalid input) → error message with detail."""
    body = {"detail": "text is required"}
    with patch("src.mcp_server._post", return_value=_mock_resp(422, body)):
        result = _do_ingest_memory("some text", "mcp")

    assert "Error" in result
    assert "text is required" in result


def test_ingest_memory_api_401():
    """Wrong API key → auth error message (not silent fail)."""
    with patch("src.mcp_server._post", return_value=_mock_resp(401, {})):
        result = _do_ingest_memory("some text", "mcp")

    assert "authentication" in result.lower() or "401" in result


def test_ingest_memory_very_long_text():
    """Text > 8000 chars is accepted — no crash, API decides chunking."""
    long_text = "A" * 9000
    body = {"raw_id": "cccc-3333", "status": "queued"}
    with patch("src.mcp_server._post", return_value=_mock_resp(202, body)):
        result = _do_ingest_memory(long_text, "mcp")

    assert "cccc-3333" in result


def test_ingest_memory_connect_error():
    """Connection refused → user-friendly error string."""
    with patch("src.mcp_server._post", side_effect=httpx.ConnectError("refused")):
        result = _do_ingest_memory("some text", "mcp")

    assert "Error" in result
    assert isinstance(result, str)


def test_ingest_memory_timeout():
    """Timeout → user-friendly error string."""
    with patch("src.mcp_server._post", side_effect=httpx.TimeoutException("t/o")):
        result = _do_ingest_memory("some text", "mcp")

    assert "timed out" in result.lower() or "Error" in result


def test_ingest_memory_custom_source():
    """source parameter is forwarded in POST body."""
    body = {"raw_id": "dddd-4444", "status": "queued"}
    with patch("src.mcp_server._post", return_value=_mock_resp(202, body)) as mock_post:
        _do_ingest_memory("some text", "claude-code")

    sent_body = mock_post.call_args.args[1]
    assert sent_body["source"] == "claude-code"
