#!/usr/bin/env python3
"""One-time backfill: sync all existing TodoItems into memory_items.

Run via: python -m scripts.backfill_todo_memories

For completed todos, this creates only a todo_completion memory.
The normal flow would first supersede an existing type="todo" memory,
but during backfill there is no prior memory to supersede. Historical
completed todos get a completion record only — the completion record
contains the full description and is searchable.
"""

import asyncio

import structlog

from src.core.database import get_db_context, init_db
from src.core.models import TodoItem
from src.llm.client import embedding_client
from src.pipeline.todo_sync import sync_todo_to_memory

logger = structlog.get_logger(__name__)


async def backfill() -> None:
    await init_db()

    if not embedding_client:
        logger.error("backfill_no_embedding_client")
        return

    failed = 0
    total = 0

    async with get_db_context() as session:
        from sqlalchemy import select

        result = await session.execute(select(TodoItem))
        for todo in result.scalars():
            total += 1
            try:
                event = "completed" if todo.status == "done" else "created"
                await sync_todo_to_memory(session, todo, event, embedding_client)
            except Exception:
                failed += 1
                logger.warning("backfill_todo_failed", todo_id=str(todo.id), exc_info=True)

    logger.info("backfill_complete", total=total, failed=failed)


if __name__ == "__main__":
    asyncio.run(backfill())
