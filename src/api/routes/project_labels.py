"""Project label management endpoints.

POST   /v1/project-labels         — create label
GET    /v1/project-labels         — list all labels
PATCH  /v1/project-labels/{name}  — rename / recolor (cascades to todos + memories)
DELETE /v1/project-labels/{name}  — delete label, NULLing project on referencing rows
"""

import re

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import limiter, todos_limit
from src.core.database import get_db
from src.core.models import MemoryItem, ProjectLabel, TodoItem

logger = structlog.get_logger(__name__)

router = APIRouter()

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


# ── Pydantic models ──────────────────────────────────────────────────────────


class ProjectLabelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    color: str = Field(default="#6750A4", max_length=7)

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str) -> str:
        if not _HEX_COLOR_RE.match(v):
            raise ValueError("color must be a hex color like #FF0000")
        return v


class ProjectLabelUpdate(BaseModel):
    new_name: str | None = Field(None, min_length=1, max_length=100)
    color: str | None = Field(None, max_length=7)

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str | None) -> str | None:
        if v is not None and not _HEX_COLOR_RE.match(v):
            raise ValueError("color must be a hex color like #FF0000")
        return v


class ProjectLabelResponse(BaseModel):
    id: str
    name: str
    color: str
    created_at: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _label_to_response(label: ProjectLabel) -> ProjectLabelResponse:
    return ProjectLabelResponse(
        id=str(label.id),
        name=label.name,
        color=label.color,
        created_at=label.created_at.isoformat() if label.created_at else "",
    )


# ── POST /v1/project-labels ─────────────────────────────────────────────────


@router.post(
    "/v1/project-labels", response_model=ProjectLabelResponse, status_code=status.HTTP_201_CREATED
)
@limiter.limit(todos_limit)
async def create_project_label(
    request: Request,
    body: ProjectLabelCreate,
    session: AsyncSession = Depends(get_db),
) -> ProjectLabelResponse:
    """Create a new project label."""
    existing = await session.execute(select(ProjectLabel).where(ProjectLabel.name == body.name))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Project label '{body.name}' already exists")

    label = ProjectLabel(name=body.name, color=body.color)
    session.add(label)
    await session.commit()
    await session.refresh(label)

    logger.info("create_project_label", name=label.name)
    return _label_to_response(label)


# ── GET /v1/project-labels ──────────────────────────────────────────────────


@router.get("/v1/project-labels", response_model=list[ProjectLabelResponse])
@limiter.limit(todos_limit)
async def list_project_labels(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> list[ProjectLabelResponse]:
    """List all project labels."""
    result = await session.execute(select(ProjectLabel).order_by(ProjectLabel.name))
    labels = list(result.scalars().all())
    return [_label_to_response(l) for l in labels]


# ── PATCH /v1/project-labels/{name} ──────────────────────────────────────────


@router.patch("/v1/project-labels/{name}", response_model=ProjectLabelResponse)
@limiter.limit(todos_limit)
async def update_project_label(
    request: Request,
    name: str,
    body: ProjectLabelUpdate,
    session: AsyncSession = Depends(get_db),
) -> ProjectLabelResponse:
    """Rename and/or recolor a project label.

    A name change cascades to all referencing rows in ``todo_items.project``
    and ``memory_items.project`` in the same transaction. A name collision
    with another existing label returns 409 (no partial update).
    """
    result = await session.execute(select(ProjectLabel).where(ProjectLabel.name == name))
    label = result.scalar_one_or_none()
    if label is None:
        raise HTTPException(status_code=404, detail=f"Project label '{name}' not found")

    new_name = body.new_name
    if new_name is not None and new_name != name:
        # Collision check
        existing = await session.execute(select(ProjectLabel).where(ProjectLabel.name == new_name))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Project label '{new_name}' already exists",
            )
        # Cascade rename to referencing rows first, then update the label row.
        await session.execute(
            sa_update(TodoItem).where(TodoItem.project == name).values(project=new_name)
        )
        await session.execute(
            sa_update(MemoryItem).where(MemoryItem.project == name).values(project=new_name)
        )
        label.name = new_name

    if body.color is not None:
        label.color = body.color

    await session.commit()
    await session.refresh(label)
    logger.info(
        "update_project_label",
        old_name=name,
        new_name=label.name,
        color=label.color,
    )
    return _label_to_response(label)


# ── DELETE /v1/project-labels/{name} ─────────────────────────────────────────


@router.delete("/v1/project-labels/{name}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(todos_limit)
async def delete_project_label(
    request: Request,
    name: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Delete a project label.

    NULLs out the ``project`` column on all referencing ``todo_items`` and
    ``memory_items`` in the same transaction so the row deletion never
    leaves dangling soft references. Affected todos render under "Personal"
    via the UI fallback.
    """
    result = await session.execute(select(ProjectLabel).where(ProjectLabel.name == name))
    label = result.scalar_one_or_none()
    if label is None:
        raise HTTPException(status_code=404, detail=f"Project label '{name}' not found")

    await session.execute(sa_update(TodoItem).where(TodoItem.project == name).values(project=None))
    await session.execute(
        sa_update(MemoryItem).where(MemoryItem.project == name).values(project=None)
    )
    await session.delete(label)
    await session.commit()
    logger.info("delete_project_label", name=name)
