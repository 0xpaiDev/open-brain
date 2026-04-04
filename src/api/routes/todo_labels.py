"""Todo label management endpoints.

POST   /v1/todo-labels        — create label
GET    /v1/todo-labels        — list all labels
DELETE /v1/todo-labels/{name} — delete label by name
"""

import re

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import limiter, todos_limit
from src.core.database import get_db
from src.core.models import TodoLabel

logger = structlog.get_logger(__name__)

router = APIRouter()

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


# ── Pydantic models ──────────────────────────────────────────────────────────


class LabelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    color: str = Field(default="#6750A4", max_length=7)

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str) -> str:
        if not _HEX_COLOR_RE.match(v):
            raise ValueError("color must be a hex color like #FF0000")
        return v


class LabelResponse(BaseModel):
    id: str
    name: str
    color: str
    created_at: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _label_to_response(label: TodoLabel) -> LabelResponse:
    return LabelResponse(
        id=str(label.id),
        name=label.name,
        color=label.color,
        created_at=label.created_at.isoformat() if label.created_at else "",
    )


# ── POST /v1/todo-labels ─────────────────────────────────────────────────────


@router.post("/v1/todo-labels", response_model=LabelResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(todos_limit)
async def create_label(
    request: Request,
    body: LabelCreate,
    session: AsyncSession = Depends(get_db),
) -> LabelResponse:
    """Create a new todo label."""
    existing = await session.execute(select(TodoLabel).where(TodoLabel.name == body.name))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Label '{body.name}' already exists")

    label = TodoLabel(name=body.name, color=body.color)
    session.add(label)
    await session.commit()
    await session.refresh(label)

    logger.info("create_label", name=label.name)
    return _label_to_response(label)


# ── GET /v1/todo-labels ──────────────────────────────────────────────────────


@router.get("/v1/todo-labels", response_model=list[LabelResponse])
@limiter.limit(todos_limit)
async def list_labels(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> list[LabelResponse]:
    """List all todo labels."""
    result = await session.execute(select(TodoLabel).order_by(TodoLabel.name))
    labels = list(result.scalars().all())
    return [_label_to_response(l) for l in labels]


# ── DELETE /v1/todo-labels/{name} ─────────────────────────────────────────────


@router.delete("/v1/todo-labels/{name}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(todos_limit)
async def delete_label(
    request: Request,
    name: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Delete a todo label by name. Does NOT touch tasks with that label."""
    result = await session.execute(select(TodoLabel).where(TodoLabel.name == name))
    label = result.scalar_one_or_none()
    if label is None:
        raise HTTPException(status_code=404, detail=f"Label '{name}' not found")

    await session.delete(label)
    await session.commit()
    logger.info("delete_label", name=name)
