"""Chat tool registry — aggregates all tool schemas and dispatches calls.

Populated by domain tool modules in PR2. Empty stub in PR1.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.llm.tool_agent import ToolError

ALL_TOOLS: list[dict] = []
_DISPATCH_TABLE: dict = {}


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
