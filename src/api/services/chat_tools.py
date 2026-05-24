"""Chat tool registry — aggregates all tool schemas and dispatches calls."""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.services.memory_tools import MEMORY_HANDLERS, MEMORY_TOOLS
from src.api.services.todo_tools import TODO_HANDLERS, TODO_TOOLS
from src.llm.tool_agent import ToolError

ALL_TOOLS: list[dict] = MEMORY_TOOLS + TODO_TOOLS
_DISPATCH_TABLE: dict = {**MEMORY_HANDLERS, **TODO_HANDLERS}


async def dispatch(
    tool_name: str,
    args: dict,
    session: AsyncSession,
    user_id: uuid.UUID,
) -> str:
    handler = _DISPATCH_TABLE.get(tool_name)
    if handler is None:
        raise ToolError(f"Unknown tool: {tool_name}")
    return await handler(tool_name, args, session, user_id)
