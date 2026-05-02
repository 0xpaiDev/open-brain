"""Learning library endpoints.

Topic → Section → Item hierarchy plus a manual refresh trigger for the
daily cron. All routes require `module_learning_enabled=True`; when the
flag is off, every route returns 404 and the page is effectively invisible.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import (
    learning_import_limit,
    learning_limit,
    learning_refresh_limit,
    limiter,
)
from src.api.schemas.learning_import import (
    ImportResult,
    LearningImportRequest,
    MaterialOut,
    MaterialUpdate,
)
from src.api.services import learning_service
from src.core.config import get_settings
from src.core.database import get_db
from src.core.models import LearningItem, LearningSection, LearningTopic

logger = structlog.get_logger(__name__)

router = APIRouter()

_VALID_DEPTHS = {"foundational", "deep"}
_VALID_ITEM_STATUS = {"pending", "done"}


def _require_enabled() -> None:
    settings = get_settings()
    if not settings.module_learning_enabled:
        raise HTTPException(status_code=404, detail="Not Found")


# ── Pydantic models ───────────────────────────────────────────────────────────


class TopicCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    depth: str = "foundational"
    position: int = 0

    @field_validator("depth")
    @classmethod
    def _v_depth(cls, v: str) -> str:
        if v not in _VALID_DEPTHS:
            raise ValueError(f"depth must be one of {sorted(_VALID_DEPTHS)}")
        return v


class TopicUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = None
    depth: str | None = None
    is_active: bool | None = None
    position: int | None = None

    @field_validator("depth")
    @classmethod
    def _v_depth(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_DEPTHS:
            raise ValueError(f"depth must be one of {sorted(_VALID_DEPTHS)}")
        return v


class SectionCreate(BaseModel):
    topic_id: _uuid.UUID
    name: str = Field(..., min_length=1, max_length=120)
    position: int = 0


class SectionUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    position: int | None = None


class ItemCreate(BaseModel):
    section_id: _uuid.UUID
    title: str = Field(..., min_length=1, max_length=240)
    position: int = 0


class ItemUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=240)
    status: str | None = None
    feedback: str | None = None
    notes: str | None = None
    position: int | None = None

    @field_validator("status")
    @classmethod
    def _v_status(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_ITEM_STATUS:
            raise ValueError(f"status must be one of {sorted(_VALID_ITEM_STATUS)}")
        return v


class RefreshResponse(BaseModel):
    created: int
    skipped_existing: int
    fallback: bool
    target_count: int


# ── GET /v1/learning ──────────────────────────────────────────────────────────


@router.get("/v1/learning")
@limiter.limit(learning_limit)
async def get_tree(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the full learning tree (topics → sections → items)."""
    _require_enabled()
    topics = await learning_service.load_tree(session)
    return {"topics": [learning_service.topic_to_dict(t) for t in topics]}


# ── Topic CRUD ────────────────────────────────────────────────────────────────


