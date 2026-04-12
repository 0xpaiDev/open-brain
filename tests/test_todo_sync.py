"""Tests for the todo → memory_items sync pipeline.

Covers:
  - Content formatting for open and completed todos
  - Priority-to-importance mapping
  - Full DB sync: creates RawMemory + MemoryItem
  - Supersession on update
  - Completion creates both supersession + todo_completion memory
  - Cancellation supersedes without completion memory
  - Graceful failure when embedding fails
  - Skip when no embedding client
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from src.core.models import MemoryItem, RawMemory, TodoItem
from src.pipeline.todo_sync import (
    _format_todo_content,
    _priority_to_importance,
    sync_todo_to_memory,
)

# ── Unit tests ───────────────────────────────────────────────────────────────


def test_format_todo_content_open():
    """Open todo produces type='todo' with description and status."""
    todo = MagicMock()
    todo.description = "Fix deployment script"
    todo.priority = "high"
    todo.status = "open"
    todo.due_date = datetime(2026, 4, 10, tzinfo=UTC)
    todo.label = "work"

    content, memory_type = _format_todo_content(todo, "created")

    assert memory_type == "todo"
    assert "Todo: Fix deployment script" in content
    assert "Priority: high" in content
    assert "Status: open" in content
    assert "Due: 2026-04-10" in content
    assert "Label: work" in content


def test_format_todo_content_completed():
    """Completed todo produces type='todo_completion'."""
    todo = MagicMock()
    todo.description = "Fix deployment script"
    todo.priority = "high"
    todo.updated_at = datetime(2026, 4, 7, tzinfo=UTC)
    todo.label = "work"

    content, memory_type = _format_todo_content(todo, "completed")

    assert memory_type == "todo_completion"
    assert "Completed todo: Fix deployment script" in content
    assert "Completed: 2026-04-07" in content
    assert "Label: work" in content


def test_format_todo_content_no_optional_fields():
    """Todo without due_date and label omits those fields."""
    todo = MagicMock()
    todo.description = "Buy milk"
    todo.priority = "low"
    todo.status = "open"
    todo.due_date = None
    todo.label = None

    content, memory_type = _format_todo_content(todo, "created")

    assert memory_type == "todo"
    assert "Due:" not in content
    assert "Label:" not in content


def test_priority_to_importance():
    """Priority maps to expected importance values."""
    assert _priority_to_importance("high") == 0.7
    assert _priority_to_importance("normal") == 0.5
    assert _priority_to_importance("low") == 0.3
    assert _priority_to_importance("unknown") == 0.5  # default


# ── DB integration tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_creates_raw_memory_and_memory_item(async_session):
    """sync_todo_to_memory() creates RawMemory(source='todo') and MemoryItem(type='todo')."""
    todo = TodoItem(description="Deploy auth service", priority="high")
    async_session.add(todo)
    await async_session.commit()
    await async_session.refresh(todo)

    mock_voyage = AsyncMock()
    mock_voyage.embed = AsyncMock(return_value=[0.1] * 1024)

    with patch("src.pipeline.todo_sync.embed_text", new_callable=AsyncMock, return_value=[0.1] * 1024):
        await sync_todo_to_memory(async_session, todo, "created", mock_voyage)

    # Verify RawMemory created
    raw_result = await async_session.execute(
        select(RawMemory).where(RawMemory.source == "todo")
    )
    raw = raw_result.scalar_one()
    assert raw.metadata_["todo_id"] == str(todo.id)

    # Verify MemoryItem created
    mi_result = await async_session.execute(
        select(MemoryItem).where(MemoryItem.raw_id == raw.id)
    )
    mi = mi_result.scalar_one()
    assert mi.type == "todo"
    assert "Deploy auth service" in mi.content
    assert float(mi.base_importance) == 0.7


@pytest.mark.asyncio
async def test_sync_supersedes_on_update(async_session):
    """Updating a todo supersedes the old memory_item."""
    todo = TodoItem(description="Original task", priority="normal")
    async_session.add(todo)
    await async_session.commit()
    await async_session.refresh(todo)

    with patch("src.pipeline.todo_sync.embed_text", new_callable=AsyncMock, return_value=[0.1] * 1024):
        await sync_todo_to_memory(async_session, todo, "created", AsyncMock())

    # Update description
    todo.description = "Updated task"
    await async_session.commit()

    with patch("src.pipeline.todo_sync.embed_text", new_callable=AsyncMock, return_value=[0.2] * 1024):
        await sync_todo_to_memory(async_session, todo, "updated", AsyncMock())

    # Old should be superseded, new should not
    mi_result = await async_session.execute(
        select(MemoryItem).order_by(MemoryItem.created_at)
    )
    items = mi_result.scalars().all()
    assert len(items) == 2
    assert items[0].is_superseded is True
    assert items[1].is_superseded is False
    assert "Updated task" in items[1].content


@pytest.mark.asyncio
async def test_sync_completion_creates_both_memories(async_session):
    """Completing a todo supersedes the old 'todo' and creates a 'todo_completion'."""
    todo = TodoItem(description="Ship feature", priority="high")
    async_session.add(todo)
    await async_session.commit()
    await async_session.refresh(todo)

    with patch("src.pipeline.todo_sync.embed_text", new_callable=AsyncMock, return_value=[0.1] * 1024):
        await sync_todo_to_memory(async_session, todo, "created", AsyncMock())

    # Complete the todo
    todo.status = "done"
    todo.updated_at = datetime(2026, 4, 7, tzinfo=UTC)
    await async_session.commit()

    with patch("src.pipeline.todo_sync.embed_text", new_callable=AsyncMock, return_value=[0.2] * 1024):
        await sync_todo_to_memory(async_session, todo, "completed", AsyncMock())

    mi_result = await async_session.execute(
        select(MemoryItem).order_by(MemoryItem.created_at)
    )
    items = mi_result.scalars().all()
    assert len(items) == 2
    assert items[0].is_superseded is True  # old "todo" superseded
    assert items[0].type == "todo"
    assert items[1].is_superseded is False
    assert items[1].type == "todo_completion"
    assert "Completed todo: Ship feature" in items[1].content


@pytest.mark.asyncio
async def test_sync_cancelled_supersedes_without_completion(async_session):
    """Cancelling a todo supersedes the old memory but does NOT create a todo_completion."""
    todo = TodoItem(description="Maybe later", priority="low")
    async_session.add(todo)
    await async_session.commit()
    await async_session.refresh(todo)

    with patch("src.pipeline.todo_sync.embed_text", new_callable=AsyncMock, return_value=[0.1] * 1024):
        await sync_todo_to_memory(async_session, todo, "created", AsyncMock())

    # Cancel
    todo.status = "cancelled"
    await async_session.commit()

    with patch("src.pipeline.todo_sync.embed_text", new_callable=AsyncMock, return_value=[0.2] * 1024):
        await sync_todo_to_memory(async_session, todo, "cancelled", AsyncMock())

    mi_result = await async_session.execute(
        select(MemoryItem).order_by(MemoryItem.created_at)
    )
    items = mi_result.scalars().all()
    assert len(items) == 2
    assert items[0].is_superseded is True
    assert items[0].type == "todo"
    assert items[1].is_superseded is False
    assert items[1].type == "todo"  # cancelled produces type="todo", not "todo_completion"


@pytest.mark.asyncio
async def test_sync_graceful_failure(async_session):
    """sync_todo_to_memory() raises on embedding failure (caller catches)."""
    todo = TodoItem(description="Will fail", priority="normal")
    async_session.add(todo)
    await async_session.commit()
    await async_session.refresh(todo)

    with patch("src.pipeline.todo_sync.embed_text", new_callable=AsyncMock, side_effect=RuntimeError("embed failed")):
        with pytest.raises(RuntimeError, match="embed failed"):
            await sync_todo_to_memory(async_session, todo, "created", AsyncMock())


@pytest.mark.asyncio
async def test_try_sync_skipped_when_no_embedding_client(async_session):
    """_try_sync logs warning and returns without error when embedding_client is None."""
    from structlog.testing import capture_logs

    from src.api.services.todo_service import _try_sync

    todo = TodoItem(description="No client", priority="normal")
    async_session.add(todo)
    await async_session.commit()
    await async_session.refresh(todo)

    with patch("src.llm.client.embedding_client", None):
        with capture_logs() as cap:
            await _try_sync(async_session, todo, "created")

    skip_events = [e for e in cap if e.get("event") == "todo_sync_skipped_no_embedding_client"]
    assert len(skip_events) == 1
