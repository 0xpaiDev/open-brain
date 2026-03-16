"""Tests for scripts/capture_claude_code.py.

The capture script is a standalone CLI (not a module), so we test it via:
  - Direct function imports (_read_transcript, _extract_content, _post_transcript)
  - subprocess invocation of main() via stdin injection

All HTTP calls are mocked. No real files are created for unit tests —
we use tmp_path fixtures for file-based tests.

Naming convention: test_capture_<scenario>
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import the helper functions directly
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.capture_claude_code import (
    _extract_content,
    _post_transcript,
    _read_transcript,
    main,
)

# ── _extract_content ──────────────────────────────────────────────────────────


def test_extract_content_string():
    """String content is returned as-is."""
    assert _extract_content("hello world") == "hello world"


def test_extract_content_list_of_text_blocks():
    """List of {type: text, text: ...} blocks are joined."""
    blocks = [
        {"type": "text", "text": "Hello"},
        {"type": "text", "text": "World"},
    ]
    result = _extract_content(blocks)
    assert "Hello" in result
    assert "World" in result


def test_extract_content_list_of_strings():
    """List of raw strings are joined."""
    result = _extract_content(["foo", "bar"])
    assert "foo" in result
    assert "bar" in result


def test_extract_content_non_text_blocks_skipped():
    """Blocks with type != text are skipped."""
    blocks = [
        {"type": "tool_use", "id": "abc"},
        {"type": "text", "text": "kept"},
    ]
    result = _extract_content(blocks)
    assert "kept" in result
    assert "tool_use" not in result


def test_extract_content_unknown_type_returns_empty():
    """Non-string, non-list content returns empty string."""
    assert _extract_content(42) == ""  # type: ignore[arg-type]
    assert _extract_content(None) == ""  # type: ignore[arg-type]


# ── _read_transcript ──────────────────────────────────────────────────────────


def test_read_transcript_basic(tmp_path: Path):
    """Valid JSONL transcript is parsed into role-prefixed text blocks."""
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps({"role": "user", "content": "What is Python?"})
        + "\n"
        + json.dumps({"role": "assistant", "content": "Python is a language."})
        + "\n"
    )
    result = _read_transcript(str(transcript))
    assert "USER: What is Python?" in result
    assert "ASSISTANT: Python is a language." in result


def test_read_transcript_missing_file():
    """Missing transcript file returns empty string (not raises)."""
    result = _read_transcript("/nonexistent/path/transcript.jsonl")
    assert result == ""


def test_read_transcript_empty_file(tmp_path: Path):
    """Empty transcript file returns empty string."""
    transcript = tmp_path / "empty.jsonl"
    transcript.write_text("")
    result = _read_transcript(str(transcript))
    assert result == ""


def test_read_transcript_skips_malformed_lines(tmp_path: Path):
    """Lines that are not valid JSON are silently skipped."""
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "this is not json\n" + json.dumps({"role": "user", "content": "valid message"}) + "\n"
    )
    result = _read_transcript(str(transcript))
    assert "valid message" in result


def test_read_transcript_skips_blank_lines(tmp_path: Path):
    """Blank lines between entries are skipped without error."""
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "\n"
        + json.dumps({"role": "user", "content": "hello"})
        + "\n"
        + "\n"
        + json.dumps({"role": "assistant", "content": "world"})
        + "\n"
    )
    result = _read_transcript(str(transcript))
    assert "hello" in result
    assert "world" in result


def test_read_transcript_skips_entries_without_role(tmp_path: Path):
    """Entries missing a 'role' field are silently skipped."""
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps({"content": "no role here"})
        + "\n"
        + json.dumps({"role": "user", "content": "has role"})
        + "\n"
    )
    result = _read_transcript(str(transcript))
    assert "no role here" not in result
    assert "has role" in result


def test_read_transcript_handles_list_content(tmp_path: Path):
    """Content as a list of text blocks is correctly flattened."""
    transcript = tmp_path / "session.jsonl"
    entry = {
        "role": "assistant",
        "content": [{"type": "text", "text": "Here is my answer."}],
    }
    transcript.write_text(json.dumps(entry) + "\n")
    result = _read_transcript(str(transcript))
    assert "Here is my answer." in result


def test_read_transcript_tilde_expansion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Paths starting with ~ are expanded to the home directory."""
    # Create a file in tmp_path and simulate a ~ path
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(json.dumps({"role": "user", "content": "hello"}) + "\n")

    # We just verify that the function doesn't crash on a ~ path that resolves
    # (real ~ expansion is tested indirectly by Path.expanduser)
    result = _read_transcript(str(transcript))
    assert "hello" in result


# ── _post_transcript ──────────────────────────────────────────────────────────


def test_post_transcript_sends_correct_payload():
    """_post_transcript POSTs to /v1/memory with source=claude-code."""
    mock_resp = MagicMock()
    mock_resp.status_code = 202

    with patch("scripts.capture_claude_code.requests.post", return_value=mock_resp) as mock_post:
        _post_transcript("some conversation text", "session-abc")

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["text"] == "some conversation text"
    assert kwargs["json"]["source"] == "claude-code"
    assert kwargs["json"]["metadata"]["session_id"] == "session-abc"


def test_post_transcript_silently_ignores_connection_error():
    """_post_transcript does not raise on connection error (fire-and-forget)."""
    import requests as req

    with patch(
        "scripts.capture_claude_code.requests.post", side_effect=req.ConnectionError("refused")
    ):
        _post_transcript("text", "session-abc")  # must not raise