@router.post("/v1/learning/topics", status_code=status.HTTP_201_CREATED)
@limiter.limit(learning_limit)
async def create_topic(
    request: Request,
    body: TopicCreate,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_enabled()
    topic = LearningTopic(
        name=body.name,
        description=body.description,
        depth=body.depth,
        position=body.position,
    )
    session.add(topic)
    await session.commit()
    await session.refresh(topic)
    logger.info("learning_topic_created", topic_id=str(topic.id))
    return learning_service.topic_to_dict(topic, include_children=False)


@router.patch("/v1/learning/topics/{topic_id}")
@limiter.limit(learning_limit)
async def update_topic(
    request: Request,
    topic_id: _uuid.UUID,
    body: TopicUpdate,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_enabled()
    topic = await session.get(LearningTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    if body.name is not None:
        topic.name = body.name
    if body.description is not None:
        topic.description = body.description
    if body.depth is not None:
        topic.depth = body.depth
    if body.is_active is not None:
        topic.is_active = body.is_active
    if body.position is not None:
        topic.position = body.position
    await session.commit()
    await session.refresh(topic)
    logger.info("learning_topic_updated", topic_id=str(topic.id))
    return learning_service.topic_to_dict(topic, include_children=False)


@router.delete("/v1/learning/topics/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(learning_limit)
async def delete_topic(
    request: Request,
    topic_id: _uuid.UUID,
    confirm: bool = Query(default=False),
    session: AsyncSession = Depends(get_db),
) -> None:
    """Hard delete — requires confirm=true to prevent accidental data loss."""
    _require_enabled()
    if not confirm:
        raise HTTPException(status_code=400, detail="Pass confirm=true to delete")
    topic = await session.get(LearningTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    await session.delete(topic)
    await session.commit()
    logger.info("learning_topic_deleted", topic_id=str(topic_id))


# ── Section CRUD ──────────────────────────────────────────────────────────────


@router.post("/v1/learning/sections", status_code=status.HTTP_201_CREATED)
@limiter.limit(learning_limit)
async def create_section(
    request: Request,
    body: SectionCreate,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_enabled()
    topic = await session.get(LearningTopic, body.topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    section = LearningSection(topic_id=body.topic_id, name=body.name, position=body.position)
    session.add(section)
    await session.commit()
    await session.refresh(section)
    logger.info("learning_section_created", section_id=str(section.id))
    return learning_service.section_to_dict(section, include_items=False)


@router.patch("/v1/learning/sections/{section_id}")
@limiter.limit(learning_limit)
async def update_section(
    request: Request,
    section_id: _uuid.UUID,
    body: SectionUpdate,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_enabled()
    section = await session.get(LearningSection, section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")
    if body.name is not None:
        section.name = body.name
    if body.position is not None:
        section.position = body.position
    await session.commit()
    await session.refresh(section)
    return learning_service.section_to_dict(section, include_items=False)


@router.delete("/v1/learning/sections/{section_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(learning_limit)
async def delete_section(
    request: Request,
    section_id: _uuid.UUID,
    confirm: bool = Query(default=False),
    session: AsyncSession = Depends(get_db),
) -> None:
    _require_enabled()
    if not confirm:
        raise HTTPException(status_code=400, detail="Pass confirm=true to delete")
    section = await session.get(LearningSection, section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")
    await session.delete(section)
    await session.commit()


# ── Item CRUD ─────────────────────────────────────────────────────────────────


@router.post("/v1/learning/items", status_code=status.HTTP_201_CREATED)
@limiter.limit(learning_limit)
async def create_item(
    request: Request,
    body: ItemCreate,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_enabled()
    section = await session.get(LearningSection, body.section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")
    item = LearningItem(section_id=body.section_id, title=body.title, position=body.position)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    logger.info("learning_item_created", item_id=str(item.id))
    return learning_service.item_to_dict(item)


def _apply_item_update(item: LearningItem, body: ItemUpdate) -> bool:
    """Mutate the item in-place and return True when it transitioned to 'done'."""
    from datetime import UTC, datetime

    newly_completed = False
    if body.title is not None:
        item.title = body.title
    if body.status is not None:
        if body.status == "done" and item.status != "done":
            newly_completed = True
            item.completed_at = datetime.now(UTC)
        if body.status == "pending":
            item.completed_at = None
        item.status = body.status
    if body.feedback is not None:
        item.feedback = body.feedback
    if body.notes is not None:
        item.notes = body.notes
    if body.position is not None:
        item.position = body.position
    return newly_completed


@router.patch("/v1/learning/items/{item_id}")
@limiter.limit(learning_limit)
async def update_item(
    request: Request,
    item_id: _uuid.UUID,
    body: ItemUpdate,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_enabled()
    item = await session.get(LearningItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    newly_completed = _apply_item_update(item, body)
    await session.commit()
    await session.refresh(item)
    if newly_completed:
        try:
            await learning_service.cancel_matching_open_todo_for_item(session, item.id)
        except Exception:
            logger.warning("learning_item_cancel_todo_failed", item_id=str(item.id), exc_info=True)
    return learning_service.item_to_dict(item)


@router.delete("/v1/learning/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(learning_limit)
async def delete_item(
    request: Request,
    item_id: _uuid.UUID,
    confirm: bool = Query(default=False),
    session: AsyncSession = Depends(get_db),
) -> None:
    _require_enabled()
    if not confirm:
        raise HTTPException(status_code=400, detail="Pass confirm=true to delete")
    item = await session.get(LearningItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    await session.delete(item)
    await session.commit()


# ── POST /v1/learning/refresh ─────────────────────────────────────────────────


@router.post("/v1/learning/refresh", response_model=RefreshResponse)
@limiter.limit(learning_refresh_limit)
async def refresh_today(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> RefreshResponse:
    """Trigger the daily selection on demand.

    Idempotent — running again the same day only fills the gap to target_count.
    Tight rate limit prevents abusive LLM-cost loops.
    """
    _require_enabled()
    from src.jobs.learning_daily import run_learning_selection

    summary = await run_learning_selection(session)
    return RefreshResponse(**summary)


# ── POST /v1/learning/import ──────────────────────────────────────────────────


@router.post("/v1/learning/import", response_model=ImportResult)
@limiter.limit(learning_import_limit)
async def import_curriculum(
    request: Request,
    body: LearningImportRequest,
    dry_run: bool = Query(default=False),
    session: AsyncSession = Depends(get_db),
) -> ImportResult:
    """Bulk-import a curriculum from a structured JSON document.

    Use dry_run=true for a preview without writing anything, then re-POST with
    dry_run=false to commit. Dedup is case-insensitive on topic name.
    """
    _require_enabled()
    return await learning_service.import_curriculum(session, body, dry_run=dry_run)


# ── Material CRUD ─────────────────────────────────────────────────────────────


@router.get(
    "/v1/learning/topics/{topic_id}/material",
    response_model=MaterialOut | None,
)
@limiter.limit(learning_limit)
async def get_material(
    request: Request,
    topic_id: _uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any] | None:
    """Return the material for a topic, or null if none has been saved."""
    _require_enabled()
    topic = await session.get(LearningTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    material = await learning_service.get_material(session, topic_id)
    if material is None:
        return None
    return learning_service.material_to_dict(material)


@router.patch(
    "/v1/learning/topics/{topic_id}/material",
    response_model=MaterialOut,
)
@limiter.limit(learning_limit)
async def upsert_material(
    request: Request,
    topic_id: _uuid.UUID,
    body: MaterialUpdate,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create or replace the material for a topic."""
    _require_enabled()
    topic = await session.get(LearningTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    material = await learning_service.upsert_material(session, topic_id, body)
    return learning_service.material_to_dict(material)


@router.delete(
    "/v1/learning/topics/{topic_id}/material",
    status_code=status.HTTP_204_NO_CONTENT,
)
@limiter.limit(learning_limit)
async def delete_material(
    request: Request,
    topic_id: _uuid.UUID,
    confirm: bool = Query(default=False),
    session: AsyncSession = Depends(get_db),
) -> None:
    """Hard-delete the material for a topic. Requires confirm=true."""
    _require_enabled()
    if not confirm:
        raise HTTPException(status_code=400, detail="Pass confirm=true to delete")
    topic = await session.get(LearningTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    await learning_service.delete_material(session, topic_id)
    logger.info("learning_material_deleted", topic_id=str(topic_id))


# ── GET /v1/modules ───────────────────────────────────────────────────────────


modules_router = APIRouter()


@modules_router.get("/v1/modules")
async def get_modules() -> dict[str, bool]:
    """Return enabled-state of every feature-flagged module.

    Web uses this to hide nav links and avoid 404s against disabled features.
    """
    s = get_settings()
    return {
        "todo": s.module_todo_enabled,
        "pulse": s.module_pulse_enabled,
        "rag_chat": s.module_rag_chat_enabled,
        "training": s.module_training_enabled,
        "learning": s.module_learning_enabled,
    }
