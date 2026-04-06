"""Project label management endpoints.

POST   /v1/project-labels        — create label
GET    /v1/project-labels        — list all labels
DELETE /v1/project-labels/{name} — delete label by name
"""

import re

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import limiter, todos_limit
from src.core.database import get_db
from src.core.models import ProjectLabel

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


@router.post("/v1/project-labels", response_model=ProjectLabelResponse, status_code=status.HTTP_201_CREATED)
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


# ── DELETE /v1/project-labels/{name} ─────────────────────────────────────────


@router.delete("/v1/project-labels/{name}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(todos_limit)
async def delete_project_label(
    request: Request,
    name: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Delete a project label by name. Does NOT touch memories with that project."""
    result = await session.execute(select(ProjectLabel).where(ProjectLabel.name == name))
    label = result.scalar_one_or_none()
    if label is None:
        raise HTTPException(status_code=404, detail=f"Project label '{name}' not found")

    await session.delete(label)
    await session.commit()
    logger.info("delete_project_label", name=name)
