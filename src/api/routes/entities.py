"""Entity management endpoints.

GET  /v1/entities            — list entities with optional name/type filters
GET  /v1/entities/{id}       — get entity with its aliases
POST /v1/entities/merge      — merge source entity into target (destructive)
POST /v1/entities/{id}/aliases — add an alias to an existing entity

NOTE: /v1/entities/merge is registered before /v1/entities/{entity_id} so
FastAPI does not interpret the literal string "merge" as an entity UUID.
"""

import uuid as _uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.middleware.rate_limit import entities_limit, limiter
from src.core.database import get_db
from src.core.models import Entity, EntityAlias, EntityRelation, MemoryEntityLink

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Pydantic models ────────────────────────────────────────────────────────────


class AliasItem(BaseModel):
    id: str
    alias: str
    source: str | None
    created_at: datetime


class EntityResponse(BaseModel):
    id: str
    name: str
    type: str
    created_at: datetime
    aliases: list[AliasItem] = []


class EntityListResponse(BaseModel):
    entities: list[EntityResponse]
    total: int


class AddAliasRequest(BaseModel):
    alias: str
    source: str | None = None


class AddAliasResponse(BaseModel):
    entity_id: str
    alias: str
    source: str | None


class MergeRequest(BaseModel):
    source_entity_id: str
    target_entity_id: str


class MergeResponse(BaseModel):
    target_entity_id: str
    aliases_moved: int
    memory_links_moved: int
    relations_moved: int
    source_name_aliased: bool


# ── Helpers ────────────────────────────────────────────────────────────────────


def _entity_to_response(entity: Entity) -> EntityResponse:
    return EntityResponse(
        id=str(entity.id),
        name=entity.name,
        type=entity.type,
        created_at=entity.created_at,
        aliases=[
            AliasItem(
                id=str(a.id),
                alias=a.alias,
                source=a.source,
                created_at=a.created_at,
            )
            for a in (entity.aliases or [])
        ],
    )


# ── GET /v1/entities ──────────────────────────────────────────────────────────


@router.get("/v1/entities", response_model=EntityListResponse)
@limiter.limit(entities_limit)
async def list_entities(
    request: Request,
    q: str | None = Query(default=None, description="Name substring search (case-insensitive)"),
    type_filter: str | None = Query(default=None, description="Filter by entity type"),
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
) -> EntityListResponse:
    """List entities with optional name search and type filter.

    Args:
        q: Case-insensitive substring match on entity name.
        type_filter: Filter by entity type (person, org, project, etc.).
        limit: Max results (1–500, default 50).

    Raises:
        401: Missing or invalid X-API-Key (handled by middleware).
    """
    stmt = select(Entity).options(selectinload(Entity.aliases)).limit(limit)
    if q:
        stmt = stmt.where(Entity.name.ilike(f"%{q}%"))
    if type_filter:
        stmt = stmt.where(Entity.type == type_filter)

    result = await session.execute(stmt)
    entities = result.scalars().all()
    return EntityListResponse(
        entities=[_entity_to_response(e) for e in entities],
        total=len(entities),
    )


# ── POST /v1/entities/merge — MUST be before /{entity_id} ────────────────────


