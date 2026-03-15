"""Task management endpoints.

GET   /v1/tasks              — list tasks with optional status/owner/due_before filters
POST  /v1/tasks              — create a task linked to a memory item
PATCH /v1/tasks/{task_id}    — update task status
"""

import uuid as _uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.models import MemoryItem, Task

logger = structlog.get_logger(__name__)

router = APIRouter()

_VALID_STATUSES = {"open", "done", "cancelled"}


# ── Pydantic models ────────────────────────────────────────────────────────────


class TaskCreate(BaseModel):
    memory_id: str
    description: str
    owner: str | None = None
    due_date: datetime | None = None
    status: str = "open"

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in _VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(_VALID_STATUSES)}")
        return v


class TaskStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in _VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(_VALID_STATUSES)}")
        return v


class TaskResponse(BaseModel):
    id: str
    memory_id: str
    description: str
    owner: str | None
    due_date: datetime | None
    status: str
    created_at: datetime


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int


# ── Helpers ────────────────────────────────────────────────────────────────────


def _parse_uuid(value: str, field: str = "id") -> _uuid.UUID:
    """Parse UUID string, raise 422 on failure."""
    try:
        return _uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{field} is not a valid UUID") from None


def _task_to_response(task: Task) -> TaskResponse:
    return TaskResponse(
        id=str(task.id),
        memory_id=str(task.memory_id),
        description=task.description,
        owner=task.owner,
        due_date=task.due_date,
        status=task.status,
        created_at=task.created_at,
    )


# ── GET /v1/tasks ──────────────────────────────────────────────────────────────


@router.get("/v1/tasks", response_model=TaskListResponse)
async def list_tasks(
    status: str | None = Query(default=None),
    owner: str | None = Query(default=None),
    due_before: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> TaskListResponse:
    """List tasks with optional filters.

    Args:
        status: Filter by task status (open/done/cancelled).
        owner: Filter by owner name (exact match).
        due_before: Filter tasks due before this datetime.
        limit: Maximum results to return (1–500).
        offset: Number of results to skip.

    Returns:
        TaskListResponse with matching tasks and total count.

    Raises:
        422: If due_before cannot be parsed as a datetime.
    """
    stmt = select(Task)
    count_stmt = select(func.count()).select_from(Task)

    if status is not None:
        stmt = stmt.where(Task.status == status)
        count_stmt = count_stmt.where(Task.status == status)
    if owner is not None:
        stmt = stmt.where(Task.owner == owner)
        count_stmt = count_stmt.where(Task.owner == owner)
    if due_before is not None:
        # Coerce naive datetime to UTC for timezone-aware DB column
        if due_before.tzinfo is None:
            due_before = due_before.replace(tzinfo=timezone.utc)
        stmt = stmt.where(Task.due_date <= due_before)
        count_stmt = count_stmt.where(Task.due_date <= due_before)

    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    tasks = list(result.scalars().all())

    logger.info("list_tasks", total=total, returned=len(tasks))
    return TaskListResponse(tasks=[_task_to_response(t) for t in tasks], total=total)


# ── POST /v1/tasks ─────────────────────────────────────────────────────────────


@router.post("/v1/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskCreate,
    session: AsyncSession = Depends(get_db),
) -> TaskResponse:
    """Create a task linked to an existing memory item.

    Args:
        body: TaskCreate with memory_id (required), description, and optional fields.

    Returns:
        TaskResponse with the created task.

    Raises:
        404: If memory_id does not match any MemoryItem.
        422: If memory_id is not a valid UUID or status is invalid.
    """
    memory_uuid = _parse_uuid(body.memory_id, "memory_id")

    memory_item = await session.get(MemoryItem, memory_uuid)
    if memory_item is None:
        raise HTTPException(status_code=404, detail=f"MemoryItem {body.memory_id} not found")

    task = Task(
        memory_id=memory_uuid,
        description=body.description,
        owner=body.owner,
        due_date=body.due_date,
        status=body.status,
    )
    session.add(task)
    await session.flush()
    await session.commit()

    logger.info("create_task", task_id=str(task.id), memory_id=body.memory_id)
    return _task_to_response(task)


# ── PATCH /v1/tasks/{task_id} ──────────────────────────────────────────────────


@router.patch("/v1/tasks/{task_id}", response_model=TaskResponse)
async def update_task_status(
    task_id: str,
    body: TaskStatusUpdate,
    session: AsyncSession = Depends(get_db),
) -> TaskResponse:
    """Update a task's status.

    Args:
        task_id: UUID of the task to update.
        body: TaskStatusUpdate with the new status.

    Returns:
        TaskResponse with the updated task.

    Raises:
        404: If task_id does not match any Task.
        422: If task_id is not a valid UUID or status is invalid.
    """
    task_uuid = _parse_uuid(task_id, "task_id")

    task = await session.get(Task, task_uuid)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    task.status = body.status
    await session.flush()
    await session.commit()

    logger.info("update_task_status", task_id=task_id, status=body.status)
    return _task_to_response(task)
