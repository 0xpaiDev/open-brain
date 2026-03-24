"""Business logic for todo management.

Keeps history writes atomic with todo mutations — callers should not
write history rows directly; use these service functions instead.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import TodoHistory, TodoItem

logger = structlog.get_logger(__name__)


def _snapshot(todo: TodoItem) -> dict[str, Any]:
    """Return a plain dict snapshot of a todo's mutable fields."""
    return {
        "description": todo.description,
        "priority": todo.priority,
        "status": todo.status,
        "due_date": todo.due_date.isoformat() if todo.due_date else None,
    }


async def create_todo(
    session: AsyncSession,
    description: str,
    priority: str = "normal",
    due_date: datetime | None = None,
) -> TodoItem:
    """Insert a TodoItem and a 'created' history row in one transaction.

    Args:
        session: Async DB session (caller owns the session lifecycle).
        description: Required todo text.
        priority: "high" | "normal" | "low" (default "normal").
        due_date: Optional due date.

    Returns:
        The newly created TodoItem with id populated.
    """
    todo = TodoItem(description=description, priority=priority, due_date=due_date)
    session.add(todo)
    await session.flush()  # Populate todo.id before writing history

    history = TodoHistory(
        todo_id=todo.id,
        event_type="created",
        new_value=_snapshot(todo),
    )
    session.add(history)
    await session.flush()
    await session.commit()
    await session.refresh(todo)  # Eagerly reload server-default columns (created_at, updated_at)

    logger.info("create_todo", todo_id=str(todo.id))
    return todo


async def update_todo(
    session: AsyncSession,
    todo: TodoItem,
    *,
    description: str | None = None,
    priority: str | None = None,
    due_date: datetime | None = None,
    status: str | None = None,
    reason: str | None = None,
) -> TodoItem:
    """Apply field updates to a TodoItem and append a history row.

    Determines event_type automatically:
      - status → "completed" | "cancelled" | "priority_changed" based on field
      - due_date change → "deferred"
      - description only → "updated"

    Args:
        session: Async DB session (caller owns the session lifecycle).
        todo: The fetched TodoItem to update (must be tracked by session).
        description: New description text (optional).
        priority: New priority value (optional).
        due_date: New due date (optional).
        status: New status value (optional).
        reason: Stored in history for deferrals; optional otherwise.

    Returns:
        The updated TodoItem.
    """
    old_snapshot = _snapshot(todo)

    if description is not None:
        todo.description = description
    if priority is not None:
        todo.priority = priority
    if due_date is not None:
        todo.due_date = due_date
    if status is not None:
        todo.status = status

    new_snapshot = _snapshot(todo)

    # Determine event_type
    if status == "done":
        event_type = "completed"
    elif status == "cancelled":
        event_type = "cancelled"
    elif due_date is not None and status is None and priority is None and description is None:
        event_type = "deferred"
    elif priority is not None and status is None:
        event_type = "priority_changed"
    else:
        event_type = "updated"

    history = TodoHistory(
        todo_id=todo.id,
        event_type=event_type,
        old_value=old_snapshot,
        new_value=new_snapshot,
        reason=reason,
    )
    session.add(history)
    await session.flush()
    await session.commit()
    await session.refresh(todo)  # Eagerly reload server-side onupdate columns (updated_at)

    logger.info("update_todo", todo_id=str(todo.id), event_type=event_type)
    return todo
