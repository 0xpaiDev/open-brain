"""Global exercise library endpoints.

GET /v1/exercises — list all exercises ordered by display_name
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import commitments_limit, limiter
from src.core.database import get_db
from src.core.models import Exercise

logger = structlog.get_logger(__name__)

router = APIRouter()


class ExerciseLibraryResponse(BaseModel):
    id: str
    name: str
    display_name: str
    created_at: str


@router.get("/v1/exercises", response_model=list[ExerciseLibraryResponse])
@limiter.limit(commitments_limit)
async def list_exercises(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> list[ExerciseLibraryResponse]:
    """List all exercises in the global library, ordered by display_name."""
    result = await session.execute(
        select(Exercise).order_by(Exercise.display_name)
    )
    exercises = result.scalars().all()
    return [
        ExerciseLibraryResponse(
            id=str(ex.id),
            name=ex.name,
            display_name=ex.display_name,
            created_at=str(ex.created_at),
        )
        for ex in exercises
    ]