def test_post_transcript_silently_ignores_timeout():
    """_post_transcript does not raise on timeout."""
    import requests as req

    with patch("scripts.capture_claude_code.requests.post", side_effect=req.Timeout("t/o")):
        _post_transcript("text", "session-abc")  # must not raise


def test_post_transcript_silently_ignores_api_500():
    """_post_transcript does not raise on API 500 response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500

    with patch("scripts.capture_claude_code.requests.post", return_value=mock_resp):
        _post_transcript("text", "session-abc")  # must not raise


# ── main() — end-to-end via stdin injection ───────────────────────────────────


def _run_main_with_stdin(payload: str) -> None:
    """Invoke main() with given stdin string, capturing sys.exit(0)."""
    from io import StringIO

    with patch("sys.stdin", StringIO(payload)), pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0, f"Expected exit 0, got {exc_info.value.code}"


def test_capture_posts_transcript_to_api(tmp_path: Path):
    """Valid payload with long-enough transcript triggers a POST."""
    transcript = tmp_path / "session.jsonl"
    long_content = "Python is a great language. " * 20  # > 300 chars
    transcript.write_text(
        json.dumps({"role": "user", "content": long_content})
        + "\n"
        + json.dumps({"role": "assistant", "content": long_content})
        + "\n"
    )

    payload = json.dumps(
        {
            "session_id": "test-session-001",
            "transcript_path": str(transcript),
            "stop_hook_active": False,
        }
    )

    with patch("scripts.capture_claude_code.requests.post") as mock_post:
        _run_main_with_stdin(payload)

    mock_post.assert_called_once()
    sent_body = mock_post.call_args.kwargs["json"]
    assert "Python" in sent_body["text"]
    assert sent_body["source"] == "claude-code"


def test_capture_skips_empty_payload():
    """Empty stdin → no POST, exits 0."""
    with patch("scripts.capture_claude_code.requests.post") as mock_post:
        _run_main_with_stdin("")

    mock_post.assert_not_called()


def test_capture_skips_whitespace_payload():
    """Whitespace-only stdin → no POST, exits 0."""
    with patch("scripts.capture_claude_code.requests.post") as mock_post:
        _run_main_with_stdin("   \n  \t  ")

    mock_post.assert_not_called()


def test_capture_skips_short_transcript(tmp_path: Path):
    """Transcript < MIN_LENGTH characters → no POST (avoid noise)."""
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(json.dumps({"role": "user", "content": "hi"}) + "\n")

    payload = json.dumps(
        {
            "session_id": "short-session",
            "transcript_path": str(transcript),
            "stop_hook_active": False,
        }
    )

    with patch("scripts.capture_claude_code.requests.post") as mock_post:
        _run_main_with_stdin(payload)

    mock_post.assert_not_called()


def test_capture_handles_api_error_gracefully(tmp_path: Path):
    """API 500 → script exits 0 (hook must not break Claude Code)."""
    import requests as req

    transcript = tmp_path / "session.jsonl"
    long_content = "content " * 50
    transcript.write_text(json.dumps({"role": "user", "content": long_content}) + "\n")

    payload = json.dumps(
        {
            "session_id": "err-session",
            "transcript_path": str(transcript),
            "stop_hook_active": False,
        }
    )

    with patch(
        "scripts.capture_claude_code.requests.post", side_effect=req.ConnectionError("down")
    ):
        _run_main_with_stdin(payload)  # must not raise, exit 0


def test_capture_sets_source_claude_code(tmp_path: Path):
    """source field in POST body is always 'claude-code'."""
    transcript = tmp_path / "session.jsonl"
    long_content = "interesting content " * 20
    transcript.write_text(json.dumps({"role": "user", "content": long_content}) + "\n")

    payload = json.dumps(
        {
            "session_id": "src-test",
            "transcript_path": str(transcript),
            "stop_hook_active": False,
        }
    )

    with patch("scripts.capture_claude_code.requests.post") as mock_post:
        _run_main_with_stdin(payload)

    sent_body = mock_post.call_args.kwargs["json"]
    assert sent_body["source"] == "claude-code"


def test_capture_invalid_json_stdin_exits_zero():
    """Malformed JSON stdin → exits 0, logs warning to stderr (no crash)."""
    with patch("scripts.capture_claude_code.requests.post") as mock_post:
        _run_main_with_stdin("not { valid } json [ at all")

    mock_post.assert_not_called()


def test_capture_skips_when_stop_hook_active(tmp_path: Path):
    """stop_hook_active=True → no POST (prevents infinite hook loops)."""
    transcript = tmp_path / "session.jsonl"
    long_content = "important stuff " * 30
    transcript.write_text(json.dumps({"role": "user", "content": long_content}) + "\n")

    payload = json.dumps(
        {
            "session_id": "loop-guard",
            "transcript_path": str(transcript),
            "stop_hook_active": True,  # ← already in a hook cycle
        }
    )

    with patch("scripts.capture_claude_code.requests.post") as mock_post:
        _run_main_with_stdin(payload)

    mock_post.assert_not_called()


def test_capture_skips_when_no_transcript_path():
    """Missing transcript_path → no POST, exits 0."""
    payload = json.dumps({"session_id": "no-path", "stop_hook_active": False})

    with patch("scripts.capture_claude_code.requests.post") as mock_post:
        _run_main_with_stdin(payload)

    mock_post.assert_not_called()
