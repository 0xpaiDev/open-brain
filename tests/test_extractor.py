"""Targeted tests for base_importance behavior in the extraction pipeline.

Verifies that:
- Claude-assigned importance scores pass through correctly (no hardcoding)
- Pydantic schema validation enforces 0.0–1.0 range
- Correct prompt is selected per attempt number
- Default fallback works when base_importance is absent from LLM response
"""

import json
from unittest.mock import AsyncMock

import pytest

from src.llm.client import AnthropicClient, ExtractionFailed
from src.llm.prompts import (
    EXTRACTION_RETRY_PROMPT_1,
    EXTRACTION_RETRY_PROMPT_2,
    EXTRACTION_SYSTEM_PROMPT,
)
from src.pipeline.extractor import EntityExtract, extract

# ── Helpers ───────────────────────────────────────────────────────────────────


def _valid_json(base_importance: float = 0.6, **overrides: object) -> str:
    payload = {
        "type": "memory",
        "content": "test content",
        "summary": "test summary",
        "entities": [],
        "decisions": [],
        "tasks": [],
        "base_importance": base_importance,
        **overrides,
    }
    return json.dumps(payload)


def _mock_client(response: str) -> AsyncMock:
    client = AsyncMock(spec=AnthropicClient)
    client.complete.return_value = response
    return client


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_base_importance_high_value_passes_through() -> None:
    """High importance score assigned by Claude is preserved unchanged."""
    result = await extract("We made an irreversible architecture decision.", attempt=0, client=_mock_client(_valid_json(0.9)))
    assert result.base_importance >= 0.8


@pytest.mark.asyncio
async def test_extract_base_importance_low_value_passes_through() -> None:
    """Low importance score assigned by Claude is preserved unchanged."""
    result = await extract("Lunch order is pizza today.", attempt=0, client=_mock_client(_valid_json(0.2)))
    assert result.base_importance <= 0.4


@pytest.mark.asyncio
async def test_extract_base_importance_is_float_in_valid_range() -> None:
    """A mid-range score is stored as a float within [0.0, 1.0]."""
    result = await extract("Some context note.", attempt=0, client=_mock_client(_valid_json(0.75)))
    assert isinstance(result.base_importance, float)
    assert 0.0 <= result.base_importance <= 1.0


@pytest.mark.asyncio
async def test_extract_base_importance_rejects_above_1_0() -> None:
    """Score above 1.0 raises ExtractionFailed (Pydantic ge/le validation)."""
    with pytest.raises(ExtractionFailed):
        await extract("text", attempt=0, client=_mock_client(_valid_json(1.5)))


@pytest.mark.asyncio
async def test_extract_base_importance_rejects_below_0_0() -> None:
    """Negative score raises ExtractionFailed."""
    with pytest.raises(ExtractionFailed):
        await extract("text", attempt=0, client=_mock_client(_valid_json(-0.1)))


@pytest.mark.asyncio
async def test_extract_base_importance_defaults_when_missing() -> None:
    """When base_importance is absent, Pydantic default of 0.5 is applied."""
    payload = json.dumps({"type": "memory", "content": "test", "entities": [], "decisions": [], "tasks": []})
    result = await extract("text", attempt=0, client=_mock_client(payload))
    assert result.base_importance == 0.5


@pytest.mark.asyncio
async def test_extract_base_importance_valid_at_boundaries() -> None:
    """Boundary values 0.0 and 1.0 are both accepted by the schema."""
    result_low = await extract("text", attempt=0, client=_mock_client(_valid_json(0.0)))
    assert result_low.base_importance == 0.0

    result_high = await extract("text", attempt=0, client=_mock_client(_valid_json(1.0)))
    assert result_high.base_importance == 1.0


@pytest.mark.asyncio
async def test_extract_uses_correct_prompt_per_attempt() -> None:
    """Each attempt number routes to the correct system prompt."""
    client = _mock_client(_valid_json())

    await extract("text", attempt=0, client=client)
    assert client.complete.call_args_list[-1].kwargs["system_prompt"] == EXTRACTION_SYSTEM_PROMPT

    await extract("text", attempt=1, client=client)
    assert client.complete.call_args_list[-1].kwargs["system_prompt"] == EXTRACTION_RETRY_PROMPT_1

    await extract("text", attempt=2, client=client)
    assert client.complete.call_args_list[-1].kwargs["system_prompt"] == EXTRACTION_RETRY_PROMPT_2


