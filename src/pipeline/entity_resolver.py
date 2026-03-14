"""Entity resolution and knowledge graph linking."""

import structlog
from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.models import Entity, EntityAlias
from src.pipeline.extractor import EntityExtract

logger = structlog.get_logger(__name__)


async def resolve_entities(
    session: AsyncSession,
    entities: list[EntityExtract],
) -> list[Entity]:
    """Resolve extracted entities to the knowledge graph.

    For each entity:
    1. Check entity_aliases for exact name match (canonical form)
    2. If no exact match, fuzzy match on entities.name with pg_trgm similarity
       (same entity type, threshold from settings)
    3. If fuzzy match found, create alias linking new name to existing entity
    4. If no match, create new entity row

    Uses INSERT ... ON CONFLICT DO NOTHING for idempotency.

    Args:
        session: AsyncSession for database operations
        entities: List of EntityExtract to resolve

    Returns:
        List of Entity ORM objects (canonical entities for these extractions)

    Raises:
        Exception: If database operations fail
    """
    resolved = []

    for entity_extract in entities:
        try:
            canonical_name = entity_extract.name.strip()
            entity_type = entity_extract.type

            # Step 1: Check for exact alias match
            alias_result = await session.execute(
                select(EntityAlias).where(
                    EntityAlias.alias == canonical_name
                )
            )
            exact_alias = alias_result.scalars().first()

            if exact_alias:
                # Get the canonical entity
                canonical_entity = await session.get(Entity, exact_alias.entity_id)
                if canonical_entity:
                    logger.info(
                        "entity_resolved_via_alias",
                        name=canonical_name,
                        type=entity_type,
                        canonical_id=str(canonical_entity.id),
                    )
                    resolved.append(canonical_entity)
                    continue

            # Step 2: Fuzzy match with pg_trgm similarity
            # NOTE: This query uses PostgreSQL's pg_trgm extension.
            # SQLite does not have similarity() — tests must mock this query.
            if settings is None:
                logger.warning("settings_not_initialized_skipping_fuzzy_match")
                threshold = 0.92  # fallback default
            else:
                threshold = settings.entity_fuzzy_match_threshold

            # Attempt fuzzy matching via pg_trgm (PostgreSQL only)
            # SQLite does not have the similarity() function
            fuzzy_match = None
            try:
                fuzzy_query = select(Entity).where(
                    and_(
                        Entity.type == entity_type,
                        # pg_trgm similarity - must match exactly with the GIN index
                        text(
                            "similarity(name, :candidate_name) >= :threshold"
                        ),
                    )
                )

                fuzzy_result = await session.execute(
                    fuzzy_query,
                    {"candidate_name": canonical_name, "threshold": threshold},
                )
                fuzzy_match = fuzzy_result.scalars().first()
            except Exception as e:
                # pg_trgm not available (e.g., SQLite in tests)
                logger.debug(
                    "fuzzy_match_unavailable",
                    error=str(e),
                    note="pg_trgm similarity() not available (SQLite?)",
                )

            if fuzzy_match:
                # Create alias for this entity
                new_alias = EntityAlias(
                    entity_id=fuzzy_match.id,
                    alias=canonical_name,
                )
                session.add(new_alias)

                logger.info(
                    "entity_resolved_via_fuzzy_match",
                    name=canonical_name,
                    type=entity_type,
                    canonical_id=str(fuzzy_match.id),
                    threshold=threshold,
                )
                resolved.append(fuzzy_match)
                continue

            # Step 3: No match found — create new entity
            new_entity = Entity(
                name=canonical_name,
                type=entity_type,
            )
            session.add(new_entity)
            await session.flush()  # Ensure ID is populated

            logger.info(
                "entity_created_new",
                name=canonical_name,
                type=entity_type,
                entity_id=str(new_entity.id),
            )
            resolved.append(new_entity)

        except Exception as e:
            logger.exception(
                "entity_resolution_error",
                name=entity_extract.name,
                type=entity_extract.type,
                error=str(e),
            )
            raise

    return resolved
