"""Shared pipeline constants.

Centralises source identifiers so worker, todo_sync, and tests can import
from one place instead of hard-coding strings.
"""

AUTO_CAPTURE_SOURCES: frozenset[str] = frozenset(
    {
        "claude-code",
        "claude_code_memory",
        "claude_code_history",
        "claude_code_project",
    }
)
