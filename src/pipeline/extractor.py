"""JSON extraction from raw text via Claude."""

import json

import structlog
from pydantic import BaseModel, Field

from src.llm.client import AnthropicClient, ExtractionFailed
from src.llm.prompts import (
    build_extraction_user_message,
    get_extraction_prompt,
)

logger = structlog.get_logger(__name__)


# ── Extraction Result Schema ──────────────────────────────────────────────


class EntityExtract(BaseModel):
    """An extracted entity (person, org, project, concept, tool, or place)."""

    name: str = Field(..., description="Entity name")
    type: str = Field(
        ...,
        description="Entity type: person, org, project, concept, tool, or place",
    )


class DecisionExtract(BaseModel):
    """An extracted decision with reasoning and alternatives."""

    decision: str = Field(..., description="What was decided")
    reasoning: str = Field(..., description="Why this decision was made")
    alternatives: list[str] = Field(
        default_factory=list, description="Alternatives that were considered"
    )


class TaskExtract(BaseModel):
    """An extracted actionable task."""

    description: str = Field(..., description="What needs to be done")
    owner: str | None = Field(
        default=None, description="Who is responsible for this task"
    )
    due_date: str | None = Field(
        default=None, description="ISO date string for due date (YYYY-MM-DD)"
    )


class ExtractionResult(BaseModel):
    """Structured extraction from raw memory text.

    This Pydantic model defines the shape of Claude's extraction output.
    It must be compatible with the mock in conftest.py.
    """

    type: str = Field(
        default="memory",
        description="Memory type: memory, decision, task, or context",
    )
    content: str = Field(..., description="The main content")
    summary: str | None = Field(default=None, description="One-sentence summary")
    entities: list[EntityExtract] = Field(
        default_factory=list, description="Named entities mentioned"
    )
    decisions: list[DecisionExtract] = Field(
        default_factory=list, description="Decisions made"
    )
    tasks: list[TaskExtract] = Field(
        default_factory=list, description="Actionable tasks"
    )
    base_importance: float = Field(
        default=0.5,
        description="Importance score 0.0–1.0, rated by Claude",
        ge=0.0,
        le=1.0,
    )


# ── Extraction Function ───────────────────────────────────────────────────


async def extract(
    text: str,
    attempt: int,
    client: AnthropicClient,
) -> ExtractionResult:
    """Extract structured information from raw text via Claude.

    Args:
        text: Raw text to extract from
        attempt: Retry attempt number (0, 1, or 2). Determines which extraction
                 prompt is used (escalating stringency).
        client: AnthropicClient instance to use

    Returns:
        ExtractionResult Pydantic model with extracted data

    Raises:
        ExtractionFailed: If JSON parsing fails or schema validation fails
    """
    system_prompt = get_extraction_prompt(attempt)
    user_message = build_extraction_user_message(text)

    try:
        response_text = await client.complete(
            system_prompt=system_prompt,
            user_content=user_message,
            max_tokens=1024,
        )

        # Strip markdown code fences if present (Claude sometimes wraps JSON)
        stripped = response_text.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[-1]
            stripped = stripped.rsplit("```", 1)[0].strip()
        else:
            stripped = stripped

        # Parse JSON response
        try:
            json_data = json.loads(stripped)
        except json.JSONDecodeError as e:
            logger.exception(
                "extraction_json_parse_failed",
                attempt=attempt,
                error=str(e),
                response_text=response_text[:200],
            )
            raise ExtractionFailed(
                f"Failed to parse Claude response as JSON: {e}"
            ) from e

        # Validate against schema
        try:
            result = ExtractionResult(**json_data)
        except ValueError as e:
            logger.exception(
                "extraction_schema_validation_failed",
                attempt=attempt,
                error=str(e),
                json_data=json_data,
            )
            raise ExtractionFailed(
                f"Claude response does not match schema: {e}"
            ) from e

        logger.info(
            "extraction_success",
            attempt=attempt,
            type=result.type,
            num_entities=len(result.entities),
            num_decisions=len(result.decisions),
            num_tasks=len(result.tasks),
            base_importance=result.base_importance,
        )

        return result

    except ExtractionFailed:
        raise
    except Exception as e:
        logger.exception(
            "extraction_unexpected_error",
            attempt=attempt,
            error=str(e),
        )
        raise ExtractionFailed(f"Unexpected error during extraction: {e}") from e
