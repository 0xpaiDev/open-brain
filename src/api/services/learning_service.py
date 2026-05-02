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
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.schemas.learning_import import (
    ImportResult,
    ImportSkip,
    LearningImportRequest,
    MaterialUpdate,
)
from src.core.models import (
    LearningItem,
    LearningMaterial,
    LearningSection,
    LearningTopic,
    TodoItem,
)

logger = structlog.get_logger(__name__)


async def load_tree(session: AsyncSession) -> list[LearningTopic]:
    """Return all topics with sections+items+material eagerly loaded, ordered by position."""
    stmt = (
        select(LearningTopic)
        .options(
            selectinload(LearningTopic.sections).selectinload(LearningSection.items),
            selectinload(LearningTopic.material),
        )
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
        # material is eagerly loaded by load_tree — safe to access here
        out["has_material"] = topic.material is not None
        out["sections"] = [section_to_dict(s) for s in topic.sections]
    return out


def material_to_dict(m: LearningMaterial) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "topic_id": str(m.topic_id),
        "content": m.content,
        "source_type": m.source_type,
        "source_url": m.source_url,
        "source_title": m.source_title,
        "metadata": m.metadata_json,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


async def get_material(
    session: AsyncSession, topic_id: uuid.UUID
) -> LearningMaterial | None:
    stmt = select(LearningMaterial).where(LearningMaterial.topic_id == topic_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def upsert_material(
    session: AsyncSession, topic_id: uuid.UUID, body: MaterialUpdate
) -> LearningMaterial:
    stmt = select(LearningMaterial).where(LearningMaterial.topic_id == topic_id)
    material = (await session.execute(stmt)).scalar_one_or_none()
    if material is None:
        material = LearningMaterial(
            topic_id=topic_id,
            content=body.content,
            source_type=body.source_type,
            source_url=body.source_url,
            source_title=body.source_title,
            metadata_json=body.metadata,
        )
        session.add(material)
    else:
        material.content = body.content
        material.source_type = body.source_type
        material.source_url = body.source_url
        material.source_title = body.source_title
        material.metadata_json = body.metadata
    await session.commit()
    await session.refresh(material)
    return material


async def delete_material(session: AsyncSession, topic_id: uuid.UUID) -> bool:
    """Delete material for a topic. Returns True if deleted, False if none existed."""
    stmt = select(LearningMaterial).where(LearningMaterial.topic_id == topic_id)
    material = (await session.execute(stmt)).scalar_one_or_none()
    if material is None:
        return False
    await session.delete(material)
    await session.commit()
    return True


async def import_curriculum(
    session: AsyncSession,
    request: LearningImportRequest,
    *,
    dry_run: bool,
) -> ImportResult:
    """Bulk-import a curriculum tree from a structured JSON document.

    Dedup is case-insensitive on topic name. On dry_run=True, no rows are written.
    On failure during commit, all adds are rolled back atomically.
    """
    # Load existing topic names for case-insensitive dedup
    existing_rows = await session.execute(select(LearningTopic.name))
    existing_names: set[str] = {row[0].lower() for row in existing_rows}

    to_create = []
    to_skip = []
    for topic_req in request.topics:
        if topic_req.name.lower() in existing_names:
            to_skip.append(ImportSkip(name=topic_req.name, reason="name_collision"))
        else:
            to_create.append(topic_req)
            # Add to set so duplicate names within the same payload are also caught
            existing_names.add(topic_req.name.lower())

    topics_created = len(to_create)
    sections_created = sum(len(t.sections) for t in to_create)
    items_created = sum(
        len(s.items) for t in to_create for s in t.sections
    )
    materials_created = sum(1 for t in to_create if t.material is not None)

    if dry_run:
        return ImportResult(
            dry_run=True,
            topics_created=topics_created,
            sections_created=sections_created,
            items_created=items_created,
            materials_created=materials_created,
            topics_skipped=to_skip,
            created_topic_ids=[],
        )

    # Compute starting position — fix: use explicit None check to handle MAX=0
    max_pos = await session.scalar(select(func.max(LearningTopic.position)))
    start_pos: int = max_pos if max_pos is not None else -1

    created_topics: list[LearningTopic] = []
    try:
        for idx, topic_req in enumerate(to_create):
            topic = LearningTopic(
                name=topic_req.name,
                description=topic_req.description,
                depth=topic_req.depth,
                position=start_pos + 1 + idx,
            )
            session.add(topic)
            created_topics.append(topic)

            for s_idx, section_req in enumerate(topic_req.sections):
                section = LearningSection(
                    topic=topic,
                    name=section_req.name,
                    position=s_idx,
                )
                session.add(section)

                for i_idx, item_req in enumerate(section_req.items):
                    item = LearningItem(
                        section=section,
                        title=item_req.title,
                        position=i_idx,
                    )
                    session.add(item)

            if topic_req.material is not None:
                mat = topic_req.material
                material = LearningMaterial(
                    topic=topic,
                    content=mat.content,
                    source_type=mat.source_type,
                    source_url=mat.source_url,
                    source_title=mat.source_title,
                    metadata_json=mat.metadata,
                )
                session.add(material)

        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.error("learning_import_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Import failed: {exc!s}") from exc

    for topic in created_topics:
        await session.refresh(topic)

    return ImportResult(
        dry_run=False,
        topics_created=topics_created,
        sections_created=sections_created,
        items_created=items_created,
        materials_created=materials_created,
        topics_skipped=to_skip,
        created_topic_ids=[str(t.id) for t in created_topics],
    )
