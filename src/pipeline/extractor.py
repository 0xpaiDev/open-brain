"""JSON extraction from raw text via Claude."""

import json
import re

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
    reasoning: str | None = Field(default=None, description="Why this decision was made")
    alternatives: list[str] = Field(
        default_factory=list, description="Alternatives that were considered"
    )


class TaskExtract(BaseModel):
    """An extracted actionable task."""

    description: str = Field(..., description="What needs to be done")
    owner: str | None = Field(default=None, description="Who is responsible for this task")
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
    decisions: list[DecisionExtract] = Field(default_factory=list, description="Decisions made")
    tasks: list[TaskExtract] = Field(default_factory=list, description="Actionable tasks")
    base_importance: float = Field(
        default=0.5,
        description="Importance score 0.0–1.0, rated by Claude",
        ge=0.0,
        le=1.0,
    )


# ── Extraction Helpers ────────────────────────────────────────────────────


def _coerce_extraction_data(json_data: dict, attempt: int) -> dict:
    """Coerce flat string arrays to object arrays expected by ExtractionResult.

    Haiku sometimes returns entities/decisions/tasks as plain string arrays
    instead of arrays of objects. This function coerces them and logs a warning
    so prompt quality regressions remain visible.

    Args:
        json_data: Parsed JSON dict from Claude response
        attempt: Retry attempt number (for structured logging)

    Returns:
        json_data with entities/decisions/tasks guaranteed to be object arrays
    """
    coerced_fields: list[str] = []

    entities = json_data.get("entities", [])
    if entities and isinstance(entities[0], str):
        json_data["entities"] = [
            {"name": e, "type": "concept"} for e in entities if isinstance(e, str)
        ]
        coerced_fields.append("entities")

    decisions = json_data.get("decisions", [])
    if decisions and isinstance(decisions[0], str):
        json_data["decisions"] = [
            {"decision": d, "reasoning": None, "alternatives": []}
            for d in decisions
            if isinstance(d, str)
        ]
        coerced_fields.append("decisions")

    tasks = json_data.get("tasks", [])
    if tasks and isinstance(tasks[0], str):
        json_data["tasks"] = [
            {"description": t, "owner": None, "due_date": None} for t in tasks if isinstance(t, str)
        ]
        coerced_fields.append("tasks")

    if coerced_fields:
        logger.warning(
            "extraction_coercion_applied",
            attempt=attempt,
            coerced_fields=coerced_fields,
            note="Claude returned flat string arrays instead of objects — check prompt quality",
        )

    return json_data


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
            max_tokens=2048,
        )

        # Strip markdown code fences if present (Claude sometimes wraps JSON)
        stripped = response_text.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[-1]
            stripped = stripped.rsplit("```", 1)[0].strip()
        else:
            stripped = stripped

        # Parse JSON response — primary attempt
        try:
            json_data = json.loads(stripped)
        except json.JSONDecodeError as primary_err:
            # Fallback: Haiku sometimes writes text before/after the JSON block.
            # Extract the first {...} object from the response.
            match = re.search(r"\{[\s\S]*\}", stripped)
            if match:
                try:
                    json_data = json.loads(match.group())
                    logger.warning(
                        "extraction_json_extracted_from_text",
                        attempt=attempt,
                        note="JSON found embedded in surrounding text — check prompt quality",
                    )
                except json.JSONDecodeError as e:
                    logger.exception(
                        "extraction_json_parse_failed",
                        attempt=attempt,
                        error=str(e),
                        response_text=response_text[:200],
                    )
                    raise ExtractionFailed(f"Failed to parse Claude response as JSON: {e}") from e
            else:
                logger.exception(
                    "extraction_json_parse_failed",
                    attempt=attempt,
                    error=str(primary_err),
                    response_text=response_text[:200],
                )
                raise ExtractionFailed(
                    f"Failed to parse Claude response as JSON: {primary_err}"
                ) from primary_err

        # Coerce flat string arrays to object arrays (Haiku format regression safety net)
        json_data = _coerce_extraction_data(json_data, attempt=attempt)

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
            raise ExtractionFailed(f"Claude response does not match schema: {e}") from e

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
