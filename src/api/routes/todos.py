"""Todo management endpoints.

POST   /v1/todos              — create todo
GET    /v1/todos              — list (filters: status, priority, due_before)
GET    /v1/todos/{id}         — fetch single
PATCH  /v1/todos/{id}         — update (writes TodoHistory in same transaction)
GET    /v1/todos/{id}/history — state change log
"""

import uuid as _uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import asc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import limiter, todos_limit
from src.api.services.todo_service import create_todo, update_todo
from src.core.database import get_db
from src.core.models import TodoHistory, TodoItem
from src.pipeline.todo_sync import supersede_memory_for_todo

logger = structlog.get_logger(__name__)

router = APIRouter()

_VALID_STATUSES = {"open", "done", "cancelled"}
_VALID_PRIORITIES = {"high", "normal", "low"}


# ── Pydantic models ────────────────────────────────────────────────────────────


class TodoCreate(BaseModel):
    description: str = Field(..., min_length=1, max_length=500)
    priority: str = "normal"
    due_date: datetime | None = None
    start_date: datetime | None = None
    label: str | None = Field(None, max_length=50)

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        if v not in _VALID_PRIORITIES:
            raise ValueError(f"priority must be one of {sorted(_VALID_PRIORITIES)}")
        return v

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str | None) -> str | None:
        if v is not None and len(v) < 1:
            raise ValueError("label must not be empty")
        return v


class TodoUpdate(BaseModel):
    description: str | None = Field(None, max_length=500)
    priority: str | None = None
    due_date: datetime | None = None
    start_date: datetime | None = None
    status: str | None = None
    reason: str | None = Field(None, max_length=500)  # stored in history only
    label: str | None = Field(None, max_length=50)

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_PRIORITIES:
            raise ValueError(f"priority must be one of {sorted(_VALID_PRIORITIES)}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(_VALID_STATUSES)}")
        return v


class TodoResponse(BaseModel):
    id: str
    description: str
    priority: str
    status: str
    due_date: datetime | None
    start_date: datetime | None
    label: str | None
    discord_message_id: str | None
    discord_channel_id: str | None
    created_at: datetime
    updated_at: datetime


class TodoListResponse(BaseModel):
    todos: list[TodoResponse]
    total: int


class TodoHistoryResponse(BaseModel):
    id: str
    todo_id: str
    event_type: str
    old_value: dict | None
    new_value: dict | None
    reason: str | None
    created_at: datetime


# ── Helpers ────────────────────────────────────────────────────────────────────


def _todo_to_response(todo: TodoItem) -> TodoResponse:
    return TodoResponse(
        id=str(todo.id),
        description=todo.description,
        priority=todo.priority,
        status=todo.status,
        due_date=todo.due_date,
        start_date=todo.start_date,
        label=todo.label,
        discord_message_id=todo.discord_message_id,
        discord_channel_id=todo.discord_channel_id,
        created_at=todo.created_at,
        updated_at=todo.updated_at,
    )


def _history_to_response(h: TodoHistory) -> TodoHistoryResponse:
    return TodoHistoryResponse(
        id=str(h.id),
        todo_id=str(h.todo_id),
        event_type=h.event_type,
        old_value=h.old_value,
        new_value=h.new_value,
        reason=h.reason,
        created_at=h.created_at,
    )


# ── POST /v1/todos ─────────────────────────────────────────────────────────────


