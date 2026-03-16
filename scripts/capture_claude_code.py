#!/usr/bin/env python3
"""Claude Code Stop hook — capture conversation into Open Brain.

Invoked automatically by Claude Code when a session ends. Reads the Stop
hook JSON payload from stdin, parses the JSONL transcript, and POSTs the
conversation text to the Open Brain API for async pipeline processing.

Safety rules:
  - Always exits 0 (never break Claude Code, even on errors).
  - Skips conversations shorter than MIN_LENGTH characters (trivial sessions).
  - Does nothing if stop_hook_active is True (prevents infinite loops).
  - Silently ignores all network/file errors.

Configuration via environment variables:
    OPENBRAIN_API_URL  — Base URL (default: http://localhost:8000)
    OPENBRAIN_API_KEY  — X-API-Key header value

Hook config (add to ~/.claude/settings.json):
    {
      "hooks": {
        "Stop": [{"hooks": [{"type": "command",
                             "command": "python3 /home/shu/projects/open-brain/scripts/capture_claude_code.py"}]}]
      }
    }
"""

import json
import os
import sys
from pathlib import Path

import requests

API_URL: str = os.environ.get("OPENBRAIN_API_URL", "http://localhost:8000").rstrip("/")
API_KEY: str = os.environ.get("OPENBRAIN_API_KEY", "")
MIN_LENGTH: int = 300  # skip trivial sessions
TIMEOUT: float = 15.0


def _extract_content(raw_content: object) -> str:
    """Flatten a message content field to a plain string.

    Content may be a string or a list of typed blocks (Claude Code format).
    """
    if isinstance(raw_content, str):
        return raw_content
    if isinstance(raw_content, list):
        texts: list[str] = []
        for block in raw_content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                texts.append(block)
        return " ".join(texts)
    return ""


def _read_transcript(transcript_path: str) -> str:
    """Read the JSONL transcript and return as formatted text.

    Each JSONL line is a message object. We look for `role` and `content`
    fields. Lines that cannot be parsed are silently skipped.

    Returns an empty string if the file is missing or unreadable.
    """
    path = Path(transcript_path).expanduser()
    if not path.exists():
        return ""

    parts: list[str] = []
    try:
        with path.open() as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                role = entry.get("role", "")
                content = _extract_content(entry.get("content", ""))

                if role and content.strip():
                    parts.append(f"{role.upper()}: {content.strip()}")
    except OSError:
        return ""

    return "\n\n".join(parts)


def _post_transcript(text: str, session_id: str) -> None:
    """POST transcript to Open Brain. Silently ignores all errors."""
    try:
        requests.post(
            f"{API_URL}/v1/memory",
            headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
            json={
                "text": text,
                "source": "claude-code",
                "metadata": {"session_id": session_id},
            },
            timeout=TIMEOUT,
        )
    except Exception:
        pass


def main() -> None:
    """Entry point — reads stdin, captures transcript, exits 0 always."""
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # Malformed payload — log warning to stderr and exit cleanly
        print("open-brain capture: invalid JSON payload, skipping.", file=sys.stderr)
        sys.exit(0)

    # Prevent infinite loops — if a previous stop hook already ran, skip
    if payload.get("stop_hook_active"):
        sys.exit(0)

    session_id: str = payload.get("session_id", "unknown")
    transcript_path: str = payload.get("transcript_path", "")

    if not transcript_path:
        sys.exit(0)

    text = _read_transcript(transcript_path)

    if len(text) < MIN_LENGTH:
        sys.exit(0)

    _post_transcript(text, session_id)
    sys.exit(0)


if __name__ == "__main__":
    main()
