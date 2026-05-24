"""Memory tool schemas and handlers for chat tool-use."""
from __future__ import annotations

import json
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.services.memory_service import (
    MemoryItemNotFound,
    SupersedesInvalidUUID,
    expand_memory,
    search_memory_filtered,
)
from src.llm.tool_agent import ToolError

logger = structlog.get_logger(__name__)

MEMORY_TOOLS: list[dict] = [
    {
        "name": "search_memory_filtered",
        "description": (
            "Search your personal memory store with optional filters. "
            "Returns matching items with IDs, content, type, importance score, and project."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"},
                "type": {
                    "type": "string",
                    "description": "Filter by memory type: learning, decision, todo, daily_pulse, etc.",
                },
                "date_from": {
                    "type": "string",
                    "description": "ISO date lower bound, e.g. 2026-05-01",
                },
                "date_to": {
                    "type": "string",
                    "description": "ISO date upper bound, e.g. 2026-05-31",
                },
                "project": {"type": "string", "description": "Filter by project tag"},
                "importance_min": {
                    "type": "number",
                    "description": "Minimum importance score (0.0 to 1.0)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "expand_memory",
        "description": (
            "Get the full content, raw source text, and neighboring items for a specific memory. "
            "Use after search_memory_filtered when you need complete details."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "UUID of the memory item to expand",
                },
            },
            "required": ["memory_id"],
        },
    },
]


async def handle_search_memory_filtered(
    tool_name: str,
    args: dict,
    session: AsyncSession,
    user_id: uuid.UUID,
) -> str:
    query = args.get("query")
    if not query:
        raise ToolError("search_memory_filtered requires a 'query' argument")

    results = await search_memory_filtered(
        session,
        query=query,
        type=args.get("type"),
        date_from=args.get("date_from"),
        date_to=args.get("date_to"),
        project=args.get("project"),
        importance_min=args.get("importance_min"),
    )
    return json.dumps([
        {
            "id": r.id,
            "content": r.content,
            "type": r.type,
            "importance_score": r.importance_score,
            "project": r.project,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in results
    ])


async def handle_expand_memory(
    tool_name: str,
    args: dict,
    session: AsyncSession,
    user_id: uuid.UUID,
) -> str:
    memory_id = args.get("memory_id")
    if not memory_id:
        raise ToolError("expand_memory requires a 'memory_id' argument")

    try:
        result = await expand_memory(session, memory_id=memory_id)
    except (MemoryItemNotFound, SupersedesInvalidUUID) as exc:
        raise ToolError(str(exc)) from exc

    return json.dumps({
        "memory_id": result.memory_id,
        "content": result.content,
        "raw_text": result.raw_text,
        "neighbors": [
            {
                "memory_id": n.memory_id,
                "content": n.content,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in result.neighbors
        ],
        "metadata": result.metadata,
    })


MEMORY_HANDLERS: dict = {
    "search_memory_filtered": handle_search_memory_filtered,
    "expand_memory": handle_expand_memory,
}
