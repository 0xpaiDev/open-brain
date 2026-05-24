"""Todo tool schemas and handlers for chat tool-use."""
from __future__ import annotations

import json
import uuid
from datetime import datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.services.todo_service import create_todo, list_todos, update_todo
from src.core.models import TodoItem
from src.llm.tool_agent import ToolError

logger = structlog.get_logger(__name__)

TODO_TOOLS: list[dict] = [
    {
        "name": "list_todos",
        "description": "List todos with optional filters for status, due date, or project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status: open, done, cancelled",
                },
                "due_before": {
                    "type": "string",
                    "description": "ISO date — only todos due before this date",
                },
                "project": {"type": "string", "description": "Filter by project tag"},
            },
        },
    },
    {
        "name": "create_todo",
        "description": "Create a new todo item.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "The todo text (required)"},
                "priority": {
                    "type": "string",
                    "description": "high, normal, or low (default: normal)",
                },
                "due_date": {
                    "type": "string",
                    "description": "Optional ISO date for due date",
                },
                "project": {"type": "string", "description": "Optional project tag"},
            },
            "required": ["description"],
        },
    },
    {
        "name": "complete_todo",
        "description": "Mark a todo as done.",
        "input_schema": {
            "type": "object",
            "properties": {
                "todo_id": {"type": "string", "description": "UUID of the todo to complete"},
                "reason": {"type": "string", "description": "Optional reason or note"},
            },
            "required": ["todo_id"],
        },
    },
    {
        "name": "defer_todo",
        "description": "Defer (postpone) a todo to a later date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "todo_id": {"type": "string", "description": "UUID of the todo to defer"},
                "until_date": {
                    "type": "string",
                    "description": "ISO date to defer to (required)",
                },
                "reason": {"type": "string", "description": "Optional reason"},
            },
            "required": ["todo_id", "until_date"],
        },
    },
    {
        "name": "edit_todo",
        "description": "Edit a todo's description, priority, or project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "todo_id": {"type": "string", "description": "UUID of the todo to edit"},
                "description": {"type": "string", "description": "New description text"},
                "priority": {
                    "type": "string",
                    "description": "New priority: high, normal, or low",
                },
                "project": {"type": "string", "description": "New project tag"},
            },
            "required": ["todo_id"],
        },
    },
]


async def _get_todo(session: AsyncSession, todo_id: str) -> TodoItem:
    try:
        uid = uuid.UUID(todo_id)
    except ValueError as exc:
        raise ToolError(f"Invalid todo_id: {todo_id!r}") from exc

    todo = await session.get(TodoItem, uid)
    if todo is None:
        raise ToolError(f"Todo {todo_id} not found")
    return todo


async def handle_list_todos(
    tool_name: str, args: dict, session: AsyncSession, user_id: uuid.UUID
) -> str:
    todos = await list_todos(
        session,
        status=args.get("status"),
        due_before=args.get("due_before"),
        project=args.get("project"),
    )
    return json.dumps([
        {
            "id": str(t.id),
            "description": t.description,
            "status": t.status,
            "priority": t.priority,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "project": t.project,
        }
        for t in todos
    ])


async def handle_create_todo(
    tool_name: str, args: dict, session: AsyncSession, user_id: uuid.UUID
) -> str:
    description = args.get("description")
    if not description:
        raise ToolError("create_todo requires a 'description' argument")

    due_date = datetime.fromisoformat(args["due_date"]) if args.get("due_date") else None
    todo = await create_todo(
        session,
        description=description,
        priority=args.get("priority", "normal"),
        due_date=due_date,
        project=args.get("project"),
    )
    return json.dumps({"id": str(todo.id), "description": todo.description})


async def handle_complete_todo(
    tool_name: str, args: dict, session: AsyncSession, user_id: uuid.UUID
) -> str:
    todo = await _get_todo(session, args.get("todo_id", ""))
    await update_todo(session, todo, status="done", reason=args.get("reason"))
    return f"Marked '{todo.description}' as done."


async def handle_defer_todo(
    tool_name: str, args: dict, session: AsyncSession, user_id: uuid.UUID
) -> str:
    todo = await _get_todo(session, args.get("todo_id", ""))
    until_date_str = args.get("until_date")
    if not until_date_str:
        raise ToolError("defer_todo requires an 'until_date' argument")
    await update_todo(
        session, todo, due_date=datetime.fromisoformat(until_date_str), reason=args.get("reason")
    )
    return f"Deferred '{todo.description}' to {until_date_str}."


async def handle_edit_todo(
    tool_name: str, args: dict, session: AsyncSession, user_id: uuid.UUID
) -> str:
    todo = await _get_todo(session, args.get("todo_id", ""))
    fields = {k: args[k] for k in ("description", "priority", "project") if k in args}
    if not fields:
        raise ToolError("edit_todo requires at least one field to update")
    await update_todo(session, todo, **fields)
    changes = ", ".join(f"{k}='{v}'" for k, v in fields.items())
    return f"Updated '{todo.description}': {changes}."


TODO_HANDLERS: dict = {
    "list_todos": handle_list_todos,
    "create_todo": handle_create_todo,
    "complete_todo": handle_complete_todo,
    "defer_todo": handle_defer_todo,
    "edit_todo": handle_edit_todo,
}