@pytest.mark.asyncio
async def test_extract_coerces_entity_strings_to_objects() -> None:
    """Plain string entities are coerced to EntityExtract objects with type='concept'."""
    payload = json.dumps({
        "type": "memory",
        "content": "test content",
        "entities": ["Project Aegis", "Daily Planner agent"],
        "decisions": [],
        "tasks": [],
        "base_importance": 0.5,
    })
    result = await extract("text", attempt=0, client=_mock_client(payload))
    assert len(result.entities) == 2
    assert all(isinstance(e, EntityExtract) for e in result.entities)
    assert result.entities[0].name == "Project Aegis"
    assert result.entities[0].type == "concept"
    assert result.entities[1].name == "Daily Planner agent"


@pytest.mark.asyncio
async def test_extract_coerces_decision_strings_to_objects() -> None:
    """Plain string decisions are coerced to DecisionExtract objects."""
    payload = json.dumps({
        "type": "memory",
        "content": "test content",
        "entities": [],
        "decisions": ["Cut voice pipeline from v0.1", "Start with Daily Planner agent only"],
        "tasks": [],
        "base_importance": 0.5,
    })
    result = await extract("text", attempt=0, client=_mock_client(payload))
    assert len(result.decisions) == 2
    assert result.decisions[0].decision == "Cut voice pipeline from v0.1"
    assert result.decisions[0].reasoning is None
    assert result.decisions[0].alternatives == []


@pytest.mark.asyncio
async def test_extract_coerces_task_strings_to_objects() -> None:
    """Plain string tasks are coerced to TaskExtract objects."""
    payload = json.dumps({
        "type": "memory",
        "content": "test content",
        "entities": [],
        "decisions": [],
        "tasks": ["Write deployment checklist", "Deploy on Friday"],
        "base_importance": 0.5,
    })
    result = await extract("text", attempt=0, client=_mock_client(payload))
    assert len(result.tasks) == 2
    assert result.tasks[0].description == "Write deployment checklist"
    assert result.tasks[0].owner is None
    assert result.tasks[0].due_date is None


@pytest.mark.asyncio
async def test_extract_coercion_does_not_affect_correct_objects() -> None:
    """Valid object arrays pass through coercion unchanged."""
    payload = json.dumps({
        "type": "memory",
        "content": "test content",
        "entities": [{"name": "PostgreSQL", "type": "tool"}],
        "decisions": [{"decision": "Use PostgreSQL", "reasoning": "Better pgvector support", "alternatives": []}],
        "tasks": [{"description": "Run migrations", "owner": "Alice", "due_date": None}],
        "base_importance": 0.7,
    })
    result = await extract("text", attempt=0, client=_mock_client(payload))
    assert result.entities[0].name == "PostgreSQL"
    assert result.entities[0].type == "tool"
    assert result.decisions[0].reasoning == "Better pgvector support"
    assert result.tasks[0].owner == "Alice"


@pytest.mark.asyncio
async def test_extract_uses_max_tokens_2048() -> None:
    """client.complete is called with max_tokens=2048."""
    client = _mock_client(_valid_json())
    await extract("text", attempt=0, client=client)
    assert client.complete.call_args.kwargs["max_tokens"] == 2048


@pytest.mark.asyncio
async def test_extract_handles_json_embedded_in_text() -> None:
    """JSON block preceded by explanatory text is extracted via regex fallback."""
    valid_json = _valid_json(0.6)
    response_with_preamble = f"Here is the structured extraction:\n{valid_json}"
    result = await extract("text", attempt=0, client=_mock_client(response_with_preamble))
    assert result.base_importance == 0.6
    assert result.content == "test content"


@pytest.mark.asyncio
async def test_extract_raises_when_no_json_found() -> None:
    """Response with no JSON object at all raises ExtractionFailed."""
    with pytest.raises(ExtractionFailed):
        await extract("text", attempt=0, client=_mock_client("I cannot process this request."))