@router.post("/v1/todos", response_model=TodoResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(todos_limit)
async def create_todo_route(
    request: Request,
    body: TodoCreate,
    session: AsyncSession = Depends(get_db),
) -> TodoResponse:
    """Create a new todo item with an initial history entry.

    Args:
        body: TodoCreate with description (required), priority, due_date.

    Returns:
        TodoResponse with the created todo.

    Raises:
        422: If description is empty or priority is invalid.
    """
    todo = await create_todo(
        session,
        description=body.description,
        priority=body.priority,
        due_date=body.due_date,
        start_date=body.start_date,
        label=body.label,
    )
    logger.info("create_todo_route", todo_id=str(todo.id))
    return _todo_to_response(todo)


# ── GET /v1/todos ──────────────────────────────────────────────────────────────


@router.get("/v1/todos", response_model=TodoListResponse)
@limiter.limit(todos_limit)
async def list_todos(
    request: Request,
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    label: str | None = Query(default=None),
    due_before: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> TodoListResponse:
    """List todos with optional filters.

    Args:
        status: Filter by status (open/done/cancelled).
        priority: Filter by priority (high/normal/low).
        label: Filter by label name.
        due_before: Filter todos due before this datetime.
        limit: Maximum results (1–500).
        offset: Number of results to skip.

    Returns:
        TodoListResponse with matching todos and total count.
    """
    stmt = select(TodoItem)
    count_stmt = select(func.count()).select_from(TodoItem)

    if status is not None:
        stmt = stmt.where(TodoItem.status == status)
        count_stmt = count_stmt.where(TodoItem.status == status)
    if priority is not None:
        stmt = stmt.where(TodoItem.priority == priority)
        count_stmt = count_stmt.where(TodoItem.priority == priority)
    if label is not None:
        stmt = stmt.where(TodoItem.label == label)
        count_stmt = count_stmt.where(TodoItem.label == label)
    if due_before is not None:
        if due_before.tzinfo is None:
            due_before = due_before.replace(tzinfo=UTC)
        stmt = stmt.where(TodoItem.due_date <= due_before)
        count_stmt = count_stmt.where(TodoItem.due_date <= due_before)

    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.order_by(TodoItem.created_at.desc(), TodoItem.id.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    todos = list(result.scalars().all())

    logger.info("list_todos", total=total, returned=len(todos))
    return TodoListResponse(todos=[_todo_to_response(t) for t in todos], total=total)


# ── GET /v1/todos/overdue-undeferred ───────────────────────────────────────────


@router.get("/v1/todos/overdue-undeferred", response_model=list[TodoResponse])
@limiter.limit(todos_limit)
async def list_overdue_undeferred(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> list[TodoResponse]:
    """Return open todos that are overdue and have NOT been deferred today.

    Used by the frontend overdue enforcement modal to force the user to
    defer (with a reason) any task that slipped past its due date.

    Returns:
        List of TodoResponse for overdue, un-deferred tasks.
    """
    start_of_today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    deferred_today_sub = (
        select(TodoHistory.todo_id)
        .where(TodoHistory.event_type == "deferred")
        .where(TodoHistory.created_at >= start_of_today)
    ).subquery()

    stmt = (
        select(TodoItem)
        .where(TodoItem.status == "open")
        .where(TodoItem.due_date < start_of_today)
        .where(~TodoItem.id.in_(select(deferred_today_sub.c.todo_id)))
    )
    result = await session.execute(stmt)
    todos = list(result.scalars().all())

    logger.info("list_overdue_undeferred", count=len(todos))
    return [_todo_to_response(t) for t in todos]


# ── GET /v1/todos/{id} ─────────────────────────────────────────────────────────


@router.get("/v1/todos/{todo_id}", response_model=TodoResponse)
@limiter.limit(todos_limit)
async def get_todo(
    request: Request,
    todo_id: _uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> TodoResponse:
    """Fetch a single todo by ID.

    Returns:
        TodoResponse for the todo.

    Raises:
        404: If no todo with that ID exists.
        422: If todo_id is not a valid UUID.
    """
    todo = await session.get(TodoItem, todo_id)
    if todo is None:
        raise HTTPException(status_code=404, detail=f"Todo {todo_id} not found")
    return _todo_to_response(todo)


# ── PATCH /v1/todos/{id} ───────────────────────────────────────────────────────


@router.patch("/v1/todos/{todo_id}", response_model=TodoResponse)
@limiter.limit(todos_limit)
async def update_todo_route(
    request: Request,
    todo_id: _uuid.UUID,
    body: TodoUpdate,
    session: AsyncSession = Depends(get_db),
) -> TodoResponse:
    """Update a todo's fields and write a history row.

    Only non-None fields in the request body are applied.

    Returns:
        TodoResponse with updated todo.

    Raises:
        404: If no todo with that ID exists.
        422: If todo_id is invalid UUID or field values are invalid.
    """
    todo = await session.get(TodoItem, todo_id)
    if todo is None:
        raise HTTPException(status_code=404, detail=f"Todo {todo_id} not found")

    todo = await update_todo(
        session,
        todo,
        description=body.description,
        priority=body.priority,
        due_date=body.due_date,
        start_date=body.start_date,
        status=body.status,
        reason=body.reason,
        label=body.label,
        fields_set=body.model_fields_set,
    )
    logger.info("update_todo_route", todo_id=str(todo_id))
    return _todo_to_response(todo)


# ── DELETE /v1/todos/{id} ──────────────────────────────────────────────────────


@router.delete("/v1/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(todos_limit)
async def delete_todo_route(
    request: Request,
    todo_id: _uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Hard-delete a todo and supersede its memory items.

    The TodoHistory rows cascade on delete via the FK ``ondelete="CASCADE"``.
    Memory items tied to this todo are marked ``is_superseded=True`` before
    the delete so hybrid search no longer surfaces them.

    Raises:
        404: If no todo with that ID exists.
    """
    todo = await session.get(TodoItem, todo_id)
    if todo is None:
        raise HTTPException(status_code=404, detail=f"Todo {todo_id} not found")

    superseded = await supersede_memory_for_todo(session, todo_id)
    await session.delete(todo)
    await session.commit()
    logger.info(
        "delete_todo_route",
        todo_id=str(todo_id),
        superseded_memory_items=superseded,
    )


# ── GET /v1/todos/{id}/history ─────────────────────────────────────────────────


@router.get("/v1/todos/{todo_id}/history", response_model=list[TodoHistoryResponse])
@limiter.limit(todos_limit)
async def get_todo_history(
    request: Request,
    todo_id: _uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> list[TodoHistoryResponse]:
    """Return the full state-change history for a todo, oldest first.

    Returns:
        List of TodoHistoryResponse entries ordered by created_at ASC.

    Raises:
        404: If no todo with that ID exists.
        422: If todo_id is not a valid UUID.
    """
    todo = await session.get(TodoItem, todo_id)
    if todo is None:
        raise HTTPException(status_code=404, detail=f"Todo {todo_id} not found")

    stmt = (
        select(TodoHistory)
        .where(TodoHistory.todo_id == todo_id)
        .order_by(asc(TodoHistory.created_at))
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    return [_history_to_response(h) for h in rows]
