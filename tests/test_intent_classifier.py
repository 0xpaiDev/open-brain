"""Tests for the hybrid intent classifier (regex fast path + Haiku fallback)."""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.parametrize("message,expected_tool", [
    ("mark that task as done", "complete_todo"),
    ("check off the gym todo", "complete_todo"),
    ("I finished the report", "complete_todo"),
    ("show my todos", "list_todos"),
    ("what's on my list", "list_todos"),
    ("list open tasks", "list_todos"),
    ("create a task: buy milk", "create_todo"),
    ("add a todo for the meeting", "create_todo"),
    ("remind me to call Alice", "create_todo"),
    ("defer that task", "defer_todo"),
    ("snooze the report until Friday", "defer_todo"),
    ("postpone the gym todo", "defer_todo"),
    ("rename the task to 'buy groceries'", "edit_todo"),
    ("change the todo description", "edit_todo"),
    ("search my memories about auth", "search_memory_filtered"),
    ("find learnings from last week", "search_memory_filtered"),
    ("expand that memory item", "expand_memory"),
    ("show full content of the memory", "expand_memory"),
    ("what is the meaning of life?", None),
    ("summarize my week", None),
    ("how are you?", None),
])
@pytest.mark.asyncio
async def test_classify_intent_regex(message, expected_tool):
    from src.llm.intent_classifier import classify_intent

    with patch(
        "src.llm.intent_classifier._haiku_classify",
        new=AsyncMock(return_value=None),
    ) as mock_haiku:
        result, method = await classify_intent(message)

    assert result == expected_tool
    if expected_tool is not None:
        assert method == "regex"
        mock_haiku.assert_not_called()


@pytest.mark.asyncio
async def test_classify_intent_haiku_fallback_detects_tool():
    from src.llm.intent_classifier import classify_intent

    with patch(
        "src.llm.intent_classifier._haiku_classify",
        new=AsyncMock(return_value="list_todos"),
    ) as mock:
        result, method = await classify_intent("could you pull up what I've got going on?")

    assert result == "list_todos"
    assert method == "haiku"
    mock.assert_called_once_with("could you pull up what I've got going on?")


@pytest.mark.asyncio
async def test_classify_intent_haiku_fallback_returns_none():
    from src.llm.intent_classifier import classify_intent

    with patch("src.llm.intent_classifier._haiku_classify", new=AsyncMock(return_value=None)):
        result, method = await classify_intent("tell me about my week")

    assert result is None
    assert method == "none"


@pytest.mark.asyncio
async def test_classify_intent_haiku_failure_falls_through():
    from src.llm.intent_classifier import classify_intent

    with patch(
        "src.llm.intent_classifier._haiku_classify",
        new=AsyncMock(side_effect=Exception("API error")),
    ):
        result, method = await classify_intent("do the thing")

    assert result is None
