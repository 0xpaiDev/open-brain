"""Test ChatLog ORM model can be written and queried."""

import pytest
from sqlalchemy import select

from src.core.models import ChatLog


@pytest.mark.asyncio
async def test_chat_log_can_be_created(async_session):
    log = ChatLog(
        user_message="show my todos",
        tools_enabled=True,
        intent_tool="list_todos",
        intent_method="regex",
        llm_calls=[{"turn_index": 0, "model": "claude-sonnet-4-6", "stop_reason": "end_turn"}],
        tool_calls=[{"tool_name": "list_todos", "args": {}, "result": "[]", "duration_ms": 5, "is_error": False}],
        response_text="You have no open todos.",
        model_used="claude-sonnet-4-6",
        duration_ms=250,
    )
    async_session.add(log)
    await async_session.commit()
    await async_session.refresh(log)

    result = await async_session.execute(select(ChatLog).where(ChatLog.id == log.id))
    fetched = result.scalar_one()
    assert fetched.intent_tool == "list_todos"
    assert fetched.llm_calls[0]["stop_reason"] == "end_turn"
    assert fetched.tools_enabled is True


@pytest.mark.asyncio
async def test_chat_log_minimal(async_session):
    log = ChatLog(
        user_message="hello",
        tools_enabled=False,
    )
    async_session.add(log)
    await async_session.commit()
    await async_session.refresh(log)

    assert log.id is not None
    assert log.intent_tool is None
    assert log.duration_ms is None