@router.post("/v1/entities/merge", response_model=MergeResponse)
@limiter.limit(entities_limit)
async def merge_entities(
    request: Request,
    body: MergeRequest,
    session: AsyncSession = Depends(get_db),
) -> MergeResponse:
    """Merge source entity into target entity.

    Moves all aliases, memory links, and entity relations from source to
    target, resolving composite-PK conflicts by dropping duplicate rows.
    Adds source.name as an alias on the target for discoverability, then
    deletes the source entity.

    All operations run in a single atomic transaction.

    Args:
        body.source_entity_id: UUID of entity to delete after merge.
        body.target_entity_id: UUID of entity that survives.

    Raises:
        422: source_entity_id == target_entity_id, or invalid UUIDs.
        404: Either entity not found.
        401: Missing or invalid X-API-Key (handled by middleware).
    """
    try:
        source_uuid = _uuid.UUID(body.source_entity_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="source_entity_id is not a valid UUID") from None
    try:
        target_uuid = _uuid.UUID(body.target_entity_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="target_entity_id is not a valid UUID") from None

    if source_uuid == target_uuid:
        raise HTTPException(status_code=422, detail="Cannot merge entity with itself")

    source_entity = await session.get(Entity, source_uuid)
    if source_entity is None:
        raise HTTPException(status_code=404, detail="source_entity_id not found")

    target_entity = await session.get(Entity, target_uuid)
    if target_entity is None:
        raise HTTPException(status_code=404, detail="target_entity_id not found")

    # Capture scalar values before any session modifications
    source_name = source_entity.name

    # Load source aliases before expunging source_entity from the session.
    # We move them via ORM so SQLAlchemy handles UUID type binding.
    alias_result = await session.execute(
        select(EntityAlias).where(EntityAlias.entity_id == source_uuid)
    )
    source_aliases = alias_result.scalars().all()

    # Expunge source_entity early so the ORM doesn't try to manage its FK
    # dependencies when we later delete it via Core (avoids "blank-out PK"
    # errors from stale identity-map MemoryEntityLink / EntityRelation objects).
    session.expunge(source_entity)

    # 1. Move entity_aliases via ORM (they are loaded; ORM handles UUID binding)
    for alias_obj in source_aliases:
        alias_obj.entity_id = target_uuid
    aliases_moved = len(source_aliases)
    await session.flush()

    # 2. Move memory_entity_links via Core (handles UUID type per dialect)
    #    Delete conflicts (target already has link to same memory), then update rest.
    conflict_memory_ids = (
        select(MemoryEntityLink.memory_id)
        .where(MemoryEntityLink.entity_id == target_uuid)
        .scalar_subquery()
    )
    await session.execute(
        sa_delete(MemoryEntityLink).where(
            MemoryEntityLink.entity_id == source_uuid,
            MemoryEntityLink.memory_id.in_(conflict_memory_ids),
        )
    )
    links_result = await session.execute(
        sa_update(MemoryEntityLink)
        .where(MemoryEntityLink.entity_id == source_uuid)
        .values(entity_id=target_uuid)
    )
    memory_links_moved = links_result.rowcount

    # 3. Move entity_relations from direction — delete conflicts, then update
    er = EntityRelation
    er2 = EntityRelation.__table__.alias("er2")
    from_conflict_exists = (
        select(func.count())
        .select_from(er2)
        .where(
            (er2.c.from_entity_id == target_uuid)
            & (er2.c.to_entity_id == er.__table__.c.to_entity_id)
            & (er2.c.relation_type == er.__table__.c.relation_type)
            & (er2.c.memory_id == er.__table__.c.memory_id)
        )
        .correlate(er.__table__)
        .scalar_subquery()
    )
    await session.execute(
        sa_delete(EntityRelation).where(
            EntityRelation.from_entity_id == source_uuid,
            from_conflict_exists > 0,
        )
    )
    from_result = await session.execute(
        sa_update(EntityRelation)
        .where(EntityRelation.from_entity_id == source_uuid)
        .values(from_entity_id=target_uuid)
    )

    # 4. Move entity_relations to direction — delete conflicts, then update
    to_conflict_exists = (
        select(func.count())
        .select_from(er2)
        .where(
            (er2.c.to_entity_id == target_uuid)
            & (er2.c.from_entity_id == er.__table__.c.from_entity_id)
            & (er2.c.relation_type == er.__table__.c.relation_type)
            & (er2.c.memory_id == er.__table__.c.memory_id)
        )
        .correlate(er.__table__)
        .scalar_subquery()
    )
    await session.execute(
        sa_delete(EntityRelation).where(
            EntityRelation.to_entity_id == source_uuid,
            to_conflict_exists > 0,
        )
    )
    to_result = await session.execute(
        sa_update(EntityRelation)
        .where(EntityRelation.to_entity_id == source_uuid)
        .values(to_entity_id=target_uuid)
    )
    relations_moved = from_result.rowcount + to_result.rowcount

    # 5. Add source name as alias on target (if not already taken)
    existing_alias = await session.execute(
        select(EntityAlias).where(EntityAlias.alias == source_name)
    )
    source_name_aliased = False
    if existing_alias.scalar_one_or_none() is None:
        name_alias = EntityAlias(entity_id=target_uuid, alias=source_name, source="merge")
        session.add(name_alias)
        source_name_aliased = True
    await session.flush()

    # 6. Delete source entity via Core (UUID type handled by ORM column definition)
    #    source_entity was expunged so the ORM won't try to cascade or blank its PKs.
    await session.execute(sa_delete(Entity).where(Entity.id == source_uuid))
    await session.commit()

    logger.info(
        "entity_merge_complete",
        source_id=str(source_uuid),
        target_id=str(target_uuid),
        aliases_moved=aliases_moved,
        memory_links_moved=memory_links_moved,
        relations_moved=relations_moved,
    )
    return MergeResponse(
        target_entity_id=str(target_uuid),
        aliases_moved=aliases_moved,
        memory_links_moved=memory_links_moved,
        relations_moved=relations_moved,
        source_name_aliased=source_name_aliased,
    )


# ── GET /v1/entities/{entity_id} ──────────────────────────────────────────────


@router.get("/v1/entities/{entity_id}", response_model=EntityResponse)
@limiter.limit(entities_limit)
async def get_entity(
    request: Request,
    entity_id: _uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> EntityResponse:
    """Get a single entity with all its aliases.

    Raises:
        422: entity_id is not a valid UUID.
        404: Entity not found.
        401: Missing or invalid X-API-Key (handled by middleware).
    """
    result = await session.execute(
        select(Entity).options(selectinload(Entity.aliases)).where(Entity.id == entity_id)
    )
    entity = result.scalar_one_or_none()
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return _entity_to_response(entity)


# ── POST /v1/entities/{entity_id}/aliases ─────────────────────────────────────


@router.post(
    "/v1/entities/{entity_id}/aliases",
    status_code=status.HTTP_201_CREATED,
    response_model=AddAliasResponse,
)
@limiter.limit(entities_limit)
async def add_alias(
    request: Request,
    entity_id: _uuid.UUID,
    body: AddAliasRequest,
    session: AsyncSession = Depends(get_db),
) -> AddAliasResponse:
    """Add an alias to an existing entity.

    Aliases are globally unique — the same alias string cannot be assigned to
    two different entities.

    Raises:
        422: entity_id is not a valid UUID.
        404: Entity not found.
        409: Alias already exists (on this or another entity).
        401: Missing or invalid X-API-Key (handled by middleware).
    """
    entity = await session.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    existing = await session.execute(select(EntityAlias).where(EntityAlias.alias == body.alias))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Alias already taken")

    alias_obj = EntityAlias(entity_id=entity_id, alias=body.alias, source=body.source)
    session.add(alias_obj)
    await session.flush()
    await session.commit()

    logger.info("entity_alias_added", entity_id=str(entity_id), alias=body.alias)
    return AddAliasResponse(entity_id=str(entity_id), alias=body.alias, source=body.source)
