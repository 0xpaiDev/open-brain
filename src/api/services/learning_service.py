"""Business logic for the learning library.

Keeps routes thin; centralises the topic→section→item invariants and the
cron-side selection logic. Learning data never flows through memory_service —
learning todos follow the normal todo_sync path because they are real todos.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.models import (
    LearningItem,
    LearningSection,
    LearningTopic,
    TodoItem,
)

logger = structlog.get_logger(__name__)


async def load_tree(session: AsyncSession) -> list[LearningTopic]:
    """Return all topics with sections+items eagerly loaded, ordered by position."""
    stmt = (
        select(LearningTopic)
        .options(selectinload(LearningTopic.sections).selectinload(LearningSection.items))
        .order_by(LearningTopic.position, LearningTopic.created_at)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_topic(session: AsyncSession, topic_id: uuid.UUID) -> LearningTopic | None:
    return await session.get(LearningTopic, topic_id)


async def get_section(session: AsyncSession, section_id: uuid.UUID) -> LearningSection | None:
    return await session.get(LearningSection, section_id)


async def get_item(session: AsyncSession, item_id: uuid.UUID) -> LearningItem | None:
    return await session.get(LearningItem, item_id)


async def cascade_item_completion(
    session: AsyncSession,
    todo: TodoItem,
    *,
    feedback: str | None = None,
    notes: str | None = None,
) -> LearningItem | None:
    """If `todo` was generated from a learning item, mark it done + persist feedback/notes.

    Best-effort: caller wraps in try/except so a cascade failure never blocks
    the todo update. Returns the item when mutated, None otherwise.
    """
    if todo.learning_item_id is None:
        return None
    item = await session.get(LearningItem, todo.learning_item_id)
    if item is None:
        return None
    item.status = "done"
    item.completed_at = datetime.now(UTC)
    if feedback is not None:
        item.feedback = feedback
    if notes is not None:
        item.notes = notes
    await session.flush()
    await session.commit()
    logger.info("learning_item_cascade_completed", item_id=str(item.id), todo_id=str(todo.id))
    return item


async def cancel_matching_open_todo_for_item(
    session: AsyncSession,
    item_id: uuid.UUID,
) -> TodoItem | None:
    """When an item is completed directly on /learning, cancel any still-open
    todo pointing at it. Best-effort, safe to call when nothing matches.
    """
    stmt = select(TodoItem).where(
        TodoItem.learning_item_id == item_id,
        TodoItem.status == "open",
    )
    result = await session.execute(stmt)
    todo = result.scalars().first()
    if todo is None:
        return None
    todo.status = "cancelled"
    await session.flush()
    await session.commit()
    logger.info("learning_item_cancelled_matching_todo", todo_id=str(todo.id), item_id=str(item_id))
    return todo


def item_to_dict(item: LearningItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "section_id": str(item.section_id),
        "title": item.title,
        "status": item.status,
        "feedback": item.feedback,
        "notes": item.notes,
        "position": item.position,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def section_to_dict(section: LearningSection, include_items: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(section.id),
        "topic_id": str(section.topic_id),
        "name": section.name,
        "position": section.position,
    }
    if include_items:
        out["items"] = [item_to_dict(i) for i in section.items]
    return out


def topic_to_dict(topic: LearningTopic, include_children: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(topic.id),
        "name": topic.name,
        "description": topic.description,
        "depth": topic.depth,
        "is_active": topic.is_active,
        "position": topic.position,
    }
    if include_children:
        out["sections"] = [section_to_dict(s) for s in topic.sections]
    return out
