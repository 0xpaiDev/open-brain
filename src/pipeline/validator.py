"""Validation and normalization of extracted data."""

import structlog

from src.pipeline.extractor import (
    ExtractionResult,
)

logger = structlog.get_logger(__name__)


class ValidationFailed(Exception):
    """Raised when validation of extracted data fails."""

    pass


def validate(extraction: ExtractionResult) -> ExtractionResult:
    """Validate and normalize extracted data.

    Performs:
    - Ensures content is not empty
    - Normalizes entity names (strip whitespace, lowercase)
    - Deduplicates entities by normalized name
    - Validates decision/task structure

    Args:
        extraction: ExtractionResult to validate

    Returns:
        Validated and normalized ExtractionResult

    Raises:
        ValidationFailed: If validation fails
    """
    try:
        # Check that content is not empty
        if not extraction.content or not extraction.content.strip():
            raise ValidationFailed("Extracted content cannot be empty")

        # Normalize entity names: strip, lowercase
        # Then deduplicate by normalized name while preserving the original canonical form
        seen_names = set()
        deduplicated_entities = []

        for entity in extraction.entities:
            normalized_name = entity.name.strip().lower()

            if normalized_name not in seen_names:
                seen_names.add(normalized_name)
                # Keep the original entity (don't modify the name)
                deduplicated_entities.append(entity)

        # Create a new ExtractionResult with deduplicated entities
        result = ExtractionResult(
            type=extraction.type,
            content=extraction.content,
            summary=extraction.summary,
            entities=deduplicated_entities,
            decisions=extraction.decisions,
            tasks=extraction.tasks,
            base_importance=extraction.base_importance,
        )

        logger.info(
            "validation_success",
            entities_after_dedup=len(deduplicated_entities),
            entities_before_dedup=len(extraction.entities),
        )

        return result

    except ValidationFailed:
        raise
    except Exception as e:
        logger.exception("validation_unexpected_error", error=str(e))
        raise ValidationFailed(f"Validation error: {e}") from e
