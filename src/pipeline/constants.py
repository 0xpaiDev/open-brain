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

# Sources that should skip Task row creation. Includes auto-capture sources
# (noise) plus manual Claude Code ingestions (work already completed in session).
TASK_SKIP_SOURCES: frozenset[str] = AUTO_CAPTURE_SOURCES | {
    "claude-code-manual",
    "daily-pulse",
    "training-weekly",
    "strava-activity",
}
