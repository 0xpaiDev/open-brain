"""Hybrid intent classifier for chat tool routing.

Fast path: regex patterns matched against the user message.
Slow path: Haiku LLM call if no regex match.
Returns (tool_name | None, method: "regex" | "haiku" | "none").
"""
from __future__ import annotations

import json
import re

import structlog

logger = structlog.get_logger(__name__)

_TOOL_PATTERNS: dict[str, re.Pattern] = {
    "complete_todo": re.compile(
        r"mark.*(done|complete|finished)|check\s*off|finish(ed)?.*(task|todo|it)|i finished",
        re.IGNORECASE,
    ),
    "list_todos": re.compile(
        r"show.*(todos|tasks|my list|open)|what.*(on my list|open tasks|my todos)|list.*(tasks|todos)",
        re.IGNORECASE,
    ),
    "create_todo": re.compile(
        r"(create|add|new).*(task|todo|reminder)|remind me to|add.*reminder",
        re.IGNORECASE,
    ),
    "defer_todo": re.compile(
        r"\bdefer\b|\bsnooze\b|push\s*back|postpone|reschedule",
        re.IGNORECASE,
    ),
    "edit_todo": re.compile(
        r"rename.*(task|todo)|change.*(task|todo|description)|update.*(task|todo)|edit.*(task|todo)",
        re.IGNORECASE,
    ),
    "search_memory_filtered": re.compile(
        r"search.*(mem|learn|decision|note)|find.*(learn|mem|decision)|look up.*(mem|decision|learn)",
        re.IGNORECASE,
    ),
    "expand_memory": re.compile(
        r"expand.*(memory|mem)|show full|more detail.*(memory|mem)|full content",
        re.IGNORECASE,
    ),
}

_INTENT_SYSTEM_PROMPT = """\
You are an intent classifier. Given a user message, identify which tool (if any) the user needs.

Tools and their intents:
- complete_todo: mark a todo/task as done or complete
- list_todos: show, list, or view todos/tasks
- create_todo: create, add, or set a new todo/task/reminder
- defer_todo: defer, snooze, postpone, or push back a todo
- edit_todo: rename, update, or change a todo description/priority/project
- search_memory_filtered: search, find, or look up memories/learnings/decisions
- expand_memory: get the full content of a specific memory item

Respond with JSON only. Examples:
{"tool": "complete_todo"}
{"tool": null}"""


async def _haiku_classify(message: str) -> str | None:
    from src.llm.client import anthropic_client

    if anthropic_client is None:
        return None

    try:
        raw = await anthropic_client.complete_with_history(
            system_prompt=_INTENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": message}],
            model="claude-haiku-4-5-20251001",
            max_tokens=30,
        )
        data = json.loads(raw.strip())
        return data.get("tool") or None
    except Exception:
        logger.warning("intent_classifier_haiku_failed", message=message[:80])
        return None


async def classify_intent(message: str) -> tuple[str | None, str]:
    for tool_name, pattern in _TOOL_PATTERNS.items():
        if pattern.search(message):
            return tool_name, "regex"

    try:
        tool = await _haiku_classify(message)
    except Exception:
        logger.warning("classify_intent_haiku_error", exc_info=True)
        return None, "none"

    if tool is not None:
        return tool, "haiku"

    return None, "none"
