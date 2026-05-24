"""Tests for the chat_tools dispatch table."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_dispatch_known_tool(async_session):
    from src.api.services.chat_tools import dispatch

    result = await dispatch("list_todos", {}, async_session, uuid.UUID(int=0))
    data = __import__("json").loads(result)
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_raises(async_session):
    from src.api.services.chat_tools import dispatch
    from src.llm.tool_agent import ToolError

    with pytest.raises(ToolError, match="Unknown tool"):
        await dispatch("nonexistent_tool", {}, async_session, uuid.UUID(int=0))


def test_all_tools_list_has_seven_entries():
    from src.api.services.chat_tools import ALL_TOOLS

    names = {t["name"] for t in ALL_TOOLS}
    assert names == {
        "search_memory_filtered",
        "expand_memory",
        "list_todos",
        "create_todo",
        "complete_todo",
        "defer_todo",
        "edit_todo",
    }
