"""Sync TodoItem mutations into memory_items for hybrid search visibility.

Every todo create/update/complete/cancel produces a corresponding memory_item
so that "what are my todos?" queries work through the existing RAG pipeline.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import MemoryItem, RawMemory
from src.pipeline.embedder import embed_text

logger = structlog.get_logger(__name__)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _priority_to_importance(priority: str) -> float:
    """Map todo priority to base_importance."""
    return {"high": 0.7, "normal": 0.5, "low": 0.3}.get(priority, 0.5)


def _format_todo_content(todo, event_type: str) -> tuple[str, str]:
    """Return (content_text, memory_type) for embedding.

    memory_type: "todo" for open/updated/reopened, "todo_completion" for completed.
    """
    if event_type == "completed":
        parts = [f"Completed todo: {todo.description}"]
        parts.append(f"Priority: {todo.priority}")
        if todo.updated_at:
            parts.append(f"Completed: {todo.updated_at.strftime('%Y-%m-%d')}")
        if todo.label:
            parts.append(f"Label: {todo.label}")
        return " | ".join(parts), "todo_completion"

    # All other events produce an active todo memory
    parts = [f"Todo: {todo.description}"]
    parts.append(f"Priority: {todo.priority} | Status: {todo.status}")
    if todo.due_date:
        parts.append(f"Due: {todo.due_date.strftime('%Y-%m-%d')}")
    if todo.label:
        parts.append(f"Label: {todo.label}")
    return " | ".join(parts), "todo"


# ── Main sync function ──────────────────────────────────────────────────────


async def sync_todo_to_memory(
    session: AsyncSession,
    todo,
    event_type: str,
    voyage_client,
) -> None:
    """Sync a TodoItem mutation to memory_items.

    1. Format content string from todo fields + event_type
    2. Generate embedding via embed_text()
    3. Find & supersede existing memory_item(s) for this todo_id
    4. Create RawMemory(source="todo", metadata_={"todo_id": str(todo.id)})
    5. Create MemoryItem(type=..., content=..., embedding=..., raw_id=...)
    6. Commit
    """
    todo_id_str = str(todo.id)
    content, memory_type = _format_todo_content(todo, event_type)

    # Generate embedding
    embedding = await embed_text(content, voyage_client)

    # Find and supersede existing memory_items for this todo
    existing = await session.execute(
        select(MemoryItem)
        .join(RawMemory, MemoryItem.raw_id == RawMemory.id)
        .where(
            and_(
                RawMemory.metadata_["todo_id"].as_string() == todo_id_str,
                MemoryItem.is_superseded.is_(False),
            )
        )
        .order_by(MemoryItem.created_at.desc())
    )
    for old_item in existing.scalars():
        old_item.is_superseded = True

    # Create new raw memory
    raw = RawMemory(
        source="todo",
        raw_text=content,
        metadata_={"todo_id": todo_id_str},
    )
    session.add(raw)
    await session.flush()  # populate raw.id

    # Create new memory item
    memory_item = MemoryItem(
        raw_id=raw.id,
        type=memory_type,
        content=content,
        base_importance=_priority_to_importance(todo.priority),
        embedding=embedding,
    )
    session.add(memory_item)
    await session.commit()

    logger.info(
        "todo_synced_to_memory",
        todo_id=todo_id_str,
        event_type=event_type,
        memory_type=memory_type,
        memory_id=str(memory_item.id),
    )


async def supersede_memory_for_todo(
    session: AsyncSession,
    todo_id: UUID,
) -> int:
    """Mark all non-superseded memory_items for a given todo as superseded.

    Returns the number of rows updated. Safe to call before or after the
    TodoItem row is deleted — the query only touches RawMemory + MemoryItem
    via the ``todo_id`` key stored in ``RawMemory.metadata_``.

    Used by the hard-delete path in ``DELETE /v1/todos/{todo_id}`` so that
    vanished todos do not leave orphaned embeddings in hybrid search.
    """
    todo_id_str = str(todo_id)
    result = await session.execute(
        select(MemoryItem)
        .join(RawMemory, MemoryItem.raw_id == RawMemory.id)
        .where(
            and_(
                RawMemory.metadata_["todo_id"].as_string() == todo_id_str,
                MemoryItem.is_superseded.is_(False),
            )
        )
    )
    items = list(result.scalars())
    for item in items:
        item.is_superseded = True
    if items:
        logger.info(
            "todo_memory_superseded",
            todo_id=todo_id_str,
            count=len(items),
        )
    return len(items)
